export interface ProductSummary {
  id: number
  name: string
  category: string
  hs_codes: string[]
  description: string | null
  has_data: boolean
  last_year: number | null
  total_export_value_usd: number | null
  top_market_name: string | null
}

export interface ScoreBreakdown {
  market_size: number | null
  market_growth: number | null
  market_quality: number | null
  price_competitiveness: number | null
  afg_foothold: number | null
  distance: number | null
  language: number | null
  fta_status: number | null
  tariff: number | null
}

export interface MarketContextData {
  gdp_per_capita_usd: number | null
  lpi_score: number | null
  lpi_score_year: number | null
  regulatory_quality: number | null
  regulatory_quality_year: number | null
  political_stability: number | null
  political_stability_year: number | null
  tariff_rate_pct: number | null
  tariff_indicator: string | null
  tariff_year: number | null
}

export interface MarketOpportunity {
  rank: number
  market_code: string
  market_name: string | null
  opportunity_score: number | null
  global_market_size_usd: number | null
  cagr_pct: number | null
  afg_export_value_usd: number | null
  market_share_pct: number | null
  price_competitiveness: string | null
  distance_km: number | null
  has_fta: boolean | null
  language_similarity: number | null
  tariff_rate_pct: number | null
  trade_data_year: number | null
  afg_last_export_year: number | null
  afg_last_export_value_usd: number | null
  score_breakdown: ScoreBreakdown
  context: MarketContextData
}

export interface DiscoveryResult {
  hs_code: string
  product_name: string | null
  computed_for_year: number
  total_markets_scored: number
  markets: MarketOpportunity[]
}

export interface GrowthMetrics {
  yoy_growth_pct: number | null
  cagr_pct: number | null
  absolute_growth_usd: number | null
  growth_pct: number | null
  first_year: number | null
  last_year: number | null
}

export interface PriceMetrics {
  unit_price_usd: number | null
  market_avg_price_usd: number | null
  price_vs_market_pct: number | null
  price_competitiveness: string | null
}

export interface MarketIndicator {
  market_code: string
  market_name: string | null
  afg_export_value_usd: number | null
  global_market_size_usd: number | null
  market_share_pct: number | null
  afg_supplier_rank: number | null
  trade_data_year: number | null
  afg_last_export_year: number | null
  afg_last_export_value_usd: number | null
  growth: GrowthMetrics
  price: PriceMetrics
}

export interface CompetitorRow {
  supplier_code: string
  supplier_name: string
  trade_value_usd: number | null
  trade_quantity: number | null
  market_share_pct: number | null
}

export interface NextStep {
  order: number
  title: string
  description: string
  resource_url: string | null
}

export interface MarketProfile {
  hs_code: string
  product_name: string | null
  market_code: string
  market_name: string | null
  computed_for_year: number | null
  opportunity_score: number | null
  score_breakdown: ScoreBreakdown
  context: MarketContextData
  trade: MarketIndicator | null
  competitors: CompetitorRow[]
  next_steps: NextStep[]
}
