"""
Market discovery service — serves the opportunity scoring / ranking queries.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.country_names import resolve_country_name


def get_ranked_markets(
    db: Session,
    hs_code: str,
    limit: int = 50,
    min_score: float | None = None,
) -> dict:
    """
    Return markets ranked by opportunity score for a given HS code.

    Looks up the product matching any of its hs_codes, then returns all
    indicators rows ordered by opportunity_score DESC.
    """
    product = _find_product(db, hs_code)
    if product is None:
        return None

    product_id, product_name = product

    params: dict = {"product_id": product_id}
    score_filter = ""
    if min_score is not None:
        score_filter = " AND i.opportunity_score >= :min_score"
        params["min_score"] = min_score

    sql = text(f"""
        SELECT
            i.market_code,
            m.country_name       AS market_name,
            i.computed_for_year,
            i.trade_data_year,
            i.opportunity_score,
            i.global_market_size_usd,
            i.cagr_pct,
            i.afg_export_value_usd,
            i.afg_last_export_year,
            i.afg_last_export_value_usd,
            i.market_share_pct,
            i.price_competitiveness,
            i.distance_km,
            i.has_fta,
            i.language_similarity,
            i.tariff_rate_pct,
            i.tariff_indicator,
            i.tariff_year,
            i.score_market_size,
            i.score_market_growth,
            i.score_market_quality,
            i.score_price_competitiveness,
            i.score_afg_foothold,
            i.score_distance,
            i.score_language,
            i.score_fta,
            i.score_tariff,
            i.gdp_per_capita_usd,
            i.lpi_score,
            i.lpi_score_year,
            i.regulatory_quality,
            i.regulatory_quality_year,
            i.political_stability,
            i.political_stability_year
        FROM indicators i
        LEFT JOIN markets m ON m.country_code = i.market_code
        WHERE i.product_id = :product_id
          AND i.computed_for_year = (
              SELECT MAX(computed_for_year) FROM indicators WHERE product_id = :product_id
          )
          {score_filter}
        ORDER BY i.opportunity_score DESC NULLS LAST
        LIMIT {int(limit)}
    """)

    rows = db.execute(sql, params).mappings().fetchall()

    year = rows[0]["computed_for_year"] if rows else 0
    markets = []
    for rank, r in enumerate(rows, start=1):
        market_name = resolve_country_name(r["market_code"], r["market_name"])
        markets.append({
            "rank": rank,
            "market_code": r["market_code"],
            "market_name": market_name,
            "opportunity_score": _f(r["opportunity_score"]),
            "global_market_size_usd": _f(r["global_market_size_usd"]),
            "cagr_pct": _f(r["cagr_pct"]),
            "afg_export_value_usd": _f(r["afg_export_value_usd"]),
            "afg_last_export_year": r["afg_last_export_year"],
            "afg_last_export_value_usd": _f(r["afg_last_export_value_usd"]),
            "market_share_pct": _f(r["market_share_pct"]),
            "price_competitiveness": r["price_competitiveness"],
            "distance_km": r["distance_km"],
            "has_fta": r["has_fta"],
            "language_similarity": _f(r["language_similarity"]),
            "tariff_rate_pct": _f(r["tariff_rate_pct"]),
            "trade_data_year": r["trade_data_year"],
            "score_breakdown": {
                "market_size": _f(r["score_market_size"]),
                "market_growth": _f(r["score_market_growth"]),
                "market_quality": _f(r["score_market_quality"]),
                "price_competitiveness": _f(r["score_price_competitiveness"]),
                "afg_foothold": _f(r["score_afg_foothold"]),
                "distance": _f(r["score_distance"]),
                "language": _f(r["score_language"]),
                "fta_status": _f(r["score_fta"]),
                "tariff": _f(r["score_tariff"]),
            },
            "context": {
                "gdp_per_capita_usd": _f(r["gdp_per_capita_usd"]),
                "lpi_score": _f(r["lpi_score"]),
                "lpi_score_year": r["lpi_score_year"],
                "regulatory_quality": _f(r["regulatory_quality"]),
                "regulatory_quality_year": r["regulatory_quality_year"],
                "political_stability": _f(r["political_stability"]),
                "political_stability_year": r["political_stability_year"],
                "tariff_rate_pct": _f(r["tariff_rate_pct"]),
                "tariff_indicator": r["tariff_indicator"],
                "tariff_year": r["tariff_year"],
            },
        })

    return {
        "hs_code": hs_code,
        "product_name": product_name,
        "computed_for_year": year,
        "total_markets_scored": len(rows),
        "markets": markets,
    }


def get_market_profile(db: Session, hs_code: str, market_code: str) -> dict | None:
    """Return a detailed market profile including trade indicators and next steps."""
    product = _find_product(db, hs_code)
    if product is None:
        return None

    product_id, product_name = product

    sql = text("""
        SELECT
            i.*,
            m.country_name AS market_name
        FROM indicators i
        LEFT JOIN markets m ON m.country_code = i.market_code
        WHERE i.product_id = :product_id
          AND i.market_code = :market_code
          AND i.computed_for_year = (
              SELECT MAX(computed_for_year) FROM indicators
              WHERE product_id = :product_id AND market_code = :market_code
          )
        LIMIT 1
    """)
    row = db.execute(sql, {"product_id": product_id, "market_code": market_code}).mappings().fetchone()
    if row is None:
        return None
    market_name = resolve_country_name(market_code, row["market_name"])

    # Competitor flows for this market
    comp_sql = text("""
        SELECT
            cf.supplier_code,
            cf.supplier_name,
            cf.trade_value_usd,
            cf.trade_quantity,
            SUM(cf.trade_value_usd) OVER () AS total_value
        FROM competitor_flows cf
        WHERE cf.product_id = :product_id
          AND cf.market_code = :market_code
          AND cf.year = (
              SELECT MAX(year) FROM competitor_flows
              WHERE product_id = :product_id AND market_code = :market_code
          )
        ORDER BY cf.trade_value_usd DESC NULLS LAST
        LIMIT 15
    """)
    comp_rows = db.execute(comp_sql, {"product_id": product_id, "market_code": market_code}).mappings().fetchall()
    competitors = []
    for cr in comp_rows:
        total = float(cr["total_value"]) if cr["total_value"] else None
        share = (float(cr["trade_value_usd"]) / total * 100) if total and cr["trade_value_usd"] else None
        competitors.append({
            "supplier_code": cr["supplier_code"],
            "supplier_name": resolve_country_name(cr["supplier_code"], cr["supplier_name"]),
            "trade_value_usd": _f(cr["trade_value_usd"]),
            "trade_quantity": _f(cr["trade_quantity"]),
            "market_share_pct": round(share, 2) if share else None,
        })

    return {
        "hs_code": hs_code,
        "product_name": product_name,
        "market_code": market_code,
        "market_name": market_name,
        "computed_for_year": row["computed_for_year"],
        "opportunity_score": _f(row["opportunity_score"]),
        "score_breakdown": {
            "market_size": _f(row["score_market_size"]),
            "market_growth": _f(row["score_market_growth"]),
            "market_quality": _f(row["score_market_quality"]),
            "price_competitiveness": _f(row["score_price_competitiveness"]),
            "afg_foothold": _f(row["score_afg_foothold"]),
            "distance": _f(row["score_distance"]),
            "language": _f(row["score_language"]),
            "fta_status": _f(row["score_fta"]),
            "tariff": _f(row["score_tariff"]),
        },
        "context": {
            "gdp_per_capita_usd": _f(row["gdp_per_capita_usd"]),
            "lpi_score": _f(row["lpi_score"]),
            "lpi_score_year": row["lpi_score_year"],
            "regulatory_quality": _f(row["regulatory_quality"]),
            "regulatory_quality_year": row["regulatory_quality_year"],
            "political_stability": _f(row["political_stability"]),
            "political_stability_year": row["political_stability_year"],
            "tariff_rate_pct": _f(row["tariff_rate_pct"]),
            "tariff_indicator": row["tariff_indicator"],
            "tariff_year": row["tariff_year"],
        },
        "trade": {
            "market_code": market_code,
            "market_name": market_name,
            "afg_export_value_usd": _f(row["afg_export_value_usd"]),
            "global_market_size_usd": _f(row["global_market_size_usd"]),
            "market_share_pct": _f(row["market_share_pct"]),
            "afg_supplier_rank": row["afg_supplier_rank"],
            "trade_data_year": row["trade_data_year"],
            "afg_last_export_year": row["afg_last_export_year"],
            "afg_last_export_value_usd": _f(row["afg_last_export_value_usd"]),
            "growth": {
                "yoy_growth_pct": _f(row["yoy_growth_pct"]),
                "cagr_pct": _f(row["cagr_pct"]),
                "absolute_growth_usd": _f(row["absolute_growth_usd"]),
                "growth_pct": _f(row["growth_pct"]),
                "first_year": row["first_year"],
                "last_year": row["last_year"],
            },
            "price": {
                "unit_price_usd": _f(row["unit_price_usd"]),
                "price_basis": row["price_basis"],
                "market_avg_price_usd": _f(row["market_avg_price_usd"]),
                "price_vs_market_pct": _f(row["price_vs_market_pct"]),
                "price_competitiveness": row["price_competitiveness"],
            },
        },
        "competitors": competitors,
        "next_steps": _build_next_steps(row, market_code),
    }


def _find_product(db: Session, hs_code: str):
    """Return (product_id, product_name) for any product whose hs_codes contains hs_code."""
    from sqlalchemy import String, cast

    from backend.models import Product as ProductModel
    clean = hs_code.replace(".", "").strip()
    row = (
        db.query(ProductModel.id, ProductModel.name)
        .filter(cast(ProductModel.hs_codes, String).contains(clean))
        .first()
    )
    return (row[0], row[1]) if row else None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _build_next_steps(row, market_code: str) -> list[dict]:
    """
    Generate practical market-entry next steps based on the market profile.
    This is a rule-based v1; a future version can call an LLM for richer content.
    """
    steps = []
    order = 1

    has_fta = row.get("has_fta")
    dist = row.get("distance_km")
    competitiveness = row.get("price_competitiveness")
    tariff_rate = row.get("tariff_rate_pct")
    tariff_indicator = row.get("tariff_indicator")

    steps.append({
        "order": order,
        "title": "Verify export documentation requirements",
        "description": (
            "Contact the Afghanistan Chamber of Commerce and Industry (ACCI) "
            "to obtain the current export licence, certificate of origin, and "
            "phytosanitary certificate requirements for this product and destination market."
        ),
        "resource_url": None,
    })
    order += 1

    if has_fta:
        steps.append({
            "order": order,
            "title": "Claim preferential tariff rates",
            "description": (
                "Afghanistan has a preferential trade arrangement with this market. "
                "Obtain a GSP/SAPTA/ECO certificate of origin from ACCI or the relevant "
                "customs authority to benefit from reduced import duties."
            ),
            "resource_url": None,
        })
        order += 1

    if tariff_rate is not None:
        rate_pct = float(tariff_rate)
        rate_label = f"{rate_pct:.1f}%"
        if rate_pct >= 15:
            steps.append({
                "order": order,
                "title": f"Plan for high import tariff ({rate_label})",
                "description": (
                    f"This market levies an import tariff of {rate_label} on Afghan goods "
                    f"({'preferential' if tariff_indicator == 'AHS' else 'MFN'} rate). "
                    "Factor this into your pricing strategy and explore tariff-engineering "
                    "options (e.g., shipping at an earlier processing stage with lower duty)."
                ),
                "resource_url": "https://wits.worldbank.org/",
            })
            order += 1
        elif rate_pct < 5:
            steps.append({
                "order": order,
                "title": f"Low tariff barrier ({rate_label}) — accelerate market entry",
                "description": (
                    f"This market has a low import duty of {rate_label}, lowering the "
                    "cost barrier to entry. Prioritise this market in your sales pipeline."
                ),
                "resource_url": None,
            })
            order += 1

    if dist is not None and dist < 3000:
        steps.append({
            "order": order,
            "title": "Explore overland trade routes",
            "description": (
                "This market is within overland transport range. Contact the "
                "Afghanistan Customs Department and the relevant border authority "
                "to understand transit procedures and costs via road or rail."
            ),
            "resource_url": None,
        })
        order += 1

    if competitiveness in ("Highly Competitive", "Competitive"):
        steps.append({
            "order": order,
            "title": "Lead with price in buyer outreach",
            "description": (
                "Afghan pricing is competitive in this market. Emphasise cost "
                "advantage alongside quality certifications when approaching buyers "
                "and importers."
            ),
            "resource_url": None,
        })
        order += 1

    steps.append({
        "order": order,
        "title": "Identify and contact buyers",
        "description": (
            "Search the ITC Trade Map buyer directory and the target country's "
            "importer associations for companies actively purchasing this product. "
            "Request introductions through Afghan diplomatic missions or ACCI's "
            "trade promotion team."
        ),
        "resource_url": "https://www.trademap.org",
    })
    order += 1

    steps.append({
        "order": order,
        "title": "Attend relevant trade fairs",
        "description": (
            "Exhibit at or attend the major trade fair for this product category in "
            "the target market. ITC's Export Potential Map and sector associations "
            "can identify upcoming events."
        ),
        "resource_url": "https://exportpotential.intracen.org",
    })

    return steps
