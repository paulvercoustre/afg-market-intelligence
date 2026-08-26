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


@pytest.fixture(autouse=True)
def _reset_qty_unit_cache():
    """
    _load_qty_unit_labels() caches its result in a module-level global for
    the lifetime of the process (see etl/fetch.py) -- reset it around every
    test so one test's mocked/failed getReference() call can't leak into
    the next.
    """
    fetch._qty_unit_labels = None
    yield
    fetch._qty_unit_labels = None


def _qtyunit_reference_df() -> pd.DataFrame:
    """A trimmed stand-in for comtradeapicall.getReference('qtyunit')."""
    return pd.DataFrame([
        {"qtyCode": -1, "qtyAbbr": "N/A", "qtyDescription": "Not available or not specified or no quantity."},
        {"qtyCode": 2, "qtyAbbr": "m²", "qtyDescription": "Area in square meters"},
        {"qtyCode": 8, "qtyAbbr": "kg", "qtyDescription": "Weight in kilograms"},
    ])


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
        # qtyUnitAbbr is already a clean, non-blank string here -- resolved
        # directly, no reference-table lookup needed (see TestResolveQuantityUnits
        # for the far more common case where it comes back blank from Comtrade).
        assert row["quantity_unit"] == "kg"

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

    def test_quantity_unit_resolved_from_code_when_abbr_blank(self, monkeypatch):
        # The real-world case (see etl/fetch.py's _load_qty_unit_labels
        # docstring): Comtrade returns qtyUnitCode but leaves qtyUnitAbbr
        # blank, so the label has to come from a separate reference lookup.
        rows = [{
            "refYear": 2023, "reporterCode": "380", "partnerCode": "4",
            "primaryValue": 100_000, "qtyUnitCode": 2, "qtyUnitAbbr": None,
        }]
        monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
        monkeypatch.setattr(fetch.comtradeapicall, "getFinalData", lambda **kw: pd.DataFrame(rows))
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())

        result = fetch.fetch_global_imports("570210", [2023])
        assert result.iloc[0]["quantity_unit"] == "m²"


class TestResolveQuantityUnits:
    """
    _resolve_quantity_units() / _load_qty_unit_labels() -- the fix for
    Comtrade's trade-flow API returning qtyUnitCode (numeric) but leaving
    qtyUnitAbbr (text label) blank, confirmed empirically for Woven Carpets
    (570210), Italy importing from Afghanistan, 2023.
    """

    def test_prefers_abbr_when_already_populated(self, monkeypatch):
        # getReference must not even be called -- a populated qtyUnitAbbr
        # is trusted as-is, no reference lookup needed.
        def fail_if_called(*a, **kw):
            raise AssertionError("getReference should not be called when qtyUnitAbbr is populated")
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", fail_if_called)

        df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": "kg"}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] == "kg"

    def test_falls_back_to_code_lookup_when_abbr_blank(self, monkeypatch):
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())
        df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": None}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] == "m²"

    def test_treats_empty_string_abbr_as_blank(self, monkeypatch):
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())
        df = pd.DataFrame([{"qtyUnitCode": 8, "qtyUnitAbbr": "  "}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] == "kg"

    def test_unknown_code_and_no_abbr_resolves_to_none(self, monkeypatch):
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())
        df = pd.DataFrame([{"qtyUnitCode": 999, "qtyUnitAbbr": None}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] is None

    def test_missing_columns_resolve_to_none(self):
        df = pd.DataFrame([{"primaryValue": 100_000}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] is None

    def test_reference_lookup_failure_does_not_raise(self, monkeypatch):
        # A network/parsing failure fetching the reference table shouldn't
        # take down the whole fetch -- resolve to None instead, same as an
        # unrecognised code.
        def raise_error(*a, **kw):
            raise ConnectionError("boom")
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", raise_error)

        df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": None}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] is None

    def test_reference_table_fetched_only_once(self, monkeypatch):
        calls = []
        def counting_get_reference(*a, **kw):
            calls.append(1)
            return _qtyunit_reference_df()
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", counting_get_reference)

        df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": None},
                            {"qtyUnitCode": 8, "qtyUnitAbbr": None}])
        fetch._resolve_quantity_units(df)
        fetch._resolve_quantity_units(df)
        assert len(calls) == 1

    def test_excludes_not_available_sentinel(self, monkeypatch):
        # qtyCode -1 ("N/A") is a real row in Comtrade's reference table, not
        # a usable label -- it should resolve to None like any other blank.
        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())
        df = pd.DataFrame([{"qtyUnitCode": -1, "qtyUnitAbbr": None}])
        result = fetch._resolve_quantity_units(df)
        assert result.iloc[0] is None

    def test_failed_fetch_is_not_cached_permanently(self, monkeypatch):
        # A transient failure (e.g. a rate limit -- confirmed to happen in
        # practice during a real multi-product ETL run) must not get
        # remembered as "the labels are {}" for the rest of the process.
        # The next call should get a fresh chance to fetch successfully,
        # not be permanently stuck resolving every code to None.
        monkeypatch.setattr(
            fetch.comtradeapicall, "getReference",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("boom")),
        )
        df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": None}])
        first = fetch._resolve_quantity_units(df)
        assert first.iloc[0] is None

        monkeypatch.setattr(fetch.comtradeapicall, "getReference", lambda *a, **kw: _qtyunit_reference_df())
        second = fetch._resolve_quantity_units(df)
        assert second.iloc[0] == "m²"

    def test_concurrent_first_calls_do_not_duplicate_fetch(self, monkeypatch):
        # Regression test for a real bug: etl/run.py fetches products
        # concurrently (_PRODUCT_MAX_WORKERS in etl/run.py), so several
        # threads can all see _qty_unit_labels is still None at once and
        # race into _load_qty_unit_labels() together. Without the lock, an
        # unsynchronised write from one racing thread (e.g. one that hit a
        # rate limit and cached {}) could silently clobber another thread's
        # good result for the rest of the process -- this happened for real
        # (Knotted Carpets ended up with quantity_unit=None for every
        # competitor row after a concurrent getReference() call elsewhere
        # in the same run hit a 429). Line several threads up on a barrier
        # so they all hit the None-check at the same instant, and assert
        # getReference() only actually runs once.
        import threading as th

        call_count = {"n": 0}
        count_lock = th.Lock()
        start_barrier = th.Barrier(8)

        def counting_get_reference(*a, **kw):
            with count_lock:
                call_count["n"] += 1
            return _qtyunit_reference_df()

        monkeypatch.setattr(fetch.comtradeapicall, "getReference", counting_get_reference)

        results = []
        results_lock = th.Lock()

        def worker():
            start_barrier.wait()
            df = pd.DataFrame([{"qtyUnitCode": 2, "qtyUnitAbbr": None}])
            value = fetch._resolve_quantity_units(df).iloc[0]
            with results_lock:
                results.append(value)

        threads = [th.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count["n"] == 1
        assert results == ["m²"] * 8
