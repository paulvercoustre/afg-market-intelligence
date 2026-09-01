"""
API contract tests — verify endpoint shapes without requiring a live DB.

Uses httpx TestClient with the FastAPI app and an in-memory SQLite DB
(via a dependency override) so tests run in CI without Docker.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import get_db
from backend.main import app

# ── Test DB setup (SQLite in-memory) ─────────────────────────────────────────

SQLITE_URL = "sqlite://"

test_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(test_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    # Raw SQL avoids ARRAY/JSONB/BOOLEAN types not supported in SQLite
    with test_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                hs_codes TEXT NOT NULL,
                description TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS markets (
                id INTEGER PRIMARY KEY,
                country_code TEXT NOT NULL UNIQUE,
                country_name TEXT,
                region TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_context (
                id INTEGER PRIMARY KEY,
                country_code TEXT NOT NULL,
                year INTEGER NOT NULL,
                gdp_usd REAL,
                gdp_per_capita_usd REAL,
                lpi_score REAL,
                regulatory_quality REAL,
                political_stability REAL,
                fetched_at TEXT,
                UNIQUE(country_code, year)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trade_flows (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                importer_code TEXT NOT NULL,
                importer_name TEXT,
                year INTEGER NOT NULL,
                trade_value_usd REAL,
                trade_quantity REAL,
                quantity_unit TEXT,
                net_weight_kg REAL,
                fetched_at TEXT,
                UNIQUE(product_id, importer_code, year)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS competitor_flows (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                market_code TEXT NOT NULL,
                year INTEGER NOT NULL,
                supplier_code TEXT NOT NULL,
                supplier_name TEXT NOT NULL,
                trade_value_usd REAL,
                trade_quantity REAL,
                quantity_unit TEXT,
                UNIQUE(product_id, market_code, supplier_code, year)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS indicators (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                market_code TEXT NOT NULL,
                computed_for_year INTEGER NOT NULL,
                trade_data_year INTEGER,
                global_market_size_usd REAL,
                afg_export_value_usd REAL,
                afg_last_export_year INTEGER,
                afg_last_export_value_usd REAL,
                yoy_growth_pct REAL,
                cagr_pct REAL,
                absolute_growth_usd REAL,
                growth_pct REAL,
                first_year INTEGER,
                last_year INTEGER,
                market_share_pct REAL,
                afg_supplier_rank INTEGER,
                unit_price_usd REAL,
                price_basis TEXT,
                market_avg_price_usd REAL,
                price_vs_market_pct REAL,
                price_competitiveness TEXT,
                opportunity_score REAL,
                distance_km INTEGER,
                has_fta INTEGER,
                language_similarity REAL,
                gdp_per_capita_usd REAL,
                lpi_score REAL,
                lpi_score_year INTEGER,
                regulatory_quality REAL,
                regulatory_quality_year INTEGER,
                political_stability REAL,
                political_stability_year INTEGER,
                tariff_rate_pct REAL,
                tariff_indicator TEXT,
                tariff_year INTEGER,
                score_market_size REAL,
                score_market_growth REAL,
                score_market_quality REAL,
                score_price_competitiveness REAL,
                score_afg_foothold REAL,
                score_distance REAL,
                score_language REAL,
                score_fta REAL,
                score_tariff REAL,
                computed_at TEXT,
                UNIQUE(product_id, market_code, computed_for_year)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY,
                run_at TEXT,
                status TEXT NOT NULL,
                products_updated INTEGER DEFAULT 0,
                errors_json TEXT
            )
        """))
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Insert minimal fixtures for tests that need data."""
    with TestingSession() as db:
        db.execute(text(
            "INSERT OR IGNORE INTO products (name, category, hs_codes, description) "
            "VALUES ('Saffron', 'Spices & Herbs', '091020', 'Saffron stigmas')"
        ))
        db.execute(text(
            "INSERT OR IGNORE INTO markets (country_code, country_name) "
            "VALUES ('699', 'India')"
        ))
        db.execute(text(
            "INSERT OR IGNORE INTO markets (country_code, country_name) "
            "VALUES ('276', 'Germany')"
        ))
        db.execute(text("""
            INSERT OR IGNORE INTO indicators (
                product_id, market_code, computed_for_year, trade_data_year,
                afg_export_value_usd, global_market_size_usd,
                afg_last_export_year, afg_last_export_value_usd,
                market_share_pct, afg_supplier_rank,
                yoy_growth_pct, cagr_pct, absolute_growth_usd, growth_pct,
                first_year, last_year, price_competitiveness,
                opportunity_score, distance_km, has_fta, language_similarity,
                gdp_per_capita_usd, lpi_score, lpi_score_year,
                regulatory_quality, regulatory_quality_year,
                political_stability, political_stability_year,
                tariff_rate_pct, tariff_indicator, tariff_year,
                score_market_size, score_market_growth, score_market_quality,
                score_price_competitiveness, score_afg_foothold,
                score_distance, score_language, score_fta, score_tariff
            )
            SELECT
                p.id, '699', 2024, 2024,
                1500000, 50000000,
                2024, 1500000,
                3.0, 2,
                10.5, 8.2, 200000, 15.4,
                2021, 2024, 'Below Market',
                72.5, 1000, 0, 0.2,
                2200, 3.5, 2022,
                0.8, 2024,
                0.5, 2024,
                30.0, 'AHS', 2022,
                65.0, 60.0, 70.0, 75.0, 45.0, 93.0, 20.0, 0.0, 10.0
            FROM products p WHERE p.name = 'Saffron'
        """))
        db.execute(text("""
            INSERT OR IGNORE INTO indicators (
                product_id, market_code, computed_for_year, trade_data_year,
                afg_export_value_usd, global_market_size_usd,
                afg_last_export_year, afg_last_export_value_usd,
                market_share_pct, afg_supplier_rank,
                yoy_growth_pct, cagr_pct, absolute_growth_usd, growth_pct,
                first_year, last_year, price_competitiveness,
                opportunity_score, distance_km, has_fta, language_similarity,
                gdp_per_capita_usd, lpi_score, regulatory_quality, political_stability,
                tariff_rate_pct, tariff_indicator,
                score_market_size, score_market_growth, score_market_quality,
                score_price_competitiveness, score_afg_foothold,
                score_distance, score_language, score_fta, score_tariff
            )
            SELECT
                p.id, '276', 2024, 2024,
                800000, 80000000,
                2024, 800000,
                1.0, 5,
                5.0, 4.2, 80000, 10.4,
                2021, 2024, 'Near Market',
                68.0, 5500, 1, 0.05,
                48000, 4.1, 1.5, 0.9,
                0.0, 'AHS',
                70.0, 55.0, 88.0, 50.0, 38.0, 33.0, 5.0, 100.0, 100.0
            FROM products p WHERE p.name = 'Saffron'
        """))
        db.execute(text(
            "INSERT OR IGNORE INTO markets (country_code, country_name) "
            "VALUES ('144', 'Sri Lanka')"
        ))
        db.execute(text("""
            INSERT OR IGNORE INTO indicators (
                product_id, market_code, computed_for_year, trade_data_year,
                afg_export_value_usd, global_market_size_usd,
                afg_last_export_year, afg_last_export_value_usd,
                market_share_pct, afg_supplier_rank,
                yoy_growth_pct, cagr_pct, absolute_growth_usd, growth_pct,
                first_year, last_year, price_competitiveness,
                opportunity_score, distance_km, has_fta, language_similarity,
                gdp_per_capita_usd, lpi_score, regulatory_quality, political_stability,
                tariff_rate_pct, tariff_indicator,
                score_market_size, score_market_growth, score_market_quality,
                score_price_competitiveness, score_afg_foothold,
                score_distance, score_language, score_fta, score_tariff
            )
            SELECT
                p.id, '144', 2024, NULL,
                NULL, 90000000,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL, NULL, NULL,
                2021, 2024, 'Near Market',
                80.0, 3000, 0, 0.1,
                4000, 3.0, 0.2, 0.1,
                NULL, NULL,
                90.0, 50.0, 55.0, 50.0, 25.0, 80.0, 10.0, 0.0, 50.0
            FROM products p WHERE p.name = 'Saffron'
        """))
        db.execute(text("""
            INSERT OR IGNORE INTO competitor_flows
                (product_id, market_code, year, supplier_code, supplier_name,
                 trade_value_usd, trade_quantity)
            SELECT p.id, '699', 2024, '356', 'Iran', 12000000, 5000
            FROM products p WHERE p.name = 'Saffron'
        """))
        db.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestProductsList:
    def test_returns_list(self, client):
        r = client.get("/api/products")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_product_schema(self, client, seeded_db):
        r = client.get("/api/products")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        item = items[0]
        assert "id" in item
        assert "name" in item
        assert "category" in item
        assert "hs_codes" in item
        assert "has_data" in item

    def test_top_market_ignores_null_export_values(self, client, seeded_db):
        r = client.get("/api/products")
        assert r.status_code == 200
        saffron = next(item for item in r.json() if item["name"] == "Saffron")
        assert saffron["top_market_name"] == "India"


class TestProductDetail:
    def test_unknown_hs_code_returns_404(self, client):
        r = client.get("/api/products/999999")
        assert r.status_code == 404

    def test_known_hs_code_returns_detail(self, client, seeded_db):
        r = client.get("/api/products/091020")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Saffron"
        assert "markets" in body
        assert isinstance(body["markets"], list)

    def test_market_indicator_schema(self, client, seeded_db):
        r = client.get("/api/products/091020")
        assert r.status_code == 200
        markets = r.json()["markets"]
        if markets:
            m = markets[0]
            assert "market_code" in m
            assert "growth" in m
            assert "price" in m
            assert "yoy_growth_pct" in m["growth"]
            assert "cagr_pct" in m["growth"]
            assert "unit_price_usd" in m["price"]
            assert "price_basis" in m["price"]


class TestMarketDetail:
    def test_unknown_returns_404(self, client):
        r = client.get("/api/products/091020/markets/ZZZZ")
        assert r.status_code in (200, 404)

    def test_known_market_returns_detail(self, client, seeded_db):
        r = client.get("/api/products/091020/markets/699")
        assert r.status_code == 200
        body = r.json()
        assert "market_code" in body
        assert "competitors" in body
        assert "trade_history" in body

    def test_market_indicator_includes_afg_last_export_fields(self, client, seeded_db):
        """
        Regression test for the same class of bug the trade_data_year round-trip
        test in etl/tests/test_load.py guards against: a column added to
        models.py/schemas.py but missed in a service layer's SELECT/mapping
        would silently come back as null even when the DB has real data.
        """
        r = client.get("/api/products/091020/markets/699")
        assert r.status_code == 200
        indicator = r.json()["indicator"]
        assert indicator["afg_last_export_year"] == 2024
        assert indicator["afg_last_export_value_usd"] == pytest.approx(1_500_000)


class TestIndicatorDefinitions:
    def test_returns_list(self, client):
        r = client.get("/api/indicators")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestPipelineRuns:
    def test_returns_list(self, client):
        r = client.get("/api/pipeline-runs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestDiscovery:
    def test_unknown_hs_code_returns_404(self, client):
        r = client.get("/api/discover/999999")
        assert r.status_code == 404

    def test_ranked_markets_schema(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        assert r.status_code == 200
        body = r.json()
        assert body["hs_code"] == "091020"
        assert "product_name" in body
        assert "computed_for_year" in body
        assert "total_markets_scored" in body
        assert isinstance(body["markets"], list)

    def test_ranked_markets_are_ordered(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        assert r.status_code == 200
        markets = r.json()["markets"]
        assert len(markets) >= 2
        scores = [m["opportunity_score"] for m in markets if m["opportunity_score"] is not None]
        assert scores == sorted(scores, reverse=True)

    def test_ranked_markets_include_rank(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        markets = r.json()["markets"]
        for i, m in enumerate(markets, start=1):
            assert m["rank"] == i

    def test_ranked_markets_clean_placeholder_country_names(self, client, seeded_db):
        with TestingSession() as db:
            db.execute(text("UPDATE markets SET country_name = 'None' WHERE country_code = '276'"))
            db.commit()

        r = client.get("/api/discover/091020")
        assert r.status_code == 200
        germany = next(m for m in r.json()["markets"] if m["market_code"] == "276")
        assert germany["market_name"] == "Germany"

    def test_market_row_has_score_breakdown(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        assert r.status_code == 200
        markets = r.json()["markets"]
        assert len(markets) > 0
        m = markets[0]
        assert "score_breakdown" in m
        bd = m["score_breakdown"]
        for key in ("market_size", "market_growth", "market_quality",
                    "price_competitiveness", "afg_foothold",
                    "distance", "language", "fta_status", "tariff"):
            assert key in bd

    def test_market_row_has_context(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        markets = r.json()["markets"]
        assert len(markets) > 0
        ctx = markets[0]["context"]
        for key in ("gdp_per_capita_usd", "lpi_score", "lpi_score_year",
                    "regulatory_quality", "regulatory_quality_year",
                    "political_stability", "political_stability_year",
                    "tariff_rate_pct", "tariff_indicator", "tariff_year"):
            assert key in ctx

    def test_market_row_has_tariff(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        markets = r.json()["markets"]
        # Find India (market_code 699) which we seeded with 30% tariff
        india = next((m for m in markets if m["market_code"] == "699"), None)
        assert india is not None
        assert india["tariff_rate_pct"] == 30.0
        assert india["context"]["tariff_indicator"] == "AHS"
        # Seeded with computed_for_year=2024 but tariff_year=2022 -- WITS
        # lag means the rate can be older than the indicator row itself.
        assert india["context"]["tariff_year"] == 2022
        # Same idea for World Bank fields: seeded with lpi_score_year=2022
        # (older, triennial survey) vs. regulatory/political _year=2024.
        assert india["context"]["lpi_score_year"] == 2022
        assert india["context"]["regulatory_quality_year"] == 2024
        assert india["context"]["political_stability_year"] == 2024

    def test_high_tariff_market_gets_low_tariff_score(self, client, seeded_db):
        r = client.get("/api/discover/091020")
        markets = r.json()["markets"]
        india = next(m for m in markets if m["market_code"] == "699")
        germany = next(m for m in markets if m["market_code"] == "276")
        # Germany has 0% tariff (score 100), India has 30% tariff (score 10)
        assert germany["score_breakdown"]["tariff"] > india["score_breakdown"]["tariff"]

    def test_limit_param(self, client, seeded_db):
        r = client.get("/api/discover/091020?limit=1")
        assert r.status_code == 200
        assert len(r.json()["markets"]) <= 1

    def test_min_score_filter(self, client, seeded_db):
        r = client.get("/api/discover/091020?min_score=100")
        assert r.status_code == 200
        markets = r.json()["markets"]
        for m in markets:
            if m["opportunity_score"] is not None:
                assert m["opportunity_score"] >= 100

    def test_market_profile_schema(self, client, seeded_db):
        r = client.get("/api/discover/091020/markets/699")
        assert r.status_code == 200
        body = r.json()
        assert body["hs_code"] == "091020"
        assert body["market_code"] == "699"
        assert "opportunity_score" in body
        assert "score_breakdown" in body
        assert "context" in body
        assert "trade" in body
        assert "competitors" in body
        assert "next_steps" in body

    def test_market_profile_clean_placeholder_supplier_names(self, client, seeded_db):
        with TestingSession() as db:
            db.execute(text("""
                INSERT OR IGNORE INTO competitor_flows
                    (product_id, market_code, year, supplier_code, supplier_name,
                     trade_value_usd, trade_quantity)
                SELECT p.id, '699', 2024, '276', '276', 1000, 10
                FROM products p WHERE p.name = 'Saffron'
            """))
            db.commit()

        r = client.get("/api/discover/091020/markets/699")
        assert r.status_code == 200
        germany = next(c for c in r.json()["competitors"] if c["supplier_code"] == "276")
        assert germany["supplier_name"] == "Germany"

    def test_market_profile_next_steps_non_empty(self, client, seeded_db):
        r = client.get("/api/discover/091020/markets/699")
        assert r.status_code == 200
        steps = r.json()["next_steps"]
        assert len(steps) > 0
        step = steps[0]
        assert "order" in step
        assert "title" in step
        assert "description" in step

    def test_high_tariff_triggers_tariff_next_step(self, client, seeded_db):
        # India has 30% tariff in fixtures — should trigger the high-tariff guidance
        r = client.get("/api/discover/091020/markets/699")
        steps = r.json()["next_steps"]
        titles = [s["title"] for s in steps]
        assert any("tariff" in t.lower() for t in titles)

    def test_market_profile_404_on_unknown(self, client):
        r = client.get("/api/discover/091020/markets/ZZZZ")
        assert r.status_code == 404
