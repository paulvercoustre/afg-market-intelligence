"""Unit tests for backend/country_names.py."""

from backend.country_names import _clean_candidate, resolve_country_name


class TestCleanCandidate:
    def test_none_and_placeholders(self):
        assert _clean_candidate(None) is None
        assert _clean_candidate("none") is None
        assert _clean_candidate("NaN") is None
        assert _clean_candidate("<NA>") is None

    def test_numeric_candidates_rejected(self):
        assert _clean_candidate("356") is None
        assert _clean_candidate(" 004 ") is None

    def test_valid_name_passthrough(self):
        assert _clean_candidate("India") == "India"
        assert _clean_candidate("  Pakistan  ") == "Pakistan"


class TestResolveCountryName:
    def test_prefers_clean_candidate(self):
        assert resolve_country_name("356", "India") == "India"

    def test_maps_numeric_code(self):
        assert resolve_country_name("356", None) == "India"
        assert resolve_country_name(356, None) == "India"
        assert resolve_country_name("004", None) == "Afghanistan"

    def test_handles_leading_zero_variants(self):
        assert resolve_country_name("4", None) == "Afghanistan"
        assert resolve_country_name("004", None) == "Afghanistan"

    def test_unknown_code_falls_back_to_placeholder(self):
        assert resolve_country_name("99999", None) == "Unknown (99999)"

    def test_empty_code_returns_none(self):
        assert resolve_country_name("", None) is None
        assert resolve_country_name(None, None) is None

    def test_ignores_numeric_candidate_falls_back_to_code(self):
        assert resolve_country_name("586", "586") == "Pakistan"
