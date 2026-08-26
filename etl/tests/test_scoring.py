"""Unit tests for opportunity scoring in etl/transform.py."""

import math

import pytest

from config import MAX_GREAT_CIRCLE_DISTANCE_KM, OPPORTUNITY_SCORE_WEIGHTS, TARIFF_SCORE_PER_PCT
from etl.transform import (
    _latest_wb_context,
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
        assert _score_foothold(None) == 0.0
        assert _score_foothold(0) == 0.0
        assert _score_foothold(1_000_000) == pytest.approx(84.0, rel=0.01)

    def test_foothold_current_year_value_wins_over_last_export(self):
        # Both present -- the active current-year figure is used, not a
        # blend with the historical one.
        assert _score_foothold(1_000_000, 500_000) == pytest.approx(84.0, rel=0.01)

    def test_foothold_falls_back_to_last_export_when_current_year_is_none(self):
        # Genuine current-year absence, but Afghanistan exported $1M as
        # recently as a bounded prior year -- discounted (0.7x) vs. an
        # active current-year presence, but still above the "no Afghan
        # trade at all" baseline (0.0).
        score = _score_foothold(None, 1_000_000)
        assert score == pytest.approx(84.0 * 0.7, rel=0.01)
        assert 0.0 < score < 84.0

    def test_foothold_falls_back_to_last_export_when_current_year_is_zero(self):
        assert _score_foothold(0, 1_000_000) == pytest.approx(84.0 * 0.7, rel=0.01)

    def test_foothold_trivial_last_export_scores_barely_above_zero(self):
        # A $1 historical value is technically "some" history -- it scores
        # a hair above 0, not a meaningfully higher floor.
        score = _score_foothold(None, 1)
        assert 0.0 < score < 5.0

    def test_foothold_no_current_and_no_last_export_is_zero(self):
        assert _score_foothold(None, None) == 0.0
        assert _score_foothold(0, 0) == 0.0

    def test_distance_boundaries(self):
        assert _score_distance(None) == 50.0
        assert _score_distance(0) == pytest.approx(100.0)
        assert _score_distance(MAX_GREAT_CIRCLE_DISTANCE_KM) == pytest.approx(0.0)

    def test_distance_log_scale(self):
        # Equal ratios should cost roughly equal score, not equal km -- a 10x
        # jump from 100km to 1000km should cost about as much score as 1000km
        # to 10000km (also a 10x jump), unlike the old linear formula where
        # only the absolute km gap mattered.
        cost_of_10x_from_100km = _score_distance(100) - _score_distance(1_000)
        cost_of_10x_from_1000km = _score_distance(1_000) - _score_distance(10_000)
        assert cost_of_10x_from_100km == pytest.approx(cost_of_10x_from_1000km, rel=0.05)

        # By contrast, two equal absolute-km gaps (900km) at different points
        # on the scale should cost very different amounts -- the near one
        # (100km -> 1000km, a 10x ratio) should cost far more than the far one
        # (9000km -> 9900km, a 10% ratio).
        cost_of_900km_near = _score_distance(100) - _score_distance(1_000)
        cost_of_900km_far = _score_distance(9_000) - _score_distance(9_900)
        assert cost_of_900km_near > cost_of_900km_far * 5

    def test_tariff_boundaries(self):
        assert _score_tariff(None) == 50.0
        assert _score_tariff(0) == pytest.approx(100.0)
        assert _score_tariff(33.33) == pytest.approx(0.0, abs=0.1)
        assert _score_tariff(10) == pytest.approx(100.0 - 10 * TARIFF_SCORE_PER_PCT)


class TestLatestWbContext:
    def test_merges_latest_non_null_per_field(self):
        # LPI is a triennial survey: latest year has GDP but null LPI
        ctx_by_year = {
            2022: {"gdp_per_capita_usd": 2280.0, "lpi_score": 3.4},
            2024: {"gdp_per_capita_usd": 2592.0, "lpi_score": None},
        }
        ctx = _latest_wb_context(ctx_by_year, 2024)
        assert ctx["gdp_per_capita_usd"] == 2592.0  # newest wins
        assert ctx["lpi_score"] == 3.4              # falls back to 2022

    def test_records_which_year_each_field_came_from(self):
        # Same fixture as above: gdp_per_capita_usd resolves to the newer
        # 2024 row, lpi_score falls back to 2022 -- each field's '_year'
        # entry must reflect its own source year, not a single shared one.
        ctx_by_year = {
            2022: {"gdp_per_capita_usd": 2280.0, "lpi_score": 3.4},
            2024: {"gdp_per_capita_usd": 2592.0, "lpi_score": None},
        }
        ctx = _latest_wb_context(ctx_by_year, 2024)
        assert ctx["gdp_per_capita_usd_year"] == 2024
        assert ctx["lpi_score_year"] == 2022

    def test_ignores_years_after_cutoff(self):
        ctx_by_year = {2023: {"lpi_score": 3.0}, 2025: {"lpi_score": 4.0}}
        ctx = _latest_wb_context(ctx_by_year, 2024)
        assert ctx["lpi_score"] == 3.0
        assert ctx["lpi_score_year"] == 2023

    def test_empty(self):
        assert _latest_wb_context({}, 2024) == {}


class TestEnrichIndicatorsWithScores:
    def test_adds_all_score_fields(self, sample_indicator_row):
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={"699": {2024: {"lpi_score": 3.5, "regulatory_quality": 0.5}}},
            all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 5.0, "indicator": "MFN", "year": 2022}},
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
        # The year the rate was actually reported for (can differ from
        # computed_for_year when WITS lags) must be carried through.
        assert row["tariff_year"] == 2022

    def test_wb_field_years_are_carried_through(self, sample_indicator_row):
        # market_context here has both years present for lpi_score (2022)
        # and regulatory_quality (2024) -- each should keep its own year,
        # same idea as tariff_year but for World Bank fields.
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={"699": {
                2022: {"lpi_score": 3.4},
                2024: {"regulatory_quality": 0.5, "political_stability": -0.2},
            }},
            all_market_sizes={"699": 10_000_000},
        )
        row = rows[0]
        assert row["lpi_score"] == 3.4
        assert row["lpi_score_year"] == 2022
        assert row["regulatory_quality"] == 0.5
        assert row["regulatory_quality_year"] == 2024
        assert row["political_stability"] == -0.2
        assert row["political_stability_year"] == 2024

    def test_composite_equals_weighted_sum(self, sample_indicator_row):
        row = sample_indicator_row.copy()
        rows = enrich_indicators_with_scores(
            [row],
            market_context={},
            all_market_sizes={"699": 10_000_000},
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
        # abs tolerance, not just rel: `expected` sums sub-scores that were each
        # already rounded to 2dp, while opportunity_score rounds the sum of the
        # unrounded sub-scores -- the two can drift by a cent or two from
        # double-rounding, e.g. a sub-score of x.xx5 rounding a different way
        # in each path.
        assert enriched["opportunity_score"] == pytest.approx(round(expected, 2), abs=0.02)

    def test_foothold_score_uses_last_export_when_current_year_is_none(self, sample_indicator_row):
        # Market has no afg_export_value_usd for the current trade_data_year
        # (a genuine zero -- see _resolve_afg_last_export()'s docstring) but
        # does have a bounded-year afg_last_export_value_usd on record. The
        # composite's afg_foothold dimension must use that discounted
        # fallback, not the flat 0.0 "no history at all" baseline.
        row = sample_indicator_row.copy()
        row["afg_export_value_usd"] = None
        row["afg_last_export_value_usd"] = 1_000_000.0
        rows = enrich_indicators_with_scores(
            [row], market_context={}, all_market_sizes={"699": 10_000_000},
        )
        enriched = rows[0]
        assert enriched["score_afg_foothold"] == pytest.approx(84.0 * 0.7, rel=0.01)
        assert 0.0 < enriched["score_afg_foothold"] < 84.0

    def test_neutral_defaults_without_wb_and_tariff(self, sample_indicator_row):
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"699": 10_000_000},
        )
        row = rows[0]
        assert row["score_market_quality"] == pytest.approx(50.0)
        assert row["score_tariff"] == pytest.approx(50.0)
        assert row["gdp_per_capita_usd"] is None
        assert row["lpi_score_year"] is None
        assert row["regulatory_quality_year"] is None
        assert row["political_stability_year"] is None
        assert row["tariff_rate_pct"] is None
        assert row["tariff_year"] is None

    def test_fta_bonus_applied_when_wits_reports_ahs(self, sample_indicator_row):
        # has_fta is derived live from WITS's own AHS/MFN partner-segment
        # indicator (indicators.tariff_indicator), not a hand-maintained "which
        # FTAs is Afghanistan in" dict -- 'AHS' means WITS has an
        # Afghanistan-specific applied-tariff record on file for this reporter.
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 5.0, "indicator": "AHS", "year": 2022}},
        )
        assert rows[0]["has_fta"] is True
        assert rows[0]["score_fta"] == pytest.approx(100.0)

    def test_fta_bonus_not_applied_for_mfn(self, sample_indicator_row):
        # MFN means only the generic World-partner rate was found -- no
        # Afghanistan-specific record, so no differentiated-treatment bonus.
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 5.0, "indicator": "MFN", "year": 2022}},
        )
        assert rows[0]["has_fta"] is False
        assert rows[0]["score_fta"] == pytest.approx(0.0)

    def test_fta_bonus_not_applied_when_no_tariff_data(self, sample_indicator_row):
        rows = enrich_indicators_with_scores(
            [sample_indicator_row.copy()],
            market_context={},
            all_market_sizes={"699": 10_000_000},
        )
        assert rows[0]["has_fta"] is False
        assert rows[0]["score_fta"] == pytest.approx(0.0)

    def test_empty_input_passthrough(self):
        assert enrich_indicators_with_scores([], {}, {}) == []
