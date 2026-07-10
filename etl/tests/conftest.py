"""Shared pandas fixtures for ETL transform tests."""

import pandas as pd
import pytest

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
