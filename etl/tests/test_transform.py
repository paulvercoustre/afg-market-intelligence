"""Unit tests for etl/transform.py — flows, growth, and indicators."""

import pandas as pd
import pytest

from config import PRICE_COMPETITIVENESS
from etl.tests.conftest import MARKET_CODES, PRODUCT_ID, YEARS
from etl.transform import (
    _float_or_none,
    _growth_metrics,
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
        # Afg $10 vs market avg ~$15.67 → ~36% below → Highly Competitive
        assert row["price_competitiveness"] == "Highly Competitive"
        assert row["price_vs_market_pct"] < PRICE_COMPETITIVENESS["highly_competitive"]

    def test_empty_mirror_returns_empty(self, global_df):
        assert compute_indicators(PRODUCT_ID, MARKET_CODES, pd.DataFrame(), global_df, YEARS) == []

    def test_computed_for_latest_year(self, mirror_df, global_df):
        rows = compute_indicators(PRODUCT_ID, ["699"], mirror_df, global_df, YEARS)
        assert rows[0]["computed_for_year"] == max(YEARS)
