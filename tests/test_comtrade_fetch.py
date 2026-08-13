"""
Tests for the UN Comtrade fetch layer (etl/fetch.py).

Mirrors the rigor already applied to the WITS/World Bank fetch tests in
tests/test_etl_fetch.py: this is the one external source that previously had
no coverage at all. These tests intercept comtradeapicall.getFinalData (the
one call Comtrade responses flow through) so a change in Comtrade's response
shape -- a renamed column, a different fallback field being needed -- shows
up as a failing test instead of silently empty/wrong data reaching Postgres.
"""

import pandas as pd
import pytest

from etl import fetch


def _raw_mirror_row(**overrides) -> dict:
    """One row shaped like a real Comtrade mirror-export API response."""
    row = {
        "refYear": 2024,
        "reporterCode": "699",
        "reporterDesc": "India",
        "partnerCode": "4",
        "partnerDesc": "Afghanistan",
        "primaryValue": 100_000.0,
        "qty": 10_000.0,
        "qtyUnitAbbr": "kg",
        "netWgt": 10_000.0,
    }
    row.update(overrides)
    return row


class TestNormaliseMirror:
    def test_maps_expected_columns(self):
        df = pd.DataFrame([_raw_mirror_row()])
        out = fetch._normalise_mirror(df, "091020")
        row = out.iloc[0]
        assert row["year"] == 2024
        assert row["importer_code"] == "699"
        assert row["importer_name"] == "India"
        assert row["trade_value_usd"] == pytest.approx(100_000.0)
        assert row["trade_quantity"] == pytest.approx(10_000.0)
        assert row["net_weight_kg"] == pytest.approx(10_000.0)
        assert row["hs_code"] == "091020"

    def test_falls_back_to_period_when_ref_year_absent(self):
        df = pd.DataFrame([_raw_mirror_row(refYear=None, period=2023)]).drop(columns=["refYear"])
        out = fetch._normalise_mirror(df, "091020")
        assert out.iloc[0]["year"] == 2023

    def test_falls_back_to_cifvalue_when_primary_value_absent(self):
        df = pd.DataFrame([_raw_mirror_row()]).drop(columns=["primaryValue"])
        df["cifvalue"] = 55_000.0
        out = fetch._normalise_mirror(df, "091020")
        assert out.iloc[0]["trade_value_usd"] == pytest.approx(55_000.0)

    def test_falls_back_to_reporter_iso_when_reporter_code_absent(self):
        df = pd.DataFrame([_raw_mirror_row()]).drop(columns=["reporterCode"])
        df["reporterISO"] = "IND"
        out = fetch._normalise_mirror(df, "091020")
        assert out.iloc[0]["importer_code"] == "IND"

    def test_no_reporter_column_drops_all_rows(self):
        # Regression guard: if Comtrade ever ships a response with neither
        # reporterCode nor reporterISO, every row is unusable (no importer to
        # attribute the trade to) -- the function should drop them rather
        # than write NULL importer_code rows to trade_flows.
        df = pd.DataFrame([_raw_mirror_row()]).drop(columns=["reporterCode"])
        out = fetch._normalise_mirror(df, "091020")
        assert out.empty

    def test_quantity_and_weight_are_optional(self):
        df = pd.DataFrame([_raw_mirror_row()]).drop(columns=["qty", "qtyUnitAbbr", "netWgt"])
        out = fetch._normalise_mirror(df, "091020")
        row = out.iloc[0]
        assert row["trade_quantity"] is None
        assert row["net_weight_kg"] is None
        # trade_value_usd is still required -- the row itself isn't dropped
        assert row["trade_value_usd"] == pytest.approx(100_000.0)

    def test_drops_rows_missing_trade_value(self):
        good = _raw_mirror_row()
        bad = _raw_mirror_row(reporterCode="586")
        df = pd.DataFrame([good, bad])
        df.loc[1, "primaryValue"] = None
        out = fetch._normalise_mirror(df, "091020")
        assert len(out) == 1
        assert out.iloc[0]["importer_code"] == "699"

    def test_hs_code_stamped_on_every_row(self):
        df = pd.DataFrame([_raw_mirror_row(), _raw_mirror_row(reporterCode="586")])
        out = fetch._normalise_mirror(df, "080620")
        assert (out["hs_code"] == "080620").all()


class TestCallComtrade:
    """
    Tests of _call_comtrade itself -- the one chokepoint every Comtrade
    request goes through -- as opposed to the higher-level fetch_* wrappers.
    """

    def test_pins_dimension_totals(self, monkeypatch):
        # Regression test for the double-counting bug described in
        # _call_comtrade's docstring: partner2Code, customsCode and motCode
        # must always be pinned to their TOTAL sentinel, regardless of what
        # reporter/partner/flow is being queried, or downstream aggregation
        # silently double-counts (aggregate row + its own breakdown rows).
        captured = {}

        def fake_get_final_data(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame()

        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", fake_get_final_data)

        fetch._call_comtrade(period="2024", hs_code="091020", flow_code="M",
                              reporter_code=None, partner_code="4")

        assert captured["partner2Code"] == "0"
        assert captured["customsCode"] == "C00"
        assert captured["motCode"] == "0"

    def test_none_response_returns_empty_dataframe(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: None)
        result = fetch._call_comtrade("2024", "091020", "M", None, "4")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_list_response_is_wrapped_in_dataframe(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            fetch.comtradeapicall, "getFinalData",
            lambda **kw: [_raw_mirror_row()],
        )
        result = fetch._call_comtrade("2024", "091020", "M", None, "4")
        assert len(result) == 1
        assert result.iloc[0]["reporterCode"] == "699"

    def test_empty_list_response_returns_empty_dataframe(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: [])
        result = fetch._call_comtrade("2024", "091020", "M", None, "4")
        assert result.empty


class TestFetchMirrorExports:
    def test_builds_expected_request(self, monkeypatch):
        captured = {}

        def fake_get_final_data(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame()

        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", fake_get_final_data)

        fetch.fetch_mirror_exports("0910.20", [2023, 2024])

        assert captured["cmdCode"] == "091020"  # dots stripped
        assert captured["period"] == "2023,2024"
        assert captured["flowCode"] == "M"
        assert captured["reporterCode"] is None  # all importers
        assert captured["partnerCode"] == fetch.AFGHANISTAN_NUMERIC

    def test_empty_response_returns_empty_dataframe(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: None)
        result = fetch.fetch_mirror_exports("091020", [2024])
        assert result.empty

    def test_normalizes_real_response(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            fetch.comtradeapicall, "getFinalData",
            lambda **kw: pd.DataFrame([_raw_mirror_row(), _raw_mirror_row(
                reporterCode="586", reporterDesc="Pakistan", primaryValue=50_000.0,
            )]),
        )
        result = fetch.fetch_mirror_exports("091020", [2024])
        assert set(result["importer_code"]) == {"699", "586"}
        assert result["trade_value_usd"].sum() == pytest.approx(150_000.0)

    def test_retries_twice_before_giving_up(self):
        assert fetch.fetch_mirror_exports.retry.stop.max_attempt_number == 2


class TestFetchGlobalImports:
    def test_queries_all_reporters_and_partners(self, monkeypatch):
        captured = {}

        def fake_get_final_data(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame()

        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", fake_get_final_data)

        fetch.fetch_global_imports("091020", [2024])

        assert captured["reporterCode"] is None
        assert captured["partnerCode"] is None  # includes World ('0') + all suppliers

    def test_filters_to_requested_years(self, monkeypatch):
        rows = [
            {"refYear": 2024, "reporterCode": "699", "partnerCode": "0", "primaryValue": 1_000},
            {"refYear": 2020, "reporterCode": "699", "partnerCode": "0", "primaryValue": 999},
        ]
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            fetch.comtradeapicall, "getFinalData", lambda **kw: pd.DataFrame(rows)
        )
        result = fetch.fetch_global_imports("091020", [2023, 2024])
        assert list(result["year"]) == [2024]

    def test_falls_back_to_period_when_ref_year_absent(self, monkeypatch):
        rows = [{"period": 2024, "reporterCode": "699", "partnerCode": "0", "primaryValue": 1_000}]
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            fetch.comtradeapicall, "getFinalData", lambda **kw: pd.DataFrame(rows)
        )
        result = fetch.fetch_global_imports("091020", [2024])
        assert list(result["year"]) == [2024]

    def test_reporter_and_partner_codes_cast_to_string(self, monkeypatch):
        # Comtrade can return these as numeric dtype; downstream code
        # (transform.py, load.py) always treats country codes as strings.
        rows = [{"refYear": 2024, "reporterCode": 699, "partnerCode": 0, "primaryValue": 1_000}]
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            fetch.comtradeapicall, "getFinalData", lambda **kw: pd.DataFrame(rows)
        )
        result = fetch.fetch_global_imports("091020", [2024])
        assert result.iloc[0]["reporterCode"] == "699"
        assert result.iloc[0]["partnerCode"] == "0"

    def test_empty_response_returns_empty_dataframe(self, monkeypatch):
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: None)
        result = fetch.fetch_global_imports("091020", [2024])
        assert result.empty

    def test_retries_twice_before_giving_up(self):
        assert fetch.fetch_global_imports.retry.stop.max_attempt_number == 2
