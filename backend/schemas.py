"""Pydantic response schemas for all API endpoints."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, field_validator


def _coerce_hs_codes(v) -> list[str]:
    """Accept ARRAY from PostgreSQL (list) or plain TEXT from SQLite (str)."""
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return [v]
    return list(v) if v else []


class ProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    hs_codes: list[str]
    description: str | None
    # Enriched by the service layer
    has_data: bool = False
    last_year: int | None = None
    total_export_value_usd: float | None = None
    top_market_name: str | None = None

    @field_validator("hs_codes", mode="before")
    @classmethod
    def normalise_hs_codes(cls, v):
        return _coerce_hs_codes(v)


class GrowthMetrics(BaseModel):
    yoy_growth_pct: float | None
    cagr_pct: float | None
    absolute_growth_usd: float | None
    growth_pct: float | None
    first_year: int | None
    last_year: int | None


class PriceMetrics(BaseModel):
    unit_price_usd: float | None
    price_basis: str | None  # "kg" or a native unit, e.g. "m²" -- see config.NATIVE_UNIT_PRICE_BASES
    market_avg_price_usd: float | None
    price_vs_market_pct: float | None
    price_competitiveness: str | None


class MarketIndicator(BaseModel):
    market_code: str
    market_name: str | None
    afg_export_value_usd: float | None
    global_market_size_usd: float | None
    market_share_pct: float | None
    afg_supplier_rank: int | None
    trade_data_year: int | None = None
    afg_last_export_year: int | None = None
    afg_last_export_value_usd: float | None = None
    growth: GrowthMetrics
    price: PriceMetrics


class CompetitorRow(BaseModel):
    supplier_code: str
    supplier_name: str
    trade_value_usd: float | None
    trade_quantity: float | None
    market_share_pct: float | None


class MarketDetail(BaseModel):
    market_code: str
    market_name: str | None
    product_id: int
    product_name: str
    indicator: MarketIndicator | None
    competitors: list[CompetitorRow]
    trade_history: list[TradeHistoryPoint]


class TradeHistoryPoint(BaseModel):
    year: int
    trade_value_usd: float | None
    trade_quantity: float | None


class ProductDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    hs_codes: list[str]
    description: str | None
    markets: list[MarketIndicator]

    @field_validator("hs_codes", mode="before")
    @classmethod
    def normalise_hs_codes(cls, v):
        return _coerce_hs_codes(v)


class IndicatorDefinition(BaseModel):
    key: str
    label: str
    description: str
    unit: str | None = None
    tooltip: str | None = None


class PipelineRunSummary(BaseModel):
    id: int
    run_at: str
    status: str
    products_updated: int


# ── Market discovery / opportunity scoring schemas ─────────────────────────────

class ScoreBreakdown(BaseModel):
    market_size: float | None
    market_growth: float | None
    market_quality: float | None
    price_competitiveness: float | None
    afg_foothold: float | None
    distance: float | None
    language: float | None
    fta_status: float | None
    tariff: float | None = None


class MarketContextData(BaseModel):
    gdp_per_capita_usd: float | None
    lpi_score: float | None
    lpi_score_year: int | None = None
    regulatory_quality: float | None
    regulatory_quality_year: int | None = None
    political_stability: float | None
    political_stability_year: int | None = None
    tariff_rate_pct: float | None = None
    tariff_indicator: str | None = None
    tariff_year: int | None = None


class MarketOpportunity(BaseModel):
    """Single market row in the discovery ranked list."""
    rank: int
    market_code: str
    market_name: str | None
    opportunity_score: float | None
    global_market_size_usd: float | None
    cagr_pct: float | None
    afg_export_value_usd: float | None
    market_share_pct: float | None
    price_competitiveness: str | None
    distance_km: int | None
    has_fta: bool | None
    language_similarity: float | None
    tariff_rate_pct: float | None = None
    trade_data_year: int | None = None
    afg_last_export_year: int | None = None
    afg_last_export_value_usd: float | None = None
    score_breakdown: ScoreBreakdown
    context: MarketContextData


class DiscoveryResult(BaseModel):
    """Response for GET /api/discover/{hs_code}"""
    hs_code: str
    product_name: str | None
    computed_for_year: int
    total_markets_scored: int
    markets: list[MarketOpportunity]


class NextStep(BaseModel):
    order: int
    title: str
    description: str
    resource_url: str | None = None


class MarketProfile(BaseModel):
    """Detailed market profile for GET /api/discover/{hs_code}/markets/{market_code}"""
    hs_code: str
    product_name: str | None
    market_code: str
    market_name: str | None
    computed_for_year: int | None = None
    opportunity_score: float | None
    score_breakdown: ScoreBreakdown
    context: MarketContextData
    trade: MarketIndicator | None
    competitors: list[CompetitorRow]
    next_steps: list[NextStep]


# Forward reference resolution
MarketDetail.model_rebuild()
