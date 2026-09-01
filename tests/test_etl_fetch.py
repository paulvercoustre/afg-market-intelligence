"""Tests for the WITS / World Bank fetch layer and the market-context remap."""

from unittest.mock import patch

import pytest

from config import NUMERIC_TO_ISO3
from etl import fetch
from etl.run import _build_market_context


@pytest.fixture(autouse=True)
def _isolate_wits_disk_cache(tmp_path, monkeypatch):
    """
    Every test gets a fresh, throwaway on-disk WITS cache. Without this,
    tests would read/write etl/.cache/wits_tariffs.json -- the same file a
    real ETL run uses -- and tests reusing the same (reporter, partner, year)
    key (e.g. "356"/"000"/2022) would leak cached results between each other.
    """
    monkeypatch.setattr(fetch, "_WITS_CACHE_PATH", tmp_path / "wits_tariffs.json")
    monkeypatch.setattr(fetch, "_wits_disk_cache", {})
    monkeypatch.setattr(fetch, "_wits_cache", {})


def _wits_payload(products: dict[str, float], reporter="356", partner="000"):
    """Build a minimal SDMX-JSON TRN response like the live API returns."""
    codes = list(products)
    series = {}
    for i, code in enumerate(codes):
        rate = products[code]
        series[f"0:0:{i}:0:0"] = {
            "attributes": [],
            "annotations": [],
            "observations": {"0": [rate, 0, None, 0, 0]},
        }
    return {
        "dataSets": [{"series": series}],
        "structure": {
            "dimensions": {
                "series": [
                    {"id": "FREQ", "keyPosition": 0, "values": [{"id": "A"}]},
                    {"id": "REPORTER", "keyPosition": 1, "values": [{"id": reporter}]},
                    {"id": "PARTNER", "keyPosition": 2, "values": [{"id": partner}]},
                    {
                        "id": "PRODUCTCODE",
                        "keyPosition": 3,
                        "values": [{"id": c} for c in codes],
                    },
                    {"id": "DATATYPE", "keyPosition": 4, "values": [{"id": "Reported"}]},
                ]
            }
        },
    }


class TestParseWitsTariffs:
    def test_multi_product_response(self):
        payload = _wits_payload({"080620": 105.0, "091020": 30.0, "080211": 10.5})
        assert fetch._parse_wits_tariffs(payload) == {
            "080620": 105.0,
            "091020": 30.0,
            "080211": 10.5,
        }

    def test_single_product_response(self):
        payload = _wits_payload({"080620": 2.4})
        assert fetch._parse_wits_tariffs(payload) == {"080620": 2.4}

    def test_null_observation_skipped(self):
        payload = _wits_payload({"080620": 105.0, "091020": 30.0})
        payload["dataSets"][0]["series"]["0:0:1:0:0"]["observations"] = {"0": [None]}
        assert fetch._parse_wits_tariffs(payload) == {"080620": 105.0}

    def test_empty_and_malformed(self):
        assert fetch._parse_wits_tariffs({}) == {}
        assert fetch._parse_wits_tariffs({"dataSets": [], "structure": {}}) == {}


class TestFetchWitsTariffsHttp:
    """Tests of the WITS HTTP call itself, as opposed to the SDMX-JSON parsing
    or the AHS/MFN fallback logic above. This is the layer where a previous
    20s-timeout regression silently zeroed out all tariff data: every real
    WITS call takes 30-90s+, timed out before completing, and the caller in
    etl/run.py just logs a warning and continues without tariff scores -- so
    the failure mode is invisible unless this layer is tested directly.
    """

    def test_builds_expected_url_and_params(self, monkeypatch):
        captured = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _wits_payload({"080620": 12.5})

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(fetch._WITS_SESSION, "get", fake_get)
        result = fetch._fetch_wits_tariffs("356", "000", 2022)

        assert result == {"080620": 12.5}
        assert captured["url"] == (
            f"{fetch._WITS_BASE}/reporter/356/partner/000"
            "/product/all/year/2022/datatype/reported"
        )
        assert captured["params"] == {"format": "JSON"}

    def test_uses_90_second_timeout(self, monkeypatch):
        # Regression test: a prior version set this to 20s on the mistaken
        # assumption that a successful call returns in under a second. Live
        # WITS calls genuinely take 30-60s+ (confirmed against the real API),
        # so a 20s timeout made every real request fail.
        captured = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _wits_payload({})

        def fake_get(url, params=None, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(fetch._WITS_SESSION, "get", fake_get)
        fetch._fetch_wits_tariffs("356", "000", 2022)
        assert captured["timeout"] == 90

    def test_404_returns_empty_dict_without_raising(self, monkeypatch):
        class FakeResponse:
            status_code = 404

        monkeypatch.setattr(fetch._WITS_SESSION, "get", lambda *a, **k: FakeResponse())
        assert fetch._fetch_wits_tariffs("999", "004", 2022) == {}

    def test_non_json_response_returns_empty_dict(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("not JSON")

        monkeypatch.setattr(fetch._WITS_SESSION, "get", lambda *a, **k: FakeResponse())
        assert fetch._fetch_wits_tariffs("356", "000", 2022) == {}

    def test_retries_five_times_before_giving_up(self):
        # Regression test for the retry budget: a slow/flaky WITS response
        # should get several extra chances before the product's tariff
        # fetch is treated as failed (a genuinely failed fetch is never
        # cached as "confirmed no data" -- see TestCachedWitsTariffs -- so
        # this budget is just about not giving up too early on a transient
        # blip within the current attempt).
        assert fetch._fetch_wits_tariffs.retry.stop.max_attempt_number == 5


class TestWitsConnectionPool:
    def test_pool_sized_for_actual_concurrency(self):
        # Regression test: requests.Session defaults to a 10-connection pool
        # per host. Products run concurrently (etl.run._PRODUCT_MAX_WORKERS)
        # and each spins up its own _TARIFF_MAX_WORKERS threads against this
        # one shared session, so peak concurrent WITS requests can reach
        # _PRODUCT_MAX_WORKERS * _TARIFF_MAX_WORKERS. A pool smaller than that
        # forces the excess requests into a fresh TCP+TLS handshake instead
        # of reusing a connection, adding avoidable latency on top of WITS's
        # already-slow responses (observed as "Connection pool is full,
        # discarding connection" warnings in production logs).
        from etl.run import _PRODUCT_MAX_WORKERS

        max_concurrent_requests = _PRODUCT_MAX_WORKERS * fetch._TARIFF_MAX_WORKERS
        adapter = fetch._WITS_SESSION.get_adapter("https://wits.worldbank.org")
        assert adapter._pool_maxsize >= max_concurrent_requests


class TestCachedWitsTariffs:
    def setup_method(self):
        fetch._wits_cache.clear()

    def teardown_method(self):
        fetch._wits_cache.clear()

    def test_caches_per_reporter_partner_year(self):
        calls = []

        def fake(reporter, partner, year):
            calls.append((reporter, partner, year))
            return {"080620": 5.0}

        with patch.object(fetch, "_fetch_wits_tariffs", side_effect=fake):
            first = fetch._cached_wits_tariffs("356", "000", 2022)
            second = fetch._cached_wits_tariffs("356", "000", 2022)

        assert first == second == {"080620": 5.0}
        assert calls == [("356", "000", 2022)]  # only fetched once, second call hit cache

    def test_failed_fetch_is_not_cached_and_is_retried_next_call(self):
        # A failed fetch (timeout/connection error) is NOT the same as WITS
        # confirming there's no data -- caching it as empty would silently
        # persist a false "no data" for up to 7 days. So a failure must not
        # be written to either cache: the next call for the same key should
        # hit _fetch_wits_tariffs again, not reuse a stale non-answer.
        calls = []

        def fake(reporter, partner, year):
            calls.append(1)
            raise ConnectionError("boom")

        with patch.object(fetch, "_fetch_wits_tariffs", side_effect=fake):
            first = fetch._cached_wits_tariffs("356", "000", 2022)
            second = fetch._cached_wits_tariffs("356", "000", 2022)

        assert first == second == {}
        assert len(calls) == 2  # retried, not served from a poisoned cache

    def test_successful_empty_result_is_still_cached(self):
        # A genuine confirmed-empty result (e.g. a real 404, already turned
        # into {} by _fetch_wits_tariffs without raising) IS a real answer
        # and should still be cached normally -- only fetch *failures* skip
        # the cache.
        calls = []

        def fake(reporter, partner, year):
            calls.append(1)
            return {}

        with patch.object(fetch, "_fetch_wits_tariffs", side_effect=fake):
            first = fetch._cached_wits_tariffs("356", "000", 2022)
            second = fetch._cached_wits_tariffs("356", "000", 2022)

        assert first == second == {}
        assert len(calls) == 1  # not retried -- this was a real answer


class TestFetchTariffRates:
    def setup_method(self):
        fetch._wits_cache.clear()

    def teardown_method(self):
        fetch._wits_cache.clear()

    def test_prefers_afg_specific_rates(self):
        def fake(reporter, partner, year, refresh=False):
            if partner == fetch._WITS_AFG_PARTNER:
                return {"080620": 5.0}
            return {"080620": 20.0}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            rows = fetch.fetch_tariff_rates(["699"], ["080620"], [2023, 2024])

        assert rows == [{
            "market_code": "699",
            "hs_code": "080620",
            "tariff_rate_pct": 5.0,
            "indicator": "AHS",
            "year": 2024,
        }]

    def test_falls_back_to_mfn(self):
        def fake(reporter, partner, year, refresh=False):
            if partner == fetch._WITS_WORLD_PARTNER:
                return {"080620": 20.0}
            return {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            rows = fetch.fetch_tariff_rates(["699"], ["080620"], [2024])

        assert rows[0]["indicator"] == "MFN"
        assert rows[0]["tariff_rate_pct"] == 20.0
        assert rows[0]["year"] == 2024

    def test_tries_years_descending(self):
        calls = []

        def fake(reporter, partner, year, refresh=False):
            calls.append(year)
            return {"080620": 10.0} if year == 2022 else {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            rows = fetch.fetch_tariff_rates(["699"], ["080620"], [2022, 2023, 2024])

        assert rows and rows[0]["tariff_rate_pct"] == 10.0
        assert calls[0] == 2024  # newest year first
        # 'year' must reflect where the rate actually came from (2022), not
        # the newest year requested (2024) -- this is what lets a caller tell
        # a stale/lagged WITS rate apart from a fresh one.
        assert rows[0]["year"] == 2022

    def test_comtrade_specific_codes_remapped_for_wits(self):
        seen_reporters = []

        def fake(reporter, partner, year, refresh=False):
            seen_reporters.append(reporter)
            return {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            fetch.fetch_tariff_rates(["699", "842", "56"], ["080620"], [2024])

        # India 699→356, USA 842→840, Belgium 56 zero-padded
        assert set(seen_reporters) == {"356", "840", "056"}


class TestComtradeToWitsCodeMapping:
    """
    Regression test for _COMTRADE_TO_WITS_NUMERIC. These 5 entries were
    verified empirically against the live WITS API (2026-07-31): every one
    of the ~103 markets our pipeline actually queries was cross-checked
    against WITS's own reporter list, and these are the only cases where
    Comtrade's numeric reporter code and WITS's numeric reporter code
    genuinely disagree. If this dict grows, shrinks, or changes value
    without a matching live re-verification, tariff lookups will silently
    query the wrong country (or a nonexistent one) for that market.
    """

    def test_known_exceptions_are_exactly_these_five(self):
        assert fetch._COMTRADE_TO_WITS_NUMERIC == {
            "699": "356",  # India
            "842": "840",  # United States
            "757": "756",  # Switzerland
            "251": "250",  # France
            "579": "578",  # Norway
        }

    def test_markets_confirmed_not_to_need_remapping(self):
        # These markets were specifically flagged as *possible* exceptions
        # during the live cross-check (via a stale WITS metadata catalog
        # that doesn't list EU members as standalone reporters) and then
        # confirmed to need no remapping -- Comtrade and WITS already agree
        # on their numeric code. Guards against someone "fixing" one of
        # these into the exceptions dict based on that same stale signal.
        confirmed_no_remap_needed = [
            "276", "826", "528", "380", "56", "724", "208", "372", "300",
            "642", "368", "442", "688",
        ]
        for code in confirmed_no_remap_needed:
            assert code not in fetch._COMTRADE_TO_WITS_NUMERIC, (
                f"{code} was confirmed not to need remapping -- if WITS "
                "behaviour changed, this needs re-verifying live, not just editing"
            )


class TestWorldBankIndicators:
    def test_wgi_codes_are_current(self):
        # The pre-2024 codes RQ.EST / PV.EST were archived by the World Bank
        # and silently return no data. Both fields deliberately use the .SC
        # (0-100 "score") variant, not .EST (-2.5..2.5 "estimate") -- see the
        # comment above _WB_INDICATORS in etl/fetch.py.
        assert fetch._WB_INDICATORS["regulatory_quality"] == "GOV_WGI_RQ.SC"
        assert fetch._WB_INDICATORS["political_stability"] == "GOV_WGI_PV.SC"

    def test_api_error_payload_raises(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"message": [{"id": "175", "value": "The indicator was not found."}]}]

        with patch.object(fetch._WB_SESSION, "get", return_value=FakeResponse()):
            with pytest.raises(ValueError, match="World Bank API error"):
                fetch._fetch_wb_indicator_chunk.__wrapped__(["IND"], "RQ.EST", [2021, 2024])

    def test_uses_60_second_timeout(self, monkeypatch):
        # Regression test: a 30s timeout was observed to fail on the live API
        # for a 20-country x 5-year chunk (see etl/fetch.py comment) -- it
        # left ~40 major economies, including China/India/Germany, with NULL
        # gdp_per_capita_usd for every requested year. 60s fixes it.
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"page": 1}, []]

        def fake_get(url, params=None, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(fetch._WB_SESSION, "get", fake_get)
        fetch._fetch_wb_indicator_chunk.__wrapped__(["IND"], "NY.GDP.PCAP.CD", [2021, 2025])
        assert captured["timeout"] == 60


class TestBuildMarketContext:
    def test_remaps_iso3_to_comtrade_numeric(self):
        wb_rows = [{
            "country_code": "IND",
            "year": 2023,
            "gdp_usd": 3.5e12,
            "gdp_per_capita_usd": 2500.0,
            "lpi_score": 3.4,
            "regulatory_quality": -0.1,
            "political_stability": -0.6,
        }]
        ctx = _build_market_context(wb_rows)
        # India must be keyed by its Comtrade code 699, not ISO3
        assert "IND" not in ctx
        assert ctx["699"][2023]["gdp_per_capita_usd"] == 2500.0

    def test_decimal_values_coerced_to_float(self):
        from decimal import Decimal

        wb_rows = [{
            "country_code": "PAK",
            "year": 2022,
            "gdp_usd": Decimal("1000.5"),
            "gdp_per_capita_usd": Decimal("1500.25"),
            "lpi_score": None,
            "regulatory_quality": None,
            "political_stability": None,
        }]
        ctx = _build_market_context(wb_rows)
        value = ctx["586"][2022]["gdp_per_capita_usd"]
        assert isinstance(value, float) and value == 1500.25

    def test_mapping_uses_comtrade_codes(self):
        mapping = NUMERIC_TO_ISO3
        # Comtrade-specific codes must be present…
        assert mapping["699"] == "IND"
        assert mapping["842"] == "USA"
        assert mapping["757"] == "CHE"
        assert mapping["251"] == "FRA"
        assert mapping["579"] == "NOR"
        # …and the ISO-numeric variants (which never appear in Comtrade data) must not.
        for wrong in ("356", "840", "756", "250", "578"):
            assert wrong not in mapping

    def test_no_key_is_zero_padded(self):
        # Regression test: real Comtrade reporter codes (and therefore
        # indicators.market_code) never carry a leading zero, even for
        # naturally short codes like Algeria (12) or Austria (40). A prior
        # version stored several of these zero-padded ("012", "040", "048"...),
        # which made them silently unlookupable: present in the dict, but
        # under a key that never matches a real market_code, so those
        # countries got no World Bank data despite this function claiming
        # to cover them.
        mapping = NUMERIC_TO_ISO3
        for key in mapping:
            assert key == str(int(key)), f"{key!r} is zero-padded and will never match a real market_code"

    def test_entries_verified_against_live_world_bank_country_list(self):
        # These values are not hand-typed guesses -- every one of the ~103
        # markets the pipeline actually scores (as of 2026-07-31) was cross-
        # checked by name against the live api.worldbank.org/v2/country
        # list (the exact API this mapping feeds into), with zero diffs.
        # Picking a representative sample here rather than the full set:
        # the previously zero-padded entries, a chunk of the 39 markets that
        # had no entry at all before, and one case (Romania) where a *different*
        # reference (WITS's own country-code page, which uses "ROM") would
        # have been wrong -- the World Bank's own API confirms "ROU" is correct.
        mapping = NUMERIC_TO_ISO3
        verified = {
            # previously zero-padded, now fixed
            "48": "BHR", "40": "AUT", "76": "BRA", "32": "ARG", "36": "AUS",
            "12": "DZA", "31": "AZE", "51": "ARM",
            # previously absent entirely
            "376": "ISR", "620": "PRT", "858": "URY", "442": "LUX",
            "807": "MKD", "688": "SRB", "96": "BRN", "191": "HRV",
            "275": "PSE", "344": "HKG",
            # confirmed correct despite a conflicting third-party reference
            "642": "ROU",
        }
        for code, iso3 in verified.items():
            assert mapping.get(code) == iso3
