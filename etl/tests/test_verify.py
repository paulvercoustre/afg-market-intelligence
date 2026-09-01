"""
Tests for etl/verify.py's internal sanity checks.

These checks now gate the monthly ETL workflow (.github/workflows/etl.yml)
-- a bad ETL run is supposed to fail loudly because of them. But nothing
proved the checks themselves actually detect a problem when one exists,
versus e.g. always returning empty because of a query bug (wrong table,
wrong comparison direction, a WHERE clause that can never match). Each test
class here seeds one row that should be flagged clean, and one that
shouldn't -- proving the check both stays quiet on good data and actually
fires on bad data.

Requires TEST_DATABASE_URL, same as etl/tests/test_load.py; skips automatically
without it.
"""

from sqlalchemy import text

from etl import load, verify


def _insert_trade_flow(engine, product_id, **overrides):
    row = {
        "product_id": product_id, "importer_code": "699", "importer_name": "India",
        "year": 2024, "trade_value_usd": 100_000, "trade_quantity": 1_000,
        "quantity_unit": "kg", "net_weight_kg": 1_000,
    }
    row.update(overrides)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trade_flows
                (product_id, importer_code, importer_name, year,
                 trade_value_usd, trade_quantity, quantity_unit, net_weight_kg)
            VALUES
                (:product_id, :importer_code, :importer_name, :year,
                 :trade_value_usd, :trade_quantity, :quantity_unit, :net_weight_kg)
        """), row)


def _insert_competitor_flow(engine, product_id, **overrides):
    row = {
        "product_id": product_id, "market_code": "699", "year": 2024,
        "supplier_code": "156", "supplier_name": "China",
        "trade_value_usd": 500_000, "trade_quantity": 5_000,
    }
    row.update(overrides)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO competitor_flows
                (product_id, market_code, year, supplier_code, supplier_name,
                 trade_value_usd, trade_quantity)
            VALUES
                (:product_id, :market_code, :year, :supplier_code, :supplier_name,
                 :trade_value_usd, :trade_quantity)
        """), row)


def _insert_market_context(engine, **overrides):
    row = {
        "country_code": "IND", "year": 2024, "gdp_usd": 3.5e12,
        "gdp_per_capita_usd": 2500.0, "lpi_score": 3.4,
        "regulatory_quality": -0.1, "political_stability": -0.6,
    }
    row.update(overrides)
    load.bulk_upsert_market_context(engine, [row])


def _insert_indicator(engine, product_id, **overrides):
    row = {
        "product_id": product_id, "market_code": "699", "computed_for_year": 2024,
        "trade_data_year": None,
        "global_market_size_usd": None, "afg_export_value_usd": None,
        "afg_last_export_year": None, "afg_last_export_value_usd": None,
        "yoy_growth_pct": None, "cagr_pct": None, "absolute_growth_usd": None,
        "growth_pct": None, "first_year": None, "last_year": None,
        "market_share_pct": None, "afg_supplier_rank": None,
        "unit_price_usd": None, "price_basis": None, "market_avg_price_usd": None,
        "price_vs_market_pct": None, "price_competitiveness": None,
        "opportunity_score": None, "distance_km": None, "has_fta": None,
        "language_similarity": None, "gdp_per_capita_usd": None,
        "lpi_score": None, "lpi_score_year": None,
        "regulatory_quality": None, "regulatory_quality_year": None,
        "political_stability": None, "political_stability_year": None,
        "tariff_rate_pct": None, "tariff_indicator": None, "tariff_year": None,
        "score_market_size": None, "score_market_growth": None,
        "score_market_quality": None, "score_price_competitiveness": None,
        "score_afg_foothold": None, "score_distance": None,
        "score_language": None, "score_fta": None, "score_tariff": None,
    }
    row.update(overrides)
    load.bulk_upsert_indicators(engine, [row])


class TestCheckNegativeValues:
    def test_clean_when_all_values_non_negative(self, pg_engine, product_id):
        _insert_trade_flow(pg_engine, product_id, trade_value_usd=100_000)
        _insert_competitor_flow(pg_engine, product_id, trade_quantity=5_000)
        assert verify.check_negative_values(pg_engine) == []

    def test_detects_negative_trade_value(self, pg_engine, product_id):
        _insert_trade_flow(pg_engine, product_id, trade_value_usd=-100)
        results = verify.check_negative_values(pg_engine)
        assert len(results) == 1
        assert results[0]["table_name"] == "trade_flows"

    def test_detects_negative_quantity_in_competitor_flows(self, pg_engine, product_id):
        _insert_competitor_flow(pg_engine, product_id, trade_quantity=-5)
        results = verify.check_negative_values(pg_engine)
        assert len(results) == 1
        assert results[0]["table_name"] == "competitor_flows"


class TestCheckDuplicateSupplierCodes:
    def test_clean_when_supplier_codes_consistent(self, pg_engine, product_id):
        _insert_competitor_flow(pg_engine, product_id, supplier_code="156", supplier_name="China")
        assert verify.check_duplicate_supplier_codes(pg_engine) == []

    def test_detects_same_name_resolving_to_different_codes(self, pg_engine, product_id):
        # The signature of an unmapped country-code variant slipping through
        # (e.g. India appearing as both '356' and '699' in the same run).
        _insert_competitor_flow(pg_engine, product_id, supplier_code="699", supplier_name="India")
        _insert_competitor_flow(pg_engine, product_id, supplier_code="356", supplier_name="India")
        results = verify.check_duplicate_supplier_codes(pg_engine)
        assert len(results) == 1
        assert results[0]["supplier_name"] == "India"
        assert results[0]["code_variants"] == 2


class TestCheckMarketContextCompleteness:
    def test_empty_table_returns_zero_total(self, pg_engine):
        result = verify.check_market_context_completeness(pg_engine)
        assert result["total"] == 0

    def test_reports_total_and_per_field_missing_counts(self, pg_engine):
        _insert_market_context(pg_engine, country_code="IND", lpi_score=3.4)
        _insert_market_context(pg_engine, country_code="PAK", lpi_score=None)
        result = verify.check_market_context_completeness(pg_engine)
        assert result["total"] == 2
        assert result["missing_lpi"] == 1
        assert result["missing_gdp"] == 0


class TestCheckMarketShareConsistency:
    def test_clean_when_market_share_matches_recomputed_value(self, pg_engine, product_id):
        # 200,000 / 10,000,000 * 100 = 2.0
        _insert_indicator(pg_engine, product_id, afg_export_value_usd=200_000,
                           global_market_size_usd=10_000_000, market_share_pct=2.0)
        assert verify.check_market_share_consistency(pg_engine) == []

    def test_detects_a_real_mismatch(self, pg_engine, product_id):
        # Stored value (50%) is nowhere near the recomputed value (2%).
        _insert_indicator(pg_engine, product_id, afg_export_value_usd=200_000,
                           global_market_size_usd=10_000_000, market_share_pct=50.0)
        results = verify.check_market_share_consistency(pg_engine)
        assert len(results) == 1
        assert results[0]["market_share_pct"] == 50.0
        assert float(results[0]["recomputed"]) == 2.0

    def test_small_difference_within_tolerance_is_not_flagged(self, pg_engine, product_id):
        # 2.05 vs a recomputed 2.0 -- within the default 0.1 tolerance.
        _insert_indicator(pg_engine, product_id, afg_export_value_usd=200_000,
                           global_market_size_usd=10_000_000, market_share_pct=2.05)
        assert verify.check_market_share_consistency(pg_engine) == []


class TestCheckScoreBounds:
    def test_clean_when_scores_in_range(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, opportunity_score=50.0, score_tariff=80.0)
        assert verify.check_score_bounds(pg_engine) == []

    def test_detects_score_above_100(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, score_tariff=150.0)
        results = verify.check_score_bounds(pg_engine)
        assert len(results) == 1
        assert float(results[0]["score_tariff"]) == 150.0

    def test_detects_score_below_zero(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, opportunity_score=-10.0)
        results = verify.check_score_bounds(pg_engine)
        assert len(results) == 1
        assert float(results[0]["opportunity_score"]) == -10.0

    def test_detects_political_stability_on_old_estimate_scale(self, pg_engine, product_id):
        # Regression test: political_stability is fetched on the WGI "score"
        # scale (0-100, GOV_WGI_PV.SC) -- a stale row still holding a value
        # from the old -2.5..2.5 "estimate" scale (GOV_WGI_PV.EST) must be
        # caught here, the same way an out-of-range score is.
        _insert_indicator(pg_engine, product_id, political_stability=-0.6)
        results = verify.check_score_bounds(pg_engine)
        assert len(results) == 1
        assert float(results[0]["political_stability"]) == -0.6

    def test_clean_when_political_stability_in_0_100_range(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, political_stability=25.03)
        assert verify.check_score_bounds(pg_engine) == []

    def test_detects_regulatory_quality_on_old_estimate_scale(self, pg_engine, product_id):
        # Same regression as political_stability above, but for
        # regulatory_quality (GOV_WGI_RQ.SC vs the old GOV_WGI_RQ.EST).
        _insert_indicator(pg_engine, product_id, regulatory_quality=-0.1)
        results = verify.check_score_bounds(pg_engine)
        assert len(results) == 1
        assert float(results[0]["regulatory_quality"]) == -0.1

    def test_clean_when_regulatory_quality_in_0_100_range(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, regulatory_quality=45.5)
        assert verify.check_score_bounds(pg_engine) == []


class TestCheckProductCoverage:
    def test_reports_covered_and_missing_products(self, pg_engine, product_id):
        # product_id ("Test Saffron") gets an indicator row -- covered.
        _insert_indicator(pg_engine, product_id)
        # A second product with no indicator rows at all -- missing.
        load.upsert_product(pg_engine, "Test Uncovered Product", "Other", ["999999"], "")

        result = verify.check_product_coverage(pg_engine)
        assert "Test Saffron" in result["covered"]
        assert "Test Uncovered Product" in result["missing"]


class TestRunInternalChecks:
    def test_returns_true_when_all_clean(self, pg_engine, product_id):
        _insert_trade_flow(pg_engine, product_id)
        _insert_indicator(pg_engine, product_id, opportunity_score=50.0,
                           afg_export_value_usd=200_000, global_market_size_usd=10_000_000,
                           market_share_pct=2.0)
        assert verify.run_internal_checks(pg_engine) is True

    def test_returns_false_when_a_negative_value_exists(self, pg_engine, product_id):
        _insert_trade_flow(pg_engine, product_id, trade_value_usd=-100)
        assert verify.run_internal_checks(pg_engine) is False

    def test_returns_false_when_a_score_is_out_of_bounds(self, pg_engine, product_id):
        _insert_indicator(pg_engine, product_id, score_market_size=200.0)
        assert verify.run_internal_checks(pg_engine) is False

    def test_incomplete_market_context_alone_does_not_fail_the_run(self, pg_engine, product_id):
        # Missing World Bank fields (WGI lag, non-annual LPI) are expected
        # source-data gaps, not a pipeline bug -- run_internal_checks must
        # not fail the workflow over them. See check_market_context_completeness:
        # it only logs, it never sets all_clean = False.
        _insert_market_context(pg_engine, lpi_score=None, regulatory_quality=None,
                                political_stability=None)
        assert verify.run_internal_checks(pg_engine) is True
