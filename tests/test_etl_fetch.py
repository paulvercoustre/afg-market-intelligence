"""Tests for the WITS / World Bank fetch layer and the market-context remap."""

from unittest.mock import patch

import pytest

from etl import fetch
from etl.run import _build_market_context, _load_numeric_to_iso3


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


class TestFetchTariffRates:
    def setup_method(self):
        fetch._wits_cache.clear()

    def teardown_method(self):
        fetch._wits_cache.clear()

    def test_prefers_afg_specific_rates(self):
        def fake(reporter, partner, year):
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
        }]

    def test_falls_back_to_mfn(self):
        def fake(reporter, partner, year):
            if partner == fetch._WITS_WORLD_PARTNER:
                return {"080620": 20.0}
            return {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            rows = fetch.fetch_tariff_rates(["699"], ["080620"], [2024])

        assert rows[0]["indicator"] == "MFN"
        assert rows[0]["tariff_rate_pct"] == 20.0

    def test_tries_years_descending(self):
        calls = []

        def fake(reporter, partner, year):
            calls.append(year)
            return {"080620": 10.0} if year == 2022 else {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            rows = fetch.fetch_tariff_rates(["699"], ["080620"], [2022, 2023, 2024])

        assert rows and rows[0]["tariff_rate_pct"] == 10.0
        assert calls[0] == 2024  # newest year first

    def test_comtrade_specific_codes_remapped_for_wits(self):
        seen_reporters = []

        def fake(reporter, partner, year):
            seen_reporters.append(reporter)
            return {}

        with patch.object(fetch, "_cached_wits_tariffs", side_effect=fake):
            fetch.fetch_tariff_rates(["699", "842", "56"], ["080620"], [2024])

        # India 699→356, USA 842→840, Belgium 56 zero-padded
        assert set(seen_reporters) == {"356", "840", "056"}


class TestWorldBankIndicators:
    def test_wgi_codes_are_current(self):
        # The pre-2024 codes RQ.EST / PV.EST were archived by the World Bank
        # and silently return no data.
        assert fetch._WB_INDICATORS["regulatory_quality"] == "GOV_WGI_RQ.EST"
        assert fetch._WB_INDICATORS["political_stability"] == "GOV_WGI_PV.EST"

    def test_api_error_payload_raises(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"message": [{"id": "175", "value": "The indicator was not found."}]}]

        with patch.object(fetch._WB_SESSION, "get", return_value=FakeResponse()):
            with pytest.raises(ValueError, match="World Bank API error"):
                fetch._fetch_wb_indicator.__wrapped__("IND", "RQ.EST", [2021, 2024])


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
        mapping = _load_numeric_to_iso3()
        # Comtrade-specific codes must be present…
        assert mapping["699"] == "IND"
        assert mapping["842"] == "USA"
        assert mapping["757"] == "CHE"
        assert mapping["251"] == "FRA"
        assert mapping["579"] == "NOR"
        # …and the ISO-numeric variants (which never appear in Comtrade data) must not.
        for wrong in ("356", "840", "756", "250", "578"):
            assert wrong not in mapping
