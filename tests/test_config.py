"""Config invariant tests — guard against accidental scoring/catalog edits."""

import re

import pytest

from config import (
    DISTANCE_FROM_KABUL_KM,
    FTA_STATUS,
    LANGUAGE_SIMILARITY,
    OPPORTUNITY_SCORE_WEIGHTS,
    PRODUCTS,
)

HS_CODE_PATTERN = re.compile(r"^\d{6}$")
COUNTRY_CODE_PATTERN = re.compile(r"^\d{1,3}$")


class TestOpportunityScoreWeights:
    def test_weights_sum_to_one(self):
        total = sum(OPPORTUNITY_SCORE_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_all_weights_positive(self):
        assert all(w > 0 for w in OPPORTUNITY_SCORE_WEIGHTS.values())


class TestProducts:
    def test_every_product_has_name_and_codes(self):
        for name, product in PRODUCTS.items():
            assert name.strip()
            assert product.get("codes")
            assert product.get("category", "").strip()
            assert product.get("description", "").strip()

    def test_hs_codes_are_six_digits(self):
        for name, product in PRODUCTS.items():
            for code in product["codes"]:
                assert HS_CODE_PATTERN.match(code), f"{name}: invalid HS code {code!r}"


class TestGeographyLookups:
    def test_distance_keys_are_numeric_country_codes(self):
        for code, km in DISTANCE_FROM_KABUL_KM.items():
            assert COUNTRY_CODE_PATTERN.match(code), f"invalid distance key {code!r}"
            assert km > 0

    def test_fta_keys_are_numeric_country_codes(self):
        for code, status in FTA_STATUS.items():
            assert COUNTRY_CODE_PATTERN.match(code), f"invalid FTA key {code!r}"
            assert status in ("full", "partial")

    def test_language_similarity_in_valid_range(self):
        for code, sim in LANGUAGE_SIMILARITY.items():
            assert COUNTRY_CODE_PATTERN.match(code), f"invalid language key {code!r}"
            assert 0.0 <= sim <= 1.0
