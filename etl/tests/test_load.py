"""
Integration tests for etl/load.py against a real PostgreSQL database.

The rest of the suite either works on plain Python objects (etl/tests/test_transform.py,
test_scoring.py) or checks the API layer against an in-memory SQLite stand-in
(backend/tests/test_api.py). Neither ever executes load.py's actual upsert SQL
-- the ON CONFLICT clauses, the exact column lists, or real Postgres types
(NUMERIC, JSONB). SQLite silently tolerates things Postgres wouldn't, and a
column list drift (e.g. a column added to models.py/migrations but forgotten
in one of load.py's INSERT statements -- which almost happened with
tariff_year) would not be caught by any existing test. This file closes that
gap by running the real functions against a real, migrated Postgres schema.

Requires a real Postgres instance, pointed to by TEST_DATABASE_URL. If unset,
the whole module is skipped so the rest of the suite still runs without
Docker. Bring one up with:

    docker compose up -d db_test
    export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/afg_market_test
    pytest etl/tests/test_load.py -v

CI runs these automatically against a postgres service container (see
.github/workflows/ci.yml).
"""

import pytest
from sqlalchemy import text

from etl import load
from etl.tests.conftest import YEARS
from etl.transform import compute_indicators, enrich_indicators_with_scores

# pg_engine / clean_tables / product_id fixtures live in etl/tests/conftest.py
# (shared with etl/tests/test_pipeline_integration.py) -- pg_engine skips
# automatically, for any test that requests it, when TEST_DATABASE_URL isn't
# set. See that fixture's docstring, or the module docstring above, to run
# these locally.


class TestUpsertProduct:
    def test_insert_creates_row(self, pg_engine):
        pid = load.upsert_product(pg_engine, "Almonds", "Tree Nuts", ["080211"], "desc")
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM products WHERE id = :id"), {"id": pid}
            ).mappings().one()
        assert row["name"] == "Almonds"
        assert row["category"] == "Tree Nuts"
        assert list(row["hs_codes"]) == ["080211"]

    def test_upsert_same_name_updates_in_place(self, pg_engine):
        first_id = load.upsert_product(pg_engine, "Almonds", "Tree Nuts", ["080211"], "old desc")
        second_id = load.upsert_product(
            pg_engine, "Almonds", "Tree Nuts", ["080211", "080212"], "new desc"
        )
        assert second_id == first_id

        with pg_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
            row = conn.execute(
                text("SELECT * FROM products WHERE id = :id"), {"id": first_id}
            ).mappings().one()
        assert count == 1
        assert row["description"] == "new desc"
        assert list(row["hs_codes"]) == ["080211", "080212"]


class TestUpsertMarket:
    def test_known_code_resolves_name(self, pg_engine):
        load.upsert_market(pg_engine, "004", None)
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT country_name FROM markets WHERE country_code = '004'")
            ).mappings().one()
        assert row["country_name"] == "Afghanistan"

    def test_upsert_is_idempotent_and_updates_name(self, pg_engine):
        load.upsert_market(pg_engine, "699", "India (raw)")
        load.upsert_market(pg_engine, "699", "India")

        with pg_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM markets")).scalar()
            row = conn.execute(
                text("SELECT country_name FROM markets WHERE country_code = '699'")
            ).mappings().one()
        assert count == 1
        assert row["country_name"] == "India"

    def test_unrecognized_code_gets_unknown_label(self, pg_engine):
        load.upsert_market(pg_engine, "999", None)
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT country_name FROM markets WHERE country_code = '999'")
            ).mappings().one()
        assert row["country_name"] == "Unknown (999)"


class TestBulkUpsertTradeFlows:
    def test_upsert_is_idempotent(self, pg_engine, product_id):
        row = {
            "product_id": product_id, "importer_code": "699", "importer_name": "India",
            "year": 2024, "trade_value_usd": 100_000, "trade_quantity": 10_000,
            "quantity_unit": "kg", "net_weight_kg": 10_000,
        }
        load.bulk_upsert_trade_flows(pg_engine, [row])
        load.bulk_upsert_trade_flows(pg_engine, [{**row, "trade_value_usd": 150_000}])

        with pg_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM trade_flows WHERE product_id = :pid"), {"pid": product_id}
            ).mappings().all()
        assert len(rows) == 1
        assert float(rows[0]["trade_value_usd"]) == pytest.approx(150_000)

    def test_empty_rows_is_a_noop(self, pg_engine):
        assert load.bulk_upsert_trade_flows(pg_engine, []) == 0


class TestBulkUpsertCompetitorFlows:
    def test_resolves_supplier_name_and_is_idempotent(self, pg_engine, product_id):
        row = {
            "product_id": product_id, "market_code": "699", "year": 2024,
            "supplier_code": "004", "supplier_name": None,
            "trade_value_usd": 200_000, "trade_quantity": 20_000,
        }
        load.bulk_upsert_competitor_flows(pg_engine, [row])
        load.bulk_upsert_competitor_flows(pg_engine, [{**row, "trade_value_usd": 250_000}])

        with pg_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM competitor_flows WHERE product_id = :pid"), {"pid": product_id}
            ).mappings().all()
        assert len(rows) == 1
        assert rows[0]["supplier_name"] == "Afghanistan"
        assert float(rows[0]["trade_value_usd"]) == pytest.approx(250_000)


class TestBulkUpsertMarketContext:
    def test_upsert_is_idempotent(self, pg_engine):
        row = {
            "country_code": "IND", "year": 2024, "gdp_usd": 3.5e12,
            "gdp_per_capita_usd": 2500.0, "lpi_score": 3.4,
            "regulatory_quality": -0.1, "political_stability": -0.6,
        }
        load.bulk_upsert_market_context(pg_engine, [row])
        load.bulk_upsert_market_context(pg_engine, [{**row, "gdp_per_capita_usd": 2600.0}])

        with pg_engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM market_context")).mappings().all()
        assert len(rows) == 1
        assert float(rows[0]["gdp_per_capita_usd"]) == pytest.approx(2600.0)


class TestLoadMarketContext:
    def test_reads_back_upserted_rows(self, pg_engine):
        load.bulk_upsert_market_context(pg_engine, [{
            "country_code": "IND", "year": 2024, "gdp_usd": 3.5e12,
            "gdp_per_capita_usd": 2500.0, "lpi_score": 3.4,
            "regulatory_quality": -0.1, "political_stability": -0.6,
        }])
        rows = load.load_market_context(pg_engine)
        assert len(rows) == 1
        assert rows[0]["country_code"] == "IND"
        assert float(rows[0]["gdp_per_capita_usd"]) == pytest.approx(2500.0)


class TestBulkUpsertIndicators:
    def test_round_trip_and_upsert_is_idempotent(self, pg_engine, product_id, mirror_df, global_df):
        """
        Regression test for the tariff_year class of bug: adding a column to
        models.py/schemas.py without adding it to load.py's INSERT column
        list would silently drop that field on write. Running the real
        compute -> enrich -> load pipeline and reading every value back from
        Postgres is the only way this suite catches that.
        """
        rows = compute_indicators(product_id, ["699"], mirror_df, global_df, YEARS)
        rows = enrich_indicators_with_scores(
            rows, market_context={}, all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 12.5, "indicator": "AHS", "year": 2022}},
        )
        n = load.bulk_upsert_indicators(pg_engine, rows)
        assert n == 1

        # Re-run as a later ETL pass would: same conflict key, new tariff and
        # World Bank data. lpi_score and regulatory_quality/political_stability
        # deliberately come from different years, like a real triennial LPI
        # survey vs. an annual WGI update -- each must keep its own year.
        rows2 = compute_indicators(product_id, ["699"], mirror_df, global_df, YEARS)
        rows2 = enrich_indicators_with_scores(
            rows2,
            market_context={"699": {
                2022: {"lpi_score": 3.4},
                2023: {"regulatory_quality": 0.5, "political_stability": -0.2},
            }},
            all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 7.0, "indicator": "MFN", "year": 2023}},
        )
        load.bulk_upsert_indicators(pg_engine, rows2)

        with pg_engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM indicators WHERE product_id = :pid"), {"pid": product_id}
            ).mappings().all()

        # Exactly one row: the conflict key (product_id, market_code,
        # computed_for_year) updated in place instead of duplicating.
        assert len(result) == 1
        row = result[0]
        assert row["computed_for_year"] == max(YEARS)
        assert float(row["tariff_rate_pct"]) == pytest.approx(7.0)
        assert row["tariff_indicator"] == "MFN"
        assert row["tariff_year"] == 2023
        assert float(row["lpi_score"]) == pytest.approx(3.4)
        assert row["lpi_score_year"] == 2022
        assert float(row["regulatory_quality"]) == pytest.approx(0.5)
        assert row["regulatory_quality_year"] == 2023
        assert float(row["political_stability"]) == pytest.approx(-0.2)
        assert row["political_stability_year"] == 2023
        assert row["opportunity_score"] is not None
        assert 0 <= float(row["opportunity_score"]) <= 100
        # FTA/distance/language are static config lookups for India (699) --
        # confirms the full score_* column set actually persisted, not just
        # the tariff fields this test targets.
        assert row["has_fta"] is True
        assert row["score_distance"] is not None

    def test_empty_rows_is_a_noop(self, pg_engine):
        assert load.bulk_upsert_indicators(pg_engine, []) == 0


class TestLogPipelineRun:
    def test_round_trips_errors_json(self, pg_engine):
        errors = [{"hs": "091020", "stage": "fetch_tariffs", "error": "timeout"}]
        load.log_pipeline_run(pg_engine, status="partial", products_updated=3, errors=errors)

        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, products_updated, errors_json FROM pipeline_runs")
            ).mappings().one()

        assert row["status"] == "partial"
        assert row["products_updated"] == 3
        assert row["errors_json"] == errors
