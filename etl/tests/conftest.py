"""Shared pandas fixtures for ETL transform tests, plus real-Postgres fixtures
used by any test that needs to exercise etl/load.py's actual upsert SQL
(etl/tests/test_load.py, etl/tests/test_pipeline_integration.py)."""

import os
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

PRODUCT_ID = 1
YEARS = [2022, 2023, 2024]
MARKET_CODES = ["699", "586", "842"]


@pytest.fixture
def mirror_df() -> pd.DataFrame:
    """Afghanistan mirror exports to three markets over three years."""
    rows = []
    values = {
        "699": [100_000, 150_000, 200_000],
        "586": [50_000, 60_000, 70_000],
        "842": [10_000, 12_000, 15_000],
    }
    quantities = {
        "699": [10_000, 15_000, 20_000],
        "586": [5_000, 6_000, 7_000],
        "842": [1_000, 1_200, 1_500],
    }
    for market in MARKET_CODES:
        for i, year in enumerate(YEARS):
            rows.append({
                "hs_code": "080211",
                "year": year,
                "importer_code": market,
                "importer_name": f"Market {market}",
                "trade_value_usd": values[market][i],
                "trade_quantity": quantities[market][i],
                "quantity_unit": "kg",
                "net_weight_kg": quantities[market][i],
            })
    return pd.DataFrame(rows)


@pytest.fixture
def global_df() -> pd.DataFrame:
    """Global import data: world totals and supplier rows for test markets."""
    rows = []

    world_totals = {"699": 10_000_000, "586": 5_000_000, "842": 50_000_000}
    for market, total in world_totals.items():
        for year in YEARS:
            rows.append({
                "reporterCode": market,
                "partnerCode": "0",
                "year": year,
                "primaryValue": total,
                "partnerDesc": "World",
                "qty": None,
            })

    # Suppliers to market 699 in 2024: Afghanistan (004), China (156), Turkey (792)
    suppliers_699 = [
        ("004", "Afghanistan", 200_000, 20_000),
        ("156", "China", 5_000_000, 500_000),
        ("792", "Turkey", 1_000_000, 100_000),
    ]
    for partner_code, partner_name, value, qty in suppliers_699:
        rows.append({
            "reporterCode": "699",
            "partnerCode": partner_code,
            "year": 2024,
            "primaryValue": value,
            "partnerDesc": partner_name,
            "qty": qty,
            "netWgt": qty,  # _price_competitiveness() now uses netWgt only
        })

    # Suppliers to market 586 in 2024
    suppliers_586 = [
        ("004", "Afghanistan", 70_000, 7_000),
        ("156", "China", 2_000_000, 200_000),
    ]
    for partner_code, partner_name, value, qty in suppliers_586:
        rows.append({
            "reporterCode": "586",
            "partnerCode": partner_code,
            "year": 2024,
            "primaryValue": value,
            "partnerDesc": partner_name,
            "qty": qty,
            "netWgt": qty,
        })

    # Suppliers to market 842 in 2024 — Afghanistan priced below market average
    suppliers_842 = [
        ("004", "Afghanistan", 15_000, 1_500),   # $10/unit
        ("156", "China", 30_000_000, 2_000_000),  # $15/unit
        ("792", "Turkey", 10_000_000, 500_000),   # $20/unit
    ]
    for partner_code, partner_name, value, qty in suppliers_842:
        rows.append({
            "reporterCode": "842",
            "partnerCode": partner_code,
            "year": 2024,
            "primaryValue": value,
            "partnerDesc": partner_name,
            "qty": qty,
            "netWgt": qty,
        })

    return pd.DataFrame(rows)


@pytest.fixture
def sample_indicator_row() -> dict:
    """Minimal indicator row for scoring tests."""
    return {
        "product_id": PRODUCT_ID,
        "market_code": "699",
        "computed_for_year": 2024,
        "global_market_size_usd": 10_000_000.0,
        "afg_export_value_usd": 200_000.0,
        "cagr_pct": 10.0,
        "price_competitiveness": "Competitive",
        "afg_supplier_rank": 3,
    }


# ── Real-Postgres fixtures ──────────────────────────────────────────────────
# Any test that requests pg_engine (directly, or transitively via clean_tables
# / product_id) is auto-skipped unless TEST_DATABASE_URL is set -- see
# etl/tests/test_load.py's module docstring for how to run these locally.

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_engine():
    """Real Postgres engine, migrated to head once per test session."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set -- see etl/tests/test_load.py to run locally")

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    # migrations/env.py prefers the DATABASE_URL env var over sqlalchemy.url
    # when it's set -- scope the override to just this call so it can't leak
    # into anything else that reads DATABASE_URL during the test session.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", TEST_DATABASE_URL)
        command.upgrade(cfg, "head")

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(request):
    """
    Start every test with empty tables, regardless of what a previous run
    left behind. Only truncates for tests that actually use pg_engine --
    autouse here means "always run for tests in this directory that request
    it," not "always touch Postgres" (fixturenames check below skips the
    truncate, and therefore the pg_engine skip-if-unconfigured, for every
    other test).
    """
    if "pg_engine" not in request.fixturenames:
        yield
        return
    pg_engine = request.getfixturevalue("pg_engine")
    with pg_engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE products, markets, market_context, trade_flows, "
            "competitor_flows, indicators, pipeline_runs RESTART IDENTITY CASCADE"
        ))
    yield


@pytest.fixture
def product_id(pg_engine) -> int:
    from etl import load
    return load.upsert_product(pg_engine, "Test Saffron", "Spices & Herbs", ["091020"], "test product")
