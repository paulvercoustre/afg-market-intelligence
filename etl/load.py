"""
Database loader — upserts ETL output rows into PostgreSQL.

All operations are idempotent: re-running the ETL for the same (product, year)
overwrites existing rows rather than creating duplicates.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.country_names import resolve_country_name

logger = logging.getLogger(__name__)


# ── Public loaders ────────────────────────────────────────────────────────────

def upsert_product(engine: Engine, name: str, category: str, hs_codes: list[str],
                   description: str) -> int:
    """Insert or update a product row; return its id."""
    sql = text("""
        INSERT INTO products (name, category, hs_codes, description)
        VALUES (:name, :category, :hs_codes, :description)
        ON CONFLICT (name)
        DO UPDATE SET
            category    = EXCLUDED.category,
            hs_codes    = EXCLUDED.hs_codes,
            description = EXCLUDED.description
        RETURNING id
    """)
    with engine.begin() as conn:
        row = conn.execute(sql, {
            "name": name,
            "category": category,
            "hs_codes": hs_codes,
            "description": description,
        }).fetchone()
    return row[0]


def upsert_market(engine: Engine, country_code: str, country_name: str | None) -> None:
    """Insert or update a market row with a displayable country name."""
    country_name = resolve_country_name(country_code, country_name)
    sql = text("""
        INSERT INTO markets (country_code, country_name)
        VALUES (:code, :name)
        ON CONFLICT (country_code) DO UPDATE SET
            country_name = CASE
                WHEN EXCLUDED.country_name IS NOT NULL THEN EXCLUDED.country_name
                WHEN LOWER(TRIM(markets.country_name)) IN ('', 'none', 'nan', 'null', '<na>') THEN NULL
                ELSE markets.country_name
            END
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"code": country_code, "name": country_name})


def bulk_upsert_trade_flows(engine: Engine, rows: list[dict]) -> int:
    """
    Upsert trade_flows rows in a single transaction.
    Conflict key: (product_id, importer_code, year).
    Returns number of rows processed.
    """
    if not rows:
        return 0
    sql = text("""
        INSERT INTO trade_flows
            (product_id, importer_code, importer_name, year,
             trade_value_usd, trade_quantity, quantity_unit, net_weight_kg)
        VALUES
            (:product_id, :importer_code, :importer_name, :year,
             :trade_value_usd, :trade_quantity, :quantity_unit, :net_weight_kg)
        ON CONFLICT (product_id, importer_code, year) DO UPDATE SET
            importer_name   = EXCLUDED.importer_name,
            trade_value_usd = EXCLUDED.trade_value_usd,
            trade_quantity  = EXCLUDED.trade_quantity,
            quantity_unit   = EXCLUDED.quantity_unit,
            net_weight_kg   = EXCLUDED.net_weight_kg,
            fetched_at      = NOW()
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def bulk_upsert_competitor_flows(engine: Engine, rows: list[dict]) -> int:
    """
    Upsert competitor_flows rows.
    Conflict key: (product_id, market_code, supplier_code, year).
    """
    if not rows:
        return 0
    rows = [
        {
            **row,
            "supplier_name": resolve_country_name(row["supplier_code"], row.get("supplier_name")),
        }
        for row in rows
    ]
    sql = text("""
        INSERT INTO competitor_flows
            (product_id, market_code, year,
             supplier_code, supplier_name, trade_value_usd, trade_quantity)
        VALUES
            (:product_id, :market_code, :year,
             :supplier_code, :supplier_name, :trade_value_usd, :trade_quantity)
        ON CONFLICT (product_id, market_code, supplier_code, year) DO UPDATE SET
            supplier_name   = EXCLUDED.supplier_name,
            trade_value_usd = EXCLUDED.trade_value_usd,
            trade_quantity  = EXCLUDED.trade_quantity
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def bulk_upsert_market_context(engine: Engine, rows: list[dict]) -> int:
    """
    Upsert World Bank market context rows.
    Conflict key: (country_code, year).
    """
    if not rows:
        return 0
    sql = text("""
        INSERT INTO market_context (
            country_code, year,
            gdp_usd, gdp_per_capita_usd, lpi_score,
            regulatory_quality, political_stability,
            fetched_at
        ) VALUES (
            :country_code, :year,
            :gdp_usd, :gdp_per_capita_usd, :lpi_score,
            :regulatory_quality, :political_stability,
            NOW()
        )
        ON CONFLICT (country_code, year) DO UPDATE SET
            gdp_usd              = EXCLUDED.gdp_usd,
            gdp_per_capita_usd   = EXCLUDED.gdp_per_capita_usd,
            lpi_score            = EXCLUDED.lpi_score,
            regulatory_quality   = EXCLUDED.regulatory_quality,
            political_stability  = EXCLUDED.political_stability,
            fetched_at           = NOW()
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def bulk_upsert_indicators(engine: Engine, rows: list[dict]) -> int:
    """
    Upsert pre-computed indicator rows (including opportunity scores).
    Conflict key: (product_id, market_code, computed_for_year).
    """
    if not rows:
        return 0
    sql = text("""
        INSERT INTO indicators (
            product_id, market_code, computed_for_year,
            global_market_size_usd, afg_export_value_usd,
            yoy_growth_pct, cagr_pct, absolute_growth_usd, growth_pct,
            first_year, last_year,
            market_share_pct, afg_supplier_rank,
            unit_price_usd, market_avg_price_usd,
            price_vs_market_pct, price_competitiveness,
            opportunity_score, distance_km, has_fta, language_similarity,
            gdp_per_capita_usd, lpi_score, regulatory_quality, political_stability,
            tariff_rate_pct, tariff_indicator,
            score_market_size, score_market_growth, score_market_quality,
            score_price_competitiveness, score_afg_foothold,
            score_distance, score_language, score_fta, score_tariff,
            computed_at
        ) VALUES (
            :product_id, :market_code, :computed_for_year,
            :global_market_size_usd, :afg_export_value_usd,
            :yoy_growth_pct, :cagr_pct, :absolute_growth_usd, :growth_pct,
            :first_year, :last_year,
            :market_share_pct, :afg_supplier_rank,
            :unit_price_usd, :market_avg_price_usd,
            :price_vs_market_pct, :price_competitiveness,
            :opportunity_score, :distance_km, :has_fta, :language_similarity,
            :gdp_per_capita_usd, :lpi_score, :regulatory_quality, :political_stability,
            :tariff_rate_pct, :tariff_indicator,
            :score_market_size, :score_market_growth, :score_market_quality,
            :score_price_competitiveness, :score_afg_foothold,
            :score_distance, :score_language, :score_fta, :score_tariff,
            NOW()
        )
        ON CONFLICT (product_id, market_code, computed_for_year) DO UPDATE SET
            global_market_size_usd      = EXCLUDED.global_market_size_usd,
            afg_export_value_usd        = EXCLUDED.afg_export_value_usd,
            yoy_growth_pct              = EXCLUDED.yoy_growth_pct,
            cagr_pct                    = EXCLUDED.cagr_pct,
            absolute_growth_usd         = EXCLUDED.absolute_growth_usd,
            growth_pct                  = EXCLUDED.growth_pct,
            first_year                  = EXCLUDED.first_year,
            last_year                   = EXCLUDED.last_year,
            market_share_pct            = EXCLUDED.market_share_pct,
            afg_supplier_rank           = EXCLUDED.afg_supplier_rank,
            unit_price_usd              = EXCLUDED.unit_price_usd,
            market_avg_price_usd        = EXCLUDED.market_avg_price_usd,
            price_vs_market_pct         = EXCLUDED.price_vs_market_pct,
            price_competitiveness       = EXCLUDED.price_competitiveness,
            opportunity_score           = EXCLUDED.opportunity_score,
            distance_km                 = EXCLUDED.distance_km,
            has_fta                     = EXCLUDED.has_fta,
            language_similarity         = EXCLUDED.language_similarity,
            gdp_per_capita_usd          = EXCLUDED.gdp_per_capita_usd,
            lpi_score                   = EXCLUDED.lpi_score,
            regulatory_quality          = EXCLUDED.regulatory_quality,
            political_stability         = EXCLUDED.political_stability,
            tariff_rate_pct             = EXCLUDED.tariff_rate_pct,
            tariff_indicator            = EXCLUDED.tariff_indicator,
            score_market_size           = EXCLUDED.score_market_size,
            score_market_growth         = EXCLUDED.score_market_growth,
            score_market_quality        = EXCLUDED.score_market_quality,
            score_price_competitiveness = EXCLUDED.score_price_competitiveness,
            score_afg_foothold          = EXCLUDED.score_afg_foothold,
            score_distance              = EXCLUDED.score_distance,
            score_language              = EXCLUDED.score_language,
            score_fta                   = EXCLUDED.score_fta,
            score_tariff                = EXCLUDED.score_tariff,
            computed_at                 = NOW()
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def load_market_context(engine: Engine) -> list[dict]:
    """
    Read existing market_context rows back from the DB (used by --skip-world-bank
    so scoring can still use previously fetched World Bank data).
    """
    sql = text("""
        SELECT country_code, year, gdp_usd, gdp_per_capita_usd, lpi_score,
               regulatory_quality, political_stability
        FROM market_context
    """)
    with engine.connect() as conn:
        result = conn.execute(sql)
        return [dict(row._mapping) for row in result]


def log_pipeline_run(engine: Engine, status: str, products_updated: int,
                     errors: list[dict]) -> None:
    # CAST(... AS JSONB) instead of ::jsonb — SQLAlchemy's text() mis-parses
    # a bind param immediately followed by a double-colon cast.
    sql = text("""
        INSERT INTO pipeline_runs (run_at, status, products_updated, errors_json)
        VALUES (NOW(), :status, :products_updated, CAST(:errors_json AS JSONB))
    """)
    import json
    with engine.begin() as conn:
        conn.execute(sql, {
            "status": status,
            "products_updated": products_updated,
            "errors_json": json.dumps(errors),
        })
