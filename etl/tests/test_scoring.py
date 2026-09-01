"""Unit tests for opportunity scoring in etl/transform.py."""

import math

import pytest

from config import (
    CAGR_SCORE_BAND_PCT,
    MARKET_SIZE_LOG_FLOOR_USD,
    MAX_GREAT_CIRCLE_DISTANCE_KM,
    OPPORTUNITY_SCORE_WEIGHTS,
    TARIFF_SCORE_PER_PCT,
)
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
    def test_market_size_missing_returns_none(self):
        # No data at all (as opposed to a genuine zero) -- caller excludes
        # this from the composite and renormalises remaining weights,
        # rather than guessing a default.
        assert _score_market_size(None, 1.0) is None

    def test_market_size_genuine_zero_scores_zero(self):
        assert _score_market_size(0, 1.0) == 0.0

    def test_market_size_below_floor_clips_to_zero_not_negative(self):
        # A real but tiny value at or below F would produce ln(v/F) <= 0 --
        # clipped to 0 rather than stored as a negative score.
        log_max = math.log(1_000_000 / MARKET_SIZE_LOG_FLOOR_USD)
        assert _score_market_size(MARKET_SIZE_LOG_FLOOR_USD, log_max) == 0.0
        assert _score_market_size(MARKET_SIZE_LOG_FLOOR_USD - 1, log_max) == 0.0

    def test_market_size_leader_scores_100(self):
        # v_i == v_max (the observed leader for this product) should score
        # exactly 100 -- log_max is precomputed by the caller as
        # log(v_max / F), so v_i == v_max makes the ratio exactly 1.0.
        log_max = math.log(1_000_000 / MARKET_SIZE_LOG_FLOOR_USD)
        assert _score_market_size(1_000_000, log_max) == pytest.approx(100.0)

    def test_market_size_log_scale_not_linear(self):
        # A market at 1% of the leader's raw size should score far higher
        # than the naive linear ratio (10_000 / 1_000_000 * 100 == 1.0) --
        # this is the whole point of log-scaling (see docstring): it keeps
        # the "long tail" of smaller markets differentiated instead of
        # collapsing them all near zero.
        log_max = math.log(1_000_000 / MARKET_SIZE_LOG_FLOOR_USD)
        score = _score_market_size(10_000, log_max)
        assert score == pytest.approx(39.41, abs=0.01)
        assert score > 20.0  # far above the 1.0 a linear ratio would give

    def test_growth_missing_returns_none(self):
        # No data at all (as opposed to a genuine 0% reading) -- caller
        # excludes this from the composite and renormalises remaining
        # weights, rather than guessing a default (same as market_size).
        assert _score_growth(None) is None

    def test_growth_boundaries(self):
        assert _score_growth(0) == pytest.approx(50.0)
        assert _score_growth(CAGR_SCORE_BAND_PCT) == pytest.approx(100.0)
        assert _score_growth(-CAGR_SCORE_BAND_PCT) == pytest.approx(0.0)

    def test_growth_beyond_band_clamps_not_overshoots(self):
        # Well beyond the +-W reference band -- must clamp, not extrapolate
        # past [0, 100].
        assert _score_growth(CAGR_SCORE_BAND_PCT * 3) == pytest.approx(100.0)
        assert _score_growth(-CAGR_SCORE_BAND_PCT * 3) == pytest.approx(0.0)

    def test_market_quality_with_full_context(self):
        # regulatory_quality and political_stability are both on the 0..100
        # WGI "score" scale -- neither needs rescaling. Only lpi_score (1..5)
        # does.
        ctx = {"lpi_score": 3.0, "regulatory_quality": 50.0, "political_stability": 50.0}
        # LPI 3 → 50, regulatory_quality 50 → 50, political_stability 50 → 50; average = 50
        assert _score_market_quality(ctx) == pytest.approx(50.0)

    def test_regulatory_quality_is_not_rescaled(self):
        # A real GOV_WGI_RQ.SC value (e.g. 30, Afghanistan-range) must pass
        # through unchanged, not get squashed through the old -2.5..2.5
        # rescale (which would produce (30+2.5)/5*100=650, clamped to 100).
        ctx = {"regulatory_quality": 30.0}
        assert _score_market_quality(ctx) == pytest.approx(30.0)

    def test_political_stability_is_not_rescaled(self):
        # A real GOV_WGI_PV.SC value (e.g. 25, Afghanistan-range) must pass
        # through unchanged, not get squashed through the -2.5..2.5 rescale
        # (which would produce (25+2.5)/5*100=550, clamped to 100).
        ctx = {"political_stability": 25.0}
        assert _score_market_quality(ctx) == pytest.approx(25.0)

    def test_market_quality_neutral_when_empty(self):
        assert _score_market_quality({}) == 50.0

    def test_price_competitiveness_mapping(self):
        assert _score_price("Substantially Below Market") == 100.0
        assert _score_price("Below Market") == 75.0
        assert _score_price("Near Market") == 50.0
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
            market_context={"699": {2024: {"lpi_score": 3.5, "regulatory_quality": 50.5}}},
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
                2024: {"regulatory_quality": 45.5, "political_stability": 32.0},
            }},
            all_market_sizes={"699": 10_000_000},
        )
        row = rows[0]
        assert row["lpi_score"] == 3.4
        assert row["lpi_score_year"] == 2022
        assert row["regulatory_quality"] == 45.5
        assert row["regulatory_quality_year"] == 2024
        assert row["political_stability"] == 32.0
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
        )
        # abs tolerance, not just rel: `expected` sums sub-scores that were each
        # already rounded to 2dp, while opportunity_score rounds the sum of the
        # unrounded sub-scores -- the two can drift by a cent or two from
        # double-rounding, e.g. a sub-score of x.xx5 rounding a different way
        # in each path.
        assert enriched["opportunity_score"] == pytest.approx(round(expected, 2), abs=0.02)

    def test_missing_market_size_excluded_and_weights_renormalised(self, sample_indicator_row):
        # global_market_size_usd missing entirely (not a genuine zero) --
        # score_market_size must be None (not 0, not a guessed default), and
        # opportunity_score must renormalise the remaining 7 dimensions'
        # weights to sum back to 1.0 rather than silently dropping 20% of
        # the composite's weight.
        row = sample_indicator_row.copy()
        row["global_market_size_usd"] = None
        rows = enrich_indicators_with_scores(
            [row],
            market_context={},
            all_market_sizes={"699": 10_000_000},
            tariffs={},
        )
        enriched = rows[0]
        assert enriched["score_market_size"] is None

        weights = OPPORTUNITY_SCORE_WEIGHTS
        other_dimensions = (
            enriched["score_market_growth"] * weights["market_growth"]
            + enriched["score_market_quality"] * weights["market_quality"]
            + enriched["score_price_competitiveness"] * weights["price_competitiveness"]
            + enriched["score_tariff"] * weights["tariff"]
            + enriched["score_afg_foothold"] * weights["afg_foothold"]
            + enriched["score_distance"] * weights["distance"]
            + enriched["score_language"] * weights["language"]
        )
        expected = other_dimensions / (1.0 - weights["market_size"])
        assert enriched["opportunity_score"] == pytest.approx(round(expected, 2), abs=0.02)

    def test_missing_cagr_excluded_and_weights_renormalised(self, sample_indicator_row):
        # cagr_pct missing entirely -- same treatment as missing
        # global_market_size_usd above: score_market_growth is None, and
        # the remaining 7 dimensions' weights renormalise to sum to 1.0.
        row = sample_indicator_row.copy()
        row["cagr_pct"] = None
        rows = enrich_indicators_with_scores(
            [row],
            market_context={},
            all_market_sizes={"699": 10_000_000},
            tariffs={},
        )
        enriched = rows[0]
        assert enriched["score_market_growth"] is None

        weights = OPPORTUNITY_SCORE_WEIGHTS
        other_dimensions = (
            enriched["score_market_size"] * weights["market_size"]
            + enriched["score_market_quality"] * weights["market_quality"]
            + enriched["score_price_competitiveness"] * weights["price_competitiveness"]
            + enriched["score_tariff"] * weights["tariff"]
            + enriched["score_afg_foothold"] * weights["afg_foothold"]
            + enriched["score_distance"] * weights["distance"]
            + enriched["score_language"] * weights["language"]
        )
        expected = other_dimensions / (1.0 - weights["market_growth"])
        assert enriched["opportunity_score"] == pytest.approx(round(expected, 2), abs=0.02)

    def test_both_market_size_and_growth_missing_renormalise_together(self, sample_indicator_row):
        # Both nullable dimensions missing at once -- the renormalisation
        # must generalise, not just handle one hardcoded case at a time.
        row = sample_indicator_row.copy()
        row["global_market_size_usd"] = None
        row["cagr_pct"] = None
        rows = enrich_indicators_with_scores(
            [row],
            market_context={},
            all_market_sizes={"699": 10_000_000},
            tariffs={},
        )
        enriched = rows[0]
        assert enriched["score_market_size"] is None
        assert enriched["score_market_growth"] is None

        weights = OPPORTUNITY_SCORE_WEIGHTS
        other_dimensions = (
            enriched["score_market_quality"] * weights["market_quality"]
            + enriched["score_price_competitiveness"] * weights["price_competitiveness"]
            + enriched["score_tariff"] * weights["tariff"]
            + enriched["score_afg_foothold"] * weights["afg_foothold"]
            + enriched["score_distance"] * weights["distance"]
            + enriched["score_language"] * weights["language"]
        )
        remaining_weight = 1.0 - weights["market_size"] - weights["market_growth"]
        expected = other_dimensions / remaining_weight
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

    def test_tariff_discarded_when_afghanistan_has_no_trade_evidence(self, sample_indicator_row):
        # WITS reports MFN/Applied rates even for products a market doesn't
        # actually trade at all (its own site says so: "MFN and Applied
        # Tariff are provided for both traded and non-traded goods"), and
        # the tariff API response has no "is this traded" flag to filter
        # those out. A market with zero real Afghan export evidence -- this
        # year AND historically -- must not keep a fetched rate, regardless
        # of whether WITS labelled it AHS or MFN.
        row = sample_indicator_row.copy()
        row["afg_export_value_usd"] = None
        row["afg_last_export_value_usd"] = None
        rows = enrich_indicators_with_scores(
            [row], market_context={}, all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 12.5, "indicator": "AHS", "year": 2022}},
        )
        enriched = rows[0]
        assert enriched["tariff_rate_pct"] is None
        assert enriched["tariff_indicator"] is None
        assert enriched["tariff_year"] is None
        assert enriched["has_fta"] is False
        assert enriched["score_tariff"] == pytest.approx(50.0)  # neutral default

    def test_tariff_kept_when_only_historical_trade_evidence_exists(self, sample_indicator_row):
        # No trade this year, but a real historical shipment on record --
        # same "don't discard useful signal over a reporting gap" logic
        # already used for the foothold score.
        row = sample_indicator_row.copy()
        row["afg_export_value_usd"] = None
        row["afg_last_export_value_usd"] = 1_000_000.0
        rows = enrich_indicators_with_scores(
            [row], market_context={}, all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 12.5, "indicator": "AHS", "year": 2022}},
        )
        assert rows[0]["tariff_rate_pct"] == pytest.approx(12.5)

    def test_tariff_kept_for_tiny_but_real_trade_value(self, sample_indicator_row):
        # A genuine but very small export value must still count as real
        # trade evidence -- this is a raw-value check, not a rounded or
        # displayed figure.
        row = sample_indicator_row.copy()
        row["afg_export_value_usd"] = 12.0
        row["afg_last_export_value_usd"] = None
        rows = enrich_indicators_with_scores(
            [row], market_context={}, all_market_sizes={"699": 10_000_000},
            tariffs={"699": {"rate": 8.0, "indicator": "MFN", "year": 2023}},
        )
        assert rows[0]["tariff_rate_pct"] == pytest.approx(8.0)
