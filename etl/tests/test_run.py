"""
Tests for etl/run.py: failure resilience, plus the pure helper functions that
decide which markets get scored, which get detailed competitor data, and how
a product's tariff rate is aggregated across its HS codes.

Failure resilience was previously only exercised by hand (a real ETL run
that happened to hit a real API error) rather than by a test. Two levels are
covered here:

  1. Inside run_product(): one HS code's fetch raising shouldn't stop the
     product's other HS codes, or crash the product outright.
  2. Inside main()'s concurrent product loop: one product's run_product()
     call raising shouldn't stop the other products in the same run, or
     crash the process.

The helper functions (_all_market_codes, _top_market_codes,
_market_sizes_by_code, _resolve_market_name, _fetch_tariffs_for_product) had
no coverage at all before this file: they're pure-ish (DataFrame/dict in,
value out), directly shape what ends up in Postgres, and are cheap to test
without any mocking or Postgres needed.
"""

import logging
import sys

import pandas as pd
import pytest

from etl import run as etl_run


class TestRunProductHsCodeResilience:
    def test_one_failing_hs_code_does_not_abort_the_product(self, monkeypatch):
        # A product with two HS codes -- config.PRODUCTS doesn't currently
        # have one, but run_product() takes cfg as a plain dict, so this
        # doesn't need a real config entry to exercise the behavior.
        cfg = {"codes": ["080211", "080212"], "category": "Test", "description": "test"}

        def fake_mirror(hs, years):
            if hs == "080211":
                raise RuntimeError("simulated Comtrade failure")
            return pd.DataFrame([{
                "hs_code": hs, "year": 2024, "importer_code": "699",
                "importer_name": "India", "trade_value_usd": 1000.0,
                "trade_quantity": 10.0, "quantity_unit": "kg", "net_weight_kg": 10.0,
            }])

        def fake_global(hs, years):
            return pd.DataFrame([{
                "reporterCode": "699", "partnerCode": "0", "year": 2024,
                "primaryValue": 5000.0, "reporterDesc": "India",
            }])

        monkeypatch.setattr(etl_run.fetch, "fetch_mirror_exports", fake_mirror)
        monkeypatch.setattr(etl_run.fetch, "fetch_global_imports", fake_global)

        # dry_run=True so this never needs a real DB engine.
        result = etl_run.run_product(
            engine=None, product_name="Test Product", cfg=cfg,
            dry_run=True, market_context={},
        )

        # The product as a whole completed (reached the dry-run exit point,
        # not an exception), using only the HS code that succeeded.
        assert result["status"] == "dry_run"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["hs"] == "080211"
        assert result["errors"][0]["stage"] == "fetch_mirror"

    def test_both_hs_codes_failing_is_reported_as_no_data_not_a_crash(self, monkeypatch):
        cfg = {"codes": ["080211", "080212"], "category": "Test", "description": "test"}

        def always_fails(hs, years):
            raise RuntimeError(f"simulated failure for {hs}")

        monkeypatch.setattr(etl_run.fetch, "fetch_mirror_exports", always_fails)
        monkeypatch.setattr(etl_run.fetch, "fetch_global_imports", always_fails)

        result = etl_run.run_product(
            engine=None, product_name="Test Product", cfg=cfg,
            dry_run=True, market_context={},
        )

        assert result["status"] == "no_data"
        assert len(result["errors"]) == 4  # 2 HS codes x 2 fetch stages


class TestMainConcurrentProductResilience:
    def test_one_product_crashing_does_not_abort_the_run(self, monkeypatch, caplog):
        def fake_run_product(engine, product_name, cfg, dry_run, market_context,
                              skip_tariffs=False, refresh_cache=False):
            if product_name == "Cumin Seeds":
                raise RuntimeError("simulated fetch crash")
            return {"product": product_name, "status": "success", "errors": []}

        monkeypatch.setattr(etl_run, "run_product", fake_run_product)
        monkeypatch.setattr(
            sys, "argv",
            # Real product names from config.PRODUCTS -- main() validates
            # --products against that dict before doing anything else.
            ["etl.run", "--products", "Saffron", "Cumin Seeds", "Fenugreek", "--dry-run"],
        )

        with caplog.at_level(logging.INFO, logger="etl.run"):
            # The assertion here IS that this doesn't raise: one product's
            # run_product() crashing must not propagate out of main().
            etl_run.main()

        assert "[Cumin Seeds] run_product crashed: simulated fetch crash" in caplog.text
        assert "2/3 products succeeded" in caplog.text

    def test_all_products_crashing_still_completes_the_run(self, monkeypatch, caplog):
        def always_crashes(engine, product_name, cfg, dry_run, market_context,
                            skip_tariffs=False):
            raise RuntimeError(f"simulated crash for {product_name}")

        monkeypatch.setattr(etl_run, "run_product", always_crashes)
        monkeypatch.setattr(
            sys, "argv",
            ["etl.run", "--products", "Saffron", "Cumin Seeds", "--dry-run"],
        )

        with caplog.at_level(logging.INFO, logger="etl.run"):
            etl_run.main()  # must still not raise

        assert "0/2 products succeeded" in caplog.text


class TestAllMarketCodes:
    def test_empty_df_returns_empty_list(self):
        assert etl_run._all_market_codes(pd.DataFrame()) == []

    def test_missing_reporter_code_column_returns_empty_list(self):
        assert etl_run._all_market_codes(pd.DataFrame({"foo": [1, 2]})) == []

    def test_excludes_world_and_afghanistan(self):
        df = pd.DataFrame({"reporterCode": ["699", "0", "4", "586"]})
        assert set(etl_run._all_market_codes(df)) == {"699", "586"}

    def test_returns_unique_string_codes(self):
        df = pd.DataFrame({"reporterCode": ["699", "699", 586]})
        codes = etl_run._all_market_codes(df)
        assert sorted(codes) == ["586", "699"]
        assert all(isinstance(c, str) for c in codes)


class TestTopMarketCodes:
    def test_empty_global_df_returns_empty_list(self):
        assert etl_run._top_market_codes(pd.DataFrame(), pd.DataFrame(), 5) == []

    def test_selects_top_n_by_latest_year_world_total(self):
        latest = max(etl_run.YEARS)
        global_df = pd.DataFrame([
            {"reporterCode": "699", "partnerCode": "0", "year": latest, "primaryValue": 5_000_000},
            {"reporterCode": "586", "partnerCode": "0", "year": latest, "primaryValue": 9_000_000},
            {"reporterCode": "156", "partnerCode": "0", "year": latest, "primaryValue": 1_000_000},
        ])
        top = etl_run._top_market_codes(pd.DataFrame(), global_df, top_n=2)
        assert top == ["586", "699"]  # descending by primaryValue

    def test_ignores_years_other_than_latest(self):
        latest = max(etl_run.YEARS)
        global_df = pd.DataFrame([
            {"reporterCode": "699", "partnerCode": "0", "year": latest, "primaryValue": 1_000},
            {"reporterCode": "586", "partnerCode": "0", "year": latest - 1, "primaryValue": 999_999_999},
        ])
        top = etl_run._top_market_codes(pd.DataFrame(), global_df, top_n=5)
        assert top == ["699"]

    def test_ignores_non_world_partner_rows(self):
        latest = max(etl_run.YEARS)
        global_df = pd.DataFrame([
            {"reporterCode": "586", "partnerCode": "0", "year": latest, "primaryValue": 1_000},
            {"reporterCode": "699", "partnerCode": "156", "year": latest, "primaryValue": 999_999},
        ])
        top = etl_run._top_market_codes(pd.DataFrame(), global_df, top_n=5)
        # 699 only has a supplier-breakdown row (partnerCode != '0'), no
        # world-total row -- it must not appear, no matter how large that
        # supplier value is.
        assert top == ["586"]


class TestMarketSizesByCode:
    def test_empty_df_returns_empty_dict(self):
        assert etl_run._market_sizes_by_code(pd.DataFrame(), 2024) == {}

    def test_returns_world_totals_by_reporter_for_given_year(self):
        global_df = pd.DataFrame([
            {"reporterCode": "699", "partnerCode": "0", "year": 2024, "primaryValue": 5_000_000},
            {"reporterCode": "586", "partnerCode": "0", "year": 2024, "primaryValue": 2_000_000},
            {"reporterCode": "699", "partnerCode": "156", "year": 2024, "primaryValue": 999_999},
        ])
        sizes = etl_run._market_sizes_by_code(global_df, 2024)
        assert sizes == {"699": 5_000_000.0, "586": 2_000_000.0}

    def test_ignores_other_years(self):
        global_df = pd.DataFrame([
            {"reporterCode": "699", "partnerCode": "0", "year": 2023, "primaryValue": 5_000_000},
            {"reporterCode": "699", "partnerCode": "0", "year": 2024, "primaryValue": 6_000_000},
        ])
        assert etl_run._market_sizes_by_code(global_df, 2024) == {"699": 6_000_000.0}


class TestResolveMarketName:
    def test_uses_reporter_desc_when_present(self):
        global_df = pd.DataFrame([{"reporterCode": "699", "reporterDesc": "India"}])
        assert etl_run._resolve_market_name(global_df, "699") == "India"

    def test_falls_back_to_reporter_iso_when_desc_absent(self):
        global_df = pd.DataFrame([{"reporterCode": "699", "reporterISO": "IND"}])
        assert etl_run._resolve_market_name(global_df, "699") == "IND"

    def test_falls_back_to_country_table_when_code_has_no_rows(self):
        global_df = pd.DataFrame([{"reporterCode": "699", "reporterDesc": "India"}])
        # Afghanistan (004) doesn't appear in this global_df at all -- must
        # still resolve via the static COUNTRY_NAMES_BY_CODE table.
        assert etl_run._resolve_market_name(global_df, "004") == "Afghanistan"

    def test_placeholder_desc_falls_through_to_country_table(self):
        # resolve_country_name() treats 'None'/'nan'/etc. as unusable and
        # falls back to the static table -- confirms _resolve_market_name
        # doesn't short-circuit on a present-but-useless reporterDesc.
        global_df = pd.DataFrame([{"reporterCode": "004", "reporterDesc": "None"}])
        assert etl_run._resolve_market_name(global_df, "004") == "Afghanistan"


class TestFetchTariffsForProduct:
    def test_averages_rate_across_hs_codes_for_same_market(self, monkeypatch):
        def fake_fetch_tariff_rates(market_codes, hs_codes, years, refresh_cache=False):
            return [
                {"market_code": "699", "hs_code": "080211", "tariff_rate_pct": 10.0,
                 "indicator": "AHS", "year": 2023},
                {"market_code": "699", "hs_code": "080212", "tariff_rate_pct": 20.0,
                 "indicator": "AHS", "year": 2023},
            ]

        monkeypatch.setattr(etl_run.fetch, "fetch_tariff_rates", fake_fetch_tariff_rates)
        result = etl_run._fetch_tariffs_for_product(["699"], ["080211", "080212"], [2023, 2024])
        assert result["699"]["rate"] == pytest.approx(15.0)
        assert result["699"]["indicator"] == "AHS"
        assert result["699"]["year"] == 2023

    def test_multiple_markets_kept_independent(self, monkeypatch):
        def fake_fetch_tariff_rates(market_codes, hs_codes, years, refresh_cache=False):
            return [
                {"market_code": "699", "hs_code": "080211", "tariff_rate_pct": 10.0,
                 "indicator": "AHS", "year": 2023},
                {"market_code": "586", "hs_code": "080211", "tariff_rate_pct": 5.0,
                 "indicator": "MFN", "year": 2024},
            ]

        monkeypatch.setattr(etl_run.fetch, "fetch_tariff_rates", fake_fetch_tariff_rates)
        result = etl_run._fetch_tariffs_for_product(["699", "586"], ["080211"], [2023, 2024])
        assert result["699"]["rate"] == pytest.approx(10.0)
        assert result["586"]["rate"] == pytest.approx(5.0)

    def test_empty_rows_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(etl_run.fetch, "fetch_tariff_rates", lambda *a, **k: [])
        assert etl_run._fetch_tariffs_for_product(["699"], ["080211"], [2024]) == {}
