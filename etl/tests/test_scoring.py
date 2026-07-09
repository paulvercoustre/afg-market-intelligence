"""Unit tests for opportunity scoring in etl/transform.py."""

import math

import pytest

from config import OPPORTUNITY_SCORE_WEIGHTS, TARIFF_SCORE_PER_PCT
from etl.transform import (
    _score_distance,
    _score_foothold,
    _score_growth,
    _score_market_quality,
    _score_market_size,
    _score_price,
    _score_tariff,
    enrich_indicators_with_scores,
)


class TestDimensionScores:
    def test_market_size_boundaries(self):
        assert _score_market_size(None, 1.0) == 0.0
        assert _score_market_size(0, 1.0) == 0.0
        log_max = math.log1p(1_000_000)
        assert _score_market_size(1_000_000, log_max) == pytest.approx(100.0)

    def test_growth_boundaries(self):
        assert _score_growth(None) == 50.0
        assert _score_growth(0) == pytest.approx(50.0)
        assert _score_growth(20) == pytest.approx(100.0)
        assert _score_growth(-20) == pytest.approx(0.0)

    def test_market_quality_with_full_context(self):
        ctx = {"lpi_score": 3.0, "regulatory_quality": 0.0, "political_stability": 0.0}
        # LPI 3 → 50, WGI 0 → 50 each; average = 50
        assert _score_market_quality(ctx) == pytest.approx(50.0)

    def test_market_quality_neutral_when_empty(self):
        assert _score_market_quality({}) == 50.0

    def test_price_competitiveness_mapping(self):
        assert _score_price("Highly Competitive") == 100.0
        assert _score_price("Competitive") == 75.0
        assert _score_price("Average") == 50.0
        assert _score_price("Above Market") == 25.0
        assert _score_price(None) == 50.0

    def test_foothold_log_scale(self):
        assert _score_foothold(None) == 25.0
        assert _score_foothold(0) == 25.0
        assert _score_foothold(1_000_000) == pytest.approx(84.0, rel=0.01)

    def test_distance_boundaries(self):
        assert _score_distance(None) == 50.0
        assert _score_distance(0) == pytest.approx(100.0)
        assert _score_distance(15_000) == pytest.approx(0.0)

    def test_tariff_boundaries(self):
        assert _score_tariff(None) == 50.0
        assert _score_tariff(0) == pytest.approx(100.0)
        assert _score_tariff(33.33) == pytest.approx(0.0, abs=0.1)
        assert _score_tariff(10) == pytest.approx(100.0 - 10 * TARIFF_SCORE_PER_PCT)


class TestEnrichIndicatorsWithScores:
    def test_adds_all_score_fields(self, sample_indicator_row):
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={"356": {2024: {"lpi_score": 3.5, "regulatory_quality": 0.5}}},
            all_market_sizes={"356": 10_000_000},
            tariffs={"356": {"rate": 5.0, "indicator": "MFN"}},
        )
        row = rows[0]
        score_keys = [
            "score_market_size", "score_market_growth", "score_market_quality",
            "score_price_competitiveness", "score_afg_foothold", "score_distance",
            "score_language", "score_fta", "score_tariff", "opportunity_score",
        ]
        for key in score_keys:
            assert key in row
            assert 0 <= row[key] <= 100

    def test_composite_equals_weighted_sum(self, sample_indicator_row):
        row = sample_indicator_row.copy()
        rows = enrich_indicators_with_scores(
            [row],
            market_context={},
            all_market_sizes={"356": 10_000_000},
            tariffs={},
        )
        enriched = rows[0]
        weights = OPPORTUNITY_SCORE_WEIGHTS
        expected = (
            enriched["score_market_size"] * weights["market_size"]
            + enriched["score_market_growth"] * weights["market_growth"]
            + enriched["score_market_quality"] * weights["market_quality"]
            + enriched["score_price_competitiveness"] * weights["price_competitiveness"]
            + enriched["score_tariff"] * weights["tariff"]
            + enriched["score_afg_foothold"] * weights["afg_foothold"]
            + enriched["score_distance"] * weights["distance"]
            + enriched["score_language"] * weights["language"]
            + enriched["score_fta"] * weights["fta_status"]
        )
        assert enriched["opportunity_score"] == pytest.approx(round(expected, 2))

    def test_neutral_defaults_without_wb_and_tariff(self, sample_indicator_row):
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"356": 10_000_000},
        )
        row = rows[0]
        assert row["score_market_quality"] == pytest.approx(50.0)
        assert row["score_tariff"] == pytest.approx(50.0)
        assert row["gdp_per_capita_usd"] is None
        assert row["tariff_rate_pct"] is None

    def test_fta_bonus_applied(self, sample_indicator_row):
        # India (356) has partial FTA in config
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"356": 10_000_000},
        )
        assert rows[0]["has_fta"] is True
        assert rows[0]["score_fta"] == pytest.approx(100.0)

    def test_empty_input_passthrough(self):
        assert enrich_indicators_with_scores([], {}, {}) == []
