"""Unit tests for etl/transform.py — flows, growth, and indicators."""

import pandas as pd
import pytest

from config import PRICE_COMPETITIVENESS
from etl.tests.conftest import MARKET_CODES, PRODUCT_ID, YEARS
from etl.transform import (
    _float_or_none,
    _growth_metrics,
    _price_competitiveness,
    _resolve_afg_last_export,
    _unit_price,
    compute_indicators,
    to_competitor_flows,
    to_trade_flows,
)


class TestFloatOrNone:
    def test_none_and_nan(self):
        assert _float_or_none(None) is None
        assert _float_or_none(float("nan")) is None
        assert _float_or_none(float("inf")) is None

    def test_valid_numbers(self):
        assert _float_or_none(42) == 42.0
        assert _float_or_none("3.14") == pytest.approx(3.14)

    def test_invalid_strings(self):
        assert _float_or_none("not-a-number") is None


class TestToTradeFlows:
    def test_row_shape(self, mirror_df):
        rows = to_trade_flows(mirror_df, PRODUCT_ID)
        assert len(rows) == len(mirror_df)
        row = rows[0]
        assert row["product_id"] == PRODUCT_ID
        assert "importer_code" in row
        assert "trade_value_usd" in row
        assert row["trade_value_usd"] == pytest.approx(100_000.0)

    def test_empty_dataframe(self):
        assert to_trade_flows(pd.DataFrame(), PRODUCT_ID) == []


class TestToCompetitorFlows:
    def test_excludes_world_aggregate(self, global_df):
        rows = to_competitor_flows(global_df, PRODUCT_ID, ["699"])
        assert all(r["market_code"] == "699" for r in rows)
        assert all(r["supplier_code"] != "0" for r in rows)

    def test_filters_by_market_codes(self, global_df):
        rows = to_competitor_flows(global_df, PRODUCT_ID, ["586"])
        assert len(rows) == 2
        assert {r["supplier_code"] for r in rows} == {"004", "156"}

    def test_resolves_supplier_name(self, global_df):
        rows = to_competitor_flows(global_df, PRODUCT_ID, ["699"])
        afg = next(r for r in rows if r["supplier_code"] == "004")
        assert afg["supplier_name"] == "Afghanistan"

    def test_empty_input(self):
        assert to_competitor_flows(pd.DataFrame(), PRODUCT_ID, ["699"]) == []

    def test_passes_through_quantity_unit(self):
        # quantity_unit is resolved upstream in etl/fetch.py
        # (_resolve_quantity_units) and attached directly to global_df --
        # to_competitor_flows just needs to carry it into the row dict
        # unchanged, same as it already does for trade_value_usd/trade_quantity.
        df = pd.DataFrame([{
            "reporterCode": "699", "partnerCode": "004", "year": 2024,
            "primaryValue": 200_000, "qty": 20_000, "quantity_unit": "m²",
        }])
        rows = to_competitor_flows(df, PRODUCT_ID, ["699"])
        assert rows[0]["quantity_unit"] == "m²"

    def test_missing_quantity_unit_column_is_none(self):
        df = pd.DataFrame([{
            "reporterCode": "699", "partnerCode": "004", "year": 2024,
            "primaryValue": 200_000, "qty": 20_000,
        }])
        rows = to_competitor_flows(df, PRODUCT_ID, ["699"])
        assert rows[0]["quantity_unit"] is None


class TestGrowthMetrics:
    def test_full_growth(self):
        df = pd.DataFrame({
            "year": [2022, 2023, 2024],
            "trade_value_usd": [1_000, 1_500, 2_000],
        })
        result = _growth_metrics(df, [2022, 2023, 2024])
        assert result["first_year"] == 2022
        assert result["last_year"] == 2024
        assert result["yoy"] == pytest.approx(33.333, rel=0.01)
        assert result["cagr"] == pytest.approx(41.421, rel=0.01)
        assert result["absolute"] == pytest.approx(1_000)
        assert result["pct"] == pytest.approx(100.0)

    def test_single_year_returns_empty_metrics(self):
        df = pd.DataFrame({"year": [2024], "trade_value_usd": [1_000]})
        result = _growth_metrics(df, [2024])
        assert result["yoy"] is None
        assert result["cagr"] is None

    def test_zero_first_value_pct_is_none(self):
        df = pd.DataFrame({
            "year": [2022, 2023],
            "trade_value_usd": [0, 1_000],
        })
        result = _growth_metrics(df, [2022, 2023])
        assert result["pct"] is None
        assert result["absolute"] == pytest.approx(1_000)
        # A window search can't recover a usable cagr from a $0 opening year
        # either (division by zero), but that's fine -- absolute/pct above
        # don't depend on it, and cagr/first_year/last_year correctly stay
        # None together rather than reporting a span with no real cagr.
        assert result["cagr"] is None
        assert result["first_year"] is None
        assert result["last_year"] is None

    def test_cagr_falls_back_past_a_near_zero_opening_year(self):
        # Real case (Dried Apricots -> France): a $6.35 trace opening year
        # makes the naive 2022-2025 cagr an artifact (+1080%), masking that
        # the market actually declined once that opening year is dropped.
        # It also made the stored growth_pct read +164,046% (the same
        # artifact, un-annualized) -- pct must share cagr's fixed window.
        df = pd.DataFrame({
            "year": [2022, 2023, 2024, 2025],
            "trade_value_usd": [6.35, 72_692.83, 19_165.71, 10_423.27],
        })
        result = _growth_metrics(df, [2022, 2023, 2024, 2025])
        assert result["first_year"] == 2023
        assert result["last_year"] == 2025
        assert result["cagr"] == pytest.approx(-62.13, abs=0.01)
        assert result["pct"] == pytest.approx(-85.66, abs=0.01)
        # absolute is the one exception -- it's unaffected by the cagr
        # window search, and still describes the full raw 2022-2025 span.
        assert result["absolute"] == pytest.approx(10_423.27 - 6.35)

    def test_cagr_falls_back_past_an_anomalous_final_year(self):
        # Same idea, opposite end: a one-off spike in the LAST year (not a
        # near-zero base) makes the naive cagr an artifact too. The search
        # isn't limited to trimming the start -- it keeps narrowing until
        # it finds any sensical window, which here means excluding 2024.
        df = pd.DataFrame({
            "year": [2022, 2023, 2024],
            "trade_value_usd": [10_000, 12_000, 5_000_000],
        })
        result = _growth_metrics(df, [2022, 2023, 2024])
        assert result["first_year"] == 2022
        assert result["last_year"] == 2023
        assert result["cagr"] == pytest.approx(20.0, abs=0.01)
        # Same 1-year window, so pct (un-annualized) equals cagr here --
        # they only diverge for windows longer than 1 year.
        assert result["pct"] == pytest.approx(20.0, abs=0.01)

    def test_cagr_none_when_no_window_is_sensical(self):
        # Only 2 data points -- if the one and only possible window still
        # isn't sensical, there's nothing smaller to fall back to.
        df = pd.DataFrame({
            "year": [2022, 2023],
            "trade_value_usd": [10, 1_000],
        })
        result = _growth_metrics(df, [2022, 2023])
        assert result["cagr"] is None
        assert result["first_year"] is None
        assert result["last_year"] is None
        # pct shares cagr's window search -- no sensical window means pct
        # is None too, not the raw (equally artifact-prone) 9900% figure.
        assert result["pct"] is None
        # absolute is unaffected either way -- always the full raw span.
        assert result["absolute"] == pytest.approx(990.0)


class TestComputeIndicators:
    def test_returns_one_row_per_market(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, MARKET_CODES, mirror_df, global_df, YEARS)
        assert len(rows) == len(MARKET_CODES)
        codes = {r["market_code"] for r in rows}
        assert codes == set(MARKET_CODES)

    def test_market_share(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        row = rows[0]
        # 200_000 / 10_000_000 * 100 = 2.0%
        assert row["market_share_pct"] == pytest.approx(2.0)

    def test_afg_supplier_rank(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        # Afghanistan is smallest of 3 suppliers in 2024
        assert rows[0]["afg_supplier_rank"] == 3

    def test_unit_price_from_quantity(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        # 200_000 / 20_000 = 10.0
        assert rows[0]["unit_price_usd"] == pytest.approx(10.0)

    def test_price_competitiveness_label(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["842"], mirror_df, global_df, YEARS)
        row = rows[0]
        # Afg $10 vs market avg ~$15.67 → ~36% below → Substantially Below Market
        assert row["price_competitiveness"] == "Substantially Below Market"
        assert row["price_vs_market_pct"] < PRICE_COMPETITIVENESS["substantially_below_market"]

    def test_empty_mirror_returns_empty(self, global_df):
        assert compute_indicators(PRODUCT_ID, MARKET_CODES, pd.DataFrame(), global_df, YEARS) == []

    def test_price_basis_stored_as_native_unit_end_to_end(self):
        # End-to-end version of TestUnitPrice's native-basis case, through
        # compute_indicators -- confirms the resulting row's price_basis
        # ("m²") and unit_price_usd both reflect the native-unit computation,
        # the way a real carpets product does (see config.NATIVE_UNIT_PRICE_BASES).
        global_df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "0", "year": 2024, "primaryValue": 1_000_000},
            {"reporterCode": "999", "partnerCode": "004", "year": 2024,
             "primaryValue": 1000, "qty": 50, "quantity_unit": "m²"},  # Afghanistan, same row also drives afg_to_market below
        ])
        mirror_df = pd.DataFrame([{
            "hs_code": "570210", "year": 2024, "importer_code": "999", "importer_name": "Market 999",
            "trade_value_usd": 1000, "trade_quantity": 50, "quantity_unit": "m²", "net_weight_kg": 2000,
        }])
        rows = compute_indicators(PRODUCT_ID, ["999"], mirror_df, global_df, [2024])
        row = rows[0]
        assert row["price_basis"] == "m²"
        assert row["unit_price_usd"] == pytest.approx(20.0)  # 1000/50, not 1000/2000

    def test_price_competitiveness_excludes_unit_mismatched_outlier(self):
        # Three suppliers cluster around $10-12/unit (consistent reporting
        # units); Romania's implied price of $5,000/unit is ~500x the pack --
        # the same signature as a real quantity-unit mismatch (e.g. reporting
        # in "pieces" while everyone else reports in kg), not a genuine price.
        # It should be excluded from market_avg_price_usd, not silently
        # blend a nonsense value into the comparison Afghanistan is judged
        # against.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024, "primaryValue": 1000, "netWgt": 100},   # $10
            {"reporterCode": "999", "partnerCode": "792", "year": 2024, "primaryValue": 1200, "netWgt": 100},   # $12
            {"reporterCode": "999", "partnerCode": "586", "year": 2024, "primaryValue": 900, "netWgt": 90},     # $10
            {"reporterCode": "999", "partnerCode": "642", "year": 2024, "primaryValue": 50000, "netWgt": 10},   # $5,000 outlier
        ])
        market_avg, pct_diff, label = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        # Without trimming this would be (10+12+10+5000)/4 = 1258 -- confirm
        # the outlier didn't drag the average anywhere near that.
        assert market_avg == pytest.approx((10 + 12 + 10) / 3)
        assert market_avg < 20

    def test_price_competitiveness_no_outliers_unaffected(self):
        # Sanity check: when every supplier's implied price is within a
        # normal range, trimming must be a no-op -- confirms the fix doesn't
        # change behavior for the common case, only the pathological one.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024, "primaryValue": 1000, "netWgt": 100},  # $10
            {"reporterCode": "999", "partnerCode": "792", "year": 2024, "primaryValue": 1500, "netWgt": 100},  # $15
            {"reporterCode": "999", "partnerCode": "586", "year": 2024, "primaryValue": 2000, "netWgt": 100},  # $20
        ])
        market_avg, pct_diff, label = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg == pytest.approx((10 + 15 + 20) / 3)

    def test_price_competitiveness_ignores_quantity_even_when_present(self):
        # netWgt (kg) is used exclusively -- qty is never consulted, even
        # when it's the only thing that would give a different number. Row
        # gives $20/unit via qty but $10/kg via netWgt; confirm netWgt wins
        # and qty is simply irrelevant to the result.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024,
             "primaryValue": 1000, "qty": 50, "netWgt": 100},
        ])
        market_avg, pct_diff, label = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg == pytest.approx(10.0)

    def test_price_competitiveness_none_when_no_supplier_has_weight_data(self):
        # Policy: no fallback to the free-form "quantity" field. A supplier
        # (or every supplier) missing net weight is excluded rather than
        # compared on a possibly-incompatible unit -- if that leaves nobody
        # to compare against, the whole comparison is left undetermined
        # (None), not silently computed on qty.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024,
             "primaryValue": 500, "qty": 50},  # qty present, netWgt absent
        ])
        market_avg, pct_diff, label = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg is None
        assert pct_diff is None
        assert label is None

    def test_price_competitiveness_excludes_only_suppliers_missing_weight(self):
        # Mixed case: some suppliers report weight, one doesn't -- the
        # weightless one is dropped from the comparison, the rest still form
        # a valid market average (not an all-or-nothing None).
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024, "primaryValue": 1000, "netWgt": 100},  # $10
            {"reporterCode": "999", "partnerCode": "792", "year": 2024, "primaryValue": 1500, "netWgt": 100},  # $15
            {"reporterCode": "999", "partnerCode": "586", "year": 2024, "primaryValue": 900, "qty": 90},       # no netWgt -- excluded
        ])
        market_avg, pct_diff, label = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg == pytest.approx((10 + 15) / 2)

    def test_uses_native_basis_when_afg_basis_is_a_native_unit(self):
        # afg_basis="m²" -- competitor prices must be computed the same way
        # (value/qty on rows reporting "m²"), not value/netWgt.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024,
             "primaryValue": 1000, "qty": 50, "quantity_unit": "m²", "netWgt": 999},  # $20/m² (netWgt would give $1.00 -- must not be used)
        ])
        market_avg, _, _ = _price_competitiveness(df, "999", 18.0, "m²", 2024)
        assert market_avg == pytest.approx(20.0)

    def test_native_basis_excludes_suppliers_reporting_a_different_unit(self):
        # afg_basis="m²" -- a competitor reporting "u" (pieces) instead is
        # excluded from the comparison entirely, not converted or mixed in.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024,
             "primaryValue": 1000, "qty": 50, "quantity_unit": "m²"},   # $20/m²
            {"reporterCode": "999", "partnerCode": "792", "year": 2024,
             "primaryValue": 500, "qty": 25, "quantity_unit": "u"},     # different unit -- excluded
        ])
        market_avg, _, _ = _price_competitiveness(df, "999", 18.0, "m²", 2024)
        assert market_avg == pytest.approx(20.0)

    def test_none_when_afg_basis_is_none(self):
        # afg_price without a basis (shouldn't normally happen since
        # _unit_price always pairs them) still can't be compared against
        # anything -- must not silently assume net_weight_kg.
        df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "699", "year": 2024,
             "primaryValue": 1000, "netWgt": 100},
        ])
        assert _price_competitiveness(df, "999", 9.0, None, 2024) == (None, None, None)

    def test_computed_for_latest_year(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        assert rows[0]["computed_for_year"] == max(YEARS)

    def test_trade_data_year_matches_when_current_year_reported(self, mirror_df, global_df):
        """Normal case: the market has data for the latest year, so trade_data_year == computed_for_year."""
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        assert rows[0]["trade_data_year"] == max(YEARS)

    def test_falls_back_to_markets_own_latest_year_when_newest_year_unreported(
        self, mirror_df, global_df
    ):
        """
        Regression test: fixture data for market 699 only goes up to 2024
        (see conftest.YEARS). Asking compute_indicators to target a year
        past that (2025, simulating config.YEARS being extended before this
        market has reported anything for it) must not leave the trade
        fields empty -- it should fall back to 699's own latest available
        year (2024) the same way World Bank fields already do, and record
        that year in trade_data_year so callers can tell.
        """
        years_with_unreported_2025 = [*YEARS, 2025]
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, years_with_unreported_2025)
        row = rows[0]

        assert row["computed_for_year"] == 2025
        assert row["trade_data_year"] == max(YEARS)  # 2024, the real latest year with data
        # Trade fields must be populated from the fallback year, not empty.
        assert row["global_market_size_usd"] is not None
        assert row["afg_export_value_usd"] is not None
        assert row["market_share_pct"] == pytest.approx(2.0)  # same as the current-year test
        assert row["unit_price_usd"] == pytest.approx(10.0)

    def test_afg_last_export_matches_current_year_when_data_exists(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        row = rows[0]
        assert row["afg_last_export_year"] == row["trade_data_year"] == max(YEARS)
        assert row["afg_last_export_value_usd"] == pytest.approx(row["afg_export_value_usd"])

    def test_surfaces_earlier_year_when_current_year_afg_data_is_a_genuine_zero(self):
        """
        Market 999 fully reported 2024 (world totals exist for it, so
        trade_data_year resolves to 2024 per _resolve_trade_year), but
        Afghanistan isn't in that year's partner breakdown -- a real signal,
        not a reporting lag (see _resolve_trade_year's docstring). This must
        not pull trade_data_year or afg_export_value_usd backward to find an
        Afghan figure -- but afg_last_export_year/value should still surface
        Afghanistan's last actual export (2023) for context.
        """
        global_df = pd.DataFrame([
            {"reporterCode": "999", "partnerCode": "0", "year": 2022, "primaryValue": 1_000_000},
            {"reporterCode": "999", "partnerCode": "0", "year": 2023, "primaryValue": 1_100_000},
            {"reporterCode": "999", "partnerCode": "0", "year": 2024, "primaryValue": 1_200_000},
        ])
        mirror_df = pd.DataFrame([
            {"hs_code": "080211", "year": 2022, "importer_code": "999", "importer_name": "Market 999",
             "trade_value_usd": 30_000, "trade_quantity": 3_000, "quantity_unit": "kg", "net_weight_kg": 3_000},
            {"hs_code": "080211", "year": 2023, "importer_code": "999", "importer_name": "Market 999",
             "trade_value_usd": 40_000, "trade_quantity": 4_000, "quantity_unit": "kg", "net_weight_kg": 4_000},
            # No 2024 row -- Afghanistan genuinely absent from 999's 2024 partner breakdown.
        ])
        rows = compute_indicators(PRODUCT_ID, ["999"], mirror_df, global_df, YEARS)
        row = rows[0]

        assert row["trade_data_year"] == 2024
        assert row["afg_export_value_usd"] is None
        assert row["afg_last_export_year"] == 2023
        assert row["afg_last_export_value_usd"] == pytest.approx(40_000)


class TestResolveAfgLastExport:
    def test_empty_input_returns_none(self):
        assert _resolve_afg_last_export(pd.DataFrame(), 2024) == (None, None)

    def test_returns_latest_eligible_year(self):
        df = pd.DataFrame([
            {"year": 2022, "trade_value_usd": 10_000},
            {"year": 2023, "trade_value_usd": 20_000},
        ])
        assert _resolve_afg_last_export(df, 2024) == (2023, 20_000.0)

    def test_ignores_years_below_the_floor(self):
        # 2019 predates AFG_LAST_EXPORT_FLOOR_YEAR (2022) -- excluded even
        # though it's the only year with data, so a single old shipment
        # doesn't get displayed as if the market were still active.
        df = pd.DataFrame([{"year": 2019, "trade_value_usd": 5_000}])
        assert _resolve_afg_last_export(df, 2024) == (None, None)

    def test_ignores_years_after_up_to_year(self):
        df = pd.DataFrame([
            {"year": 2023, "trade_value_usd": 10_000},
            {"year": 2025, "trade_value_usd": 99_000},
        ])
        assert _resolve_afg_last_export(df, 2024) == (2023, 10_000.0)

    def test_ignores_zero_value_years(self):
        df = pd.DataFrame([
            {"year": 2022, "trade_value_usd": 10_000},
            {"year": 2023, "trade_value_usd": 0},
        ])
        assert _resolve_afg_last_export(df, 2024) == (2022, 10_000.0)


class TestUnitPrice:
    def test_ignores_quantity_without_a_recognised_unit(self):
        # trade_quantity implies $20/unit; net_weight_kg implies $5/kg. No
        # quantity_unit is present here at all, so trade_quantity can't be
        # trusted as a comparable basis -- net_weight_kg wins, same as
        # before NATIVE_UNIT_PRICE_BASES existed.
        df = pd.DataFrame([{
            "year": 2024, "trade_value_usd": 1000,
            "trade_quantity": 50, "net_weight_kg": 200,
        }])
        assert _unit_price(df, 2024) == (pytest.approx(5.0), "kg")

    def test_ignores_quantity_when_unit_is_not_a_native_basis(self):
        # quantity_unit is populated and consistent ("l", litres) but isn't
        # one of NATIVE_UNIT_PRICE_BASES (config.py) -- falls back to
        # net_weight_kg exactly like the no-unit case above.
        df = pd.DataFrame([{
            "year": 2024, "trade_value_usd": 1000,
            "trade_quantity": 50, "quantity_unit": "l", "net_weight_kg": 200,
        }])
        assert _unit_price(df, 2024) == (pytest.approx(5.0), "kg")

    def test_uses_native_unit_when_consistent_and_recognised(self):
        # quantity_unit is "m²" (carpets) on every row and is one of
        # NATIVE_UNIT_PRICE_BASES -- this basis wins over net_weight_kg,
        # since it's the more economically meaningful one for this product.
        df = pd.DataFrame([
            {"year": 2024, "trade_value_usd": 600, "trade_quantity": 30,
             "quantity_unit": "m²", "net_weight_kg": 200},
            {"year": 2024, "trade_value_usd": 400, "trade_quantity": 20,
             "quantity_unit": "m²", "net_weight_kg": 100},
        ])
        # value=1000, qty=50 -> $20/m²  (vs. $1000/300kg = $3.33/kg if it
        # had fallen back instead -- confirms the native basis, not kg, won)
        assert _unit_price(df, 2024) == (pytest.approx(20.0), "m²")

    def test_falls_back_to_net_weight_when_unit_is_inconsistent(self):
        # One row reports m², the other reports u (pieces) -- no single
        # basis every row agrees on, so this must not guess; falls back to
        # net_weight_kg rather than mixing m² and pieces into one "price".
        df = pd.DataFrame([
            {"year": 2024, "trade_value_usd": 600, "trade_quantity": 30,
             "quantity_unit": "m²", "net_weight_kg": 200},
            {"year": 2024, "trade_value_usd": 400, "trade_quantity": 20,
             "quantity_unit": "u", "net_weight_kg": 100},
        ])
        assert _unit_price(df, 2024) == (pytest.approx(1000 / 300), "kg")

    def test_falls_back_to_net_weight_when_native_qty_is_zero(self):
        # Unit is recognised and consistent, but the quantity itself sums to
        # zero (division by it would be meaningless) -- falls back to
        # net_weight_kg instead of returning a nonsensical/undefined price.
        df = pd.DataFrame([{
            "year": 2024, "trade_value_usd": 500,
            "trade_quantity": 0, "quantity_unit": "m²", "net_weight_kg": 100,
        }])
        assert _unit_price(df, 2024) == (pytest.approx(5.0), "kg")

    def test_none_when_weight_missing_even_with_quantity_present(self):
        # Policy: no fallback to the free-form "quantity" field beyond the
        # NATIVE_UNIT_PRICE_BASES allowlist -- a mismatched unit there would
        # silently distort the comparison this is meant to protect (see
        # DATA_SPECIFICATION.md §4.5). Leaving this None is the intended
        # outcome, not a bug: it propagates through _price_competitiveness()
        # and surfaces as "no unit data for comparison" in the UI instead of
        # a number we can't verify.
        df = pd.DataFrame([{
            "year": 2024, "trade_value_usd": 500, "trade_quantity": 50,
        }])
        assert _unit_price(df, 2024) == (None, None)

    def test_none_when_neither_available(self):
        df = pd.DataFrame([{"year": 2024, "trade_value_usd": 500}])
        assert _unit_price(df, 2024) == (None, None)


class TestPriceOutlierBandRobustness:
    """
    Literature on cleaning unit-value data recommends checking that findings
    aren't an artifact of one arbitrarily-chosen exclusion threshold (e.g.
    varying it and confirming conclusions hold) rather than trusting a single
    cutoff blindly. This is that check for PRICE_OUTLIER_BAND_MULTIPLIER.

    Suppliers: a "normal" cluster (20-65, a realistic ~3x spread of genuine
    price variation) plus two unit-mismatched outliers (2,000 and 3,000,
    ~30-45x the top of the normal cluster -- comparable in spirit to the real
    Woven Carpets/Italy case, $11-$121 normal vs $3,872-$5,835 mismatched).
    """

    NORMAL_CLUSTER = [20, 22, 24, 30, 45, 60, 65]
    OUTLIERS = [2000, 3000]

    def _supplier_df(self):
        rows = []
        for i, price in enumerate(self.NORMAL_CLUSTER + self.OUTLIERS):
            rows.append({
                "reporterCode": "999", "partnerCode": str(100 + i), "year": 2024,
                "primaryValue": price * 10, "netWgt": 10,  # value/netWgt = price
            })
        return pd.DataFrame(rows)

    @pytest.mark.parametrize("multiplier", [3.0, 5.0, 10.0, 20.0])
    def test_stable_across_reasonable_thresholds(self, monkeypatch, multiplier):
        # For any reasonably strict threshold, both outliers get excluded and
        # market_avg lands on the normal cluster's mean regardless of exactly
        # which multiplier was chosen -- the conclusion isn't an artifact of
        # picking 10.0 specifically.
        monkeypatch.setattr("etl.transform.PRICE_OUTLIER_BAND_MULTIPLIER", multiplier)
        df = self._supplier_df()
        market_avg, _, _ = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg == pytest.approx(sum(self.NORMAL_CLUSTER) / len(self.NORMAL_CLUSTER))

    def test_breaks_down_at_an_unreasonably_generous_threshold(self, monkeypatch):
        # Honest counterpoint to the above: the band isn't magic. At a wide
        # enough multiplier one of the two outliers (2,000) falls back inside
        # the band and starts contaminating the average again -- confirming
        # PRICE_OUTLIER_BAND_MULTIPLIER=10.0 is a deliberate choice within a
        # working range, not just "bigger is always safe".
        monkeypatch.setattr("etl.transform.PRICE_OUTLIER_BAND_MULTIPLIER", 50.0)
        df = self._supplier_df()
        market_avg, _, _ = _price_competitiveness(df, "999", 9.0, "kg", 2024)
        assert market_avg != pytest.approx(sum(self.NORMAL_CLUSTER) / len(self.NORMAL_CLUSTER))
