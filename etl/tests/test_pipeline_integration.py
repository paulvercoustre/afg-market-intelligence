"""
End-to-end integration test: fetch -> transform -> load, composed together
against a real Postgres database.

Every layer already has strong isolated coverage: tests/test_comtrade_fetch.py
for fetch, etl/tests/test_transform.py + test_scoring.py for transform,
etl/tests/test_load.py for load. None of them catch a bug at the *boundary*
between two layers -- e.g. transform.py expecting a column fetch.py stopped
producing, or a dtype fetch.py returns that load.py's SQL chokes on. This
test exists specifically for that class of bug: only the actual HTTP call to
Comtrade (comtradeapicall.getFinalData) is mocked. Everything downstream of
that -- response normalisation, indicator computation, opportunity scoring,
and the real Postgres upsert SQL -- runs for real, unmocked.

Requires TEST_DATABASE_URL, same as etl/tests/test_load.py (see that file's
module docstring for how to run these locally); skips automatically without it.
"""

import pandas as pd
import pytest
from sqlalchemy import text

from etl import fetch, load, transform

_REPORTER_NAMES = {"699": "India", "4": "Afghanistan", "156": "China"}


def _comtrade_row(reporter_code: str, partner_code: str, primary_value: float,
                   year: int, qty: float | None = None) -> dict:
    """One row shaped like a real Comtrade API response."""
    return {
        "refYear": year,
        "reporterCode": reporter_code,
        "reporterDesc": _REPORTER_NAMES.get(reporter_code, reporter_code),
        "partnerCode": partner_code,
        "partnerDesc": "Afghanistan" if partner_code == "4" else "World",
        "primaryValue": primary_value,
        "qty": qty if qty is not None else primary_value / 10,
        "qtyUnitAbbr": "kg",
        "netWgt": qty if qty is not None else primary_value / 10,
    }


class TestFetchTransformLoadPipeline:
    def test_full_pipeline_composes_correctly(self, monkeypatch, pg_engine, product_id):
        years = [2023, 2024]

        # Afghanistan's mirror exports to India, growing year over year.
        mirror_rows = [
            _comtrade_row("699", "4", 100_000, 2023, qty=10_000),
            _comtrade_row("699", "4", 150_000, 2024, qty=15_000),
        ]
        # India's global import picture: world total + two suppliers
        # (Afghanistan and China), 2024 only -- mirrors a realistic response
        # where competitor detail is only meaningful for the latest year.
        global_rows = [
            _comtrade_row("699", "0", 5_000_000, 2024),
            _comtrade_row("699", "4", 150_000, 2024, qty=15_000),
            _comtrade_row("699", "156", 3_000_000, 2024, qty=200_000),
        ]

        def fake_get_final_data(**kwargs):
            if kwargs["partnerCode"] == fetch.AFGHANISTAN_NUMERIC:
                return pd.DataFrame(mirror_rows)
            return pd.DataFrame(global_rows)

        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", fake_get_final_data)

        # ── Fetch (real functions, only the HTTP call is mocked) ──────────
        mirror_df = fetch.fetch_mirror_exports("091020", years)
        global_df = fetch.fetch_global_imports("091020", years)
        assert not mirror_df.empty
        assert not global_df.empty

        # ── Transform (real functions) ─────────────────────────────────────
        ind_rows = transform.compute_indicators(product_id, ["699"], mirror_df, global_df, years)
        assert len(ind_rows) == 1

        ind_rows = transform.enrich_indicators_with_scores(
            ind_rows,
            market_context={"699": {2024: {"lpi_score": 3.4, "regulatory_quality": 0.5}}},
            all_market_sizes={"699": 5_000_000},
            tariffs={"699": {"rate": 8.0, "indicator": "MFN", "year": 2023}},
        )
        row = ind_rows[0]
        assert row["market_code"] == "699"
        assert row["computed_for_year"] == 2024
        assert row["global_market_size_usd"] == pytest.approx(5_000_000.0)
        assert row["afg_export_value_usd"] == pytest.approx(150_000.0)
        # 100k -> 150k year over year
        assert row["yoy_growth_pct"] == pytest.approx(50.0)
        assert 0 <= row["opportunity_score"] <= 100

        # ── Load (real function, real Postgres) ────────────────────────────
        n = load.bulk_upsert_indicators(pg_engine, ind_rows)
        assert n == 1

        with pg_engine.connect() as conn:
            stored = conn.execute(
                text("SELECT * FROM indicators WHERE product_id = :pid"), {"pid": product_id}
            ).mappings().one()

        # What actually landed in Postgres matches what transform computed --
        # this is the one assertion none of the per-layer tests can make.
        assert stored["market_code"] == "699"
        assert float(stored["afg_export_value_usd"]) == pytest.approx(150_000.0)
        assert float(stored["global_market_size_usd"]) == pytest.approx(5_000_000.0)
        assert float(stored["yoy_growth_pct"]) == pytest.approx(50.0)
        assert float(stored["tariff_rate_pct"]) == pytest.approx(8.0)
        assert stored["tariff_year"] == 2023
        assert float(stored["lpi_score"]) == pytest.approx(3.4)
        assert stored["lpi_score_year"] == 2024
        assert stored["opportunity_score"] is not None

    def test_no_mirror_data_produces_no_indicator_rows_not_a_crash(self, monkeypatch, pg_engine, product_id):
        # Comtrade returning nothing for the mirror side (e.g. Afghanistan
        # genuinely has no recorded exports to any market for this HS code)
        # must flow through as "no rows to score", not an exception -- the
        # same real-world case etl/run.py's "no_data" status exists to handle.
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: None)

        years = [2024]
        mirror_df = fetch.fetch_mirror_exports("091020", years)
        global_df = fetch.fetch_global_imports("091020", years)
        assert mirror_df.empty
        assert global_df.empty

        ind_rows = transform.compute_indicators(product_id, ["699"], mirror_df, global_df, years)
        assert ind_rows == []
        assert load.bulk_upsert_indicators(pg_engine, ind_rows) == 0
