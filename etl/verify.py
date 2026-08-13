"""
Data verification for the ETL pipeline.

Two independent layers of checks:
  1. Internal sanity checks -- fast, DB-only. Catch structural bugs (negative
     values, duplicate country codes, out-of-range scores, silently
     incomplete World Bank fetches) that don't require calling any API.
  2. Live API spot-checks -- slower. Re-fetch a small random sample of rows
     already stored in the DB fresh from Comtrade/World Bank, and diff the
     live value against what's stored, to catch transform bugs or staleness
     that internal checks alone can't see.

Usage:
    python -m etl.verify                     # internal checks only
    python -m etl.verify --spot-check         # also run live spot-checks
    python -m etl.verify --spot-check-n 10    # sample size (default 5)
"""

import argparse
import logging
import os
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# Ensure repo root is on sys.path when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Configure logging before importing etl.run, so this module's handler wins
# over etl.run's module-level basicConfig (which would otherwise also route
# these logs into etl_run.log and mix them with pipeline-run output).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

from etl import fetch  # noqa: E402


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return create_engine(url, pool_pre_ping=True)


# ── Internal sanity checks ────────────────────────────────────────────────────

def check_negative_values(engine) -> list[dict]:
    """Trade values/quantities should never be negative."""
    sql = text("""
        SELECT 'trade_flows' AS table_name, id, trade_value_usd, trade_quantity
        FROM trade_flows WHERE trade_value_usd < 0 OR trade_quantity < 0
        UNION ALL
        SELECT 'competitor_flows', id, trade_value_usd, trade_quantity
        FROM competitor_flows WHERE trade_value_usd < 0 OR trade_quantity < 0
    """)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def check_duplicate_supplier_codes(engine) -> list[dict]:
    """
    Same supplier name resolving to more than one supplier_code within the
    same (product, market, year) -- the signature of an unmapped country-code
    variant slipping through (e.g. India appearing as both '356' and '699').
    """
    sql = text("""
        SELECT product_id, market_code, year, supplier_name,
               COUNT(DISTINCT supplier_code) AS code_variants,
               array_agg(DISTINCT supplier_code) AS codes
        FROM competitor_flows
        GROUP BY product_id, market_code, year, supplier_name
        HAVING COUNT(DISTINCT supplier_code) > 1
    """)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def check_market_context_completeness(engine) -> dict:
    """Report what fraction of market_context rows are missing each field."""
    sql = text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE gdp_usd IS NULL) AS missing_gdp,
            COUNT(*) FILTER (WHERE gdp_per_capita_usd IS NULL) AS missing_gdp_per_capita,
            COUNT(*) FILTER (WHERE lpi_score IS NULL) AS missing_lpi,
            COUNT(*) FILTER (WHERE regulatory_quality IS NULL) AS missing_regulatory_quality,
            COUNT(*) FILTER (WHERE political_stability IS NULL) AS missing_political_stability
        FROM market_context
    """)
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return dict(row._mapping) if row else {}


def check_market_share_consistency(engine, tolerance_pct: float = 0.1) -> list[dict]:
    """market_share_pct should equal afg_export_value_usd / global_market_size_usd * 100."""
    sql = text("""
        SELECT id, product_id, market_code, computed_for_year,
               market_share_pct, afg_export_value_usd, global_market_size_usd,
               (afg_export_value_usd / global_market_size_usd * 100) AS recomputed
        FROM indicators
        WHERE afg_export_value_usd IS NOT NULL
          AND global_market_size_usd IS NOT NULL
          AND global_market_size_usd > 0
          AND market_share_pct IS NOT NULL
          AND ABS(market_share_pct - (afg_export_value_usd / global_market_size_usd * 100)) > :tol
    """)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql, {"tol": tolerance_pct})]


def check_score_bounds(engine) -> list[dict]:
    """opportunity_score and every sub-score must fall within [0, 100]."""
    score_cols = [
        "opportunity_score", "score_market_size", "score_market_growth",
        "score_market_quality", "score_price_competitiveness", "score_afg_foothold",
        "score_distance", "score_language", "score_fta", "score_tariff",
    ]
    conditions = " OR ".join(f"({c} < 0 OR {c} > 100)" for c in score_cols)
    sql = text(f"""
        SELECT id, product_id, market_code, computed_for_year, {", ".join(score_cols)}
        FROM indicators
        WHERE {conditions}
    """)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def check_product_coverage(engine) -> dict:
    """Which products have no indicator rows at all (fully empty from the ETL's perspective)."""
    sql = text("""
        SELECT p.name,
               EXISTS (SELECT 1 FROM indicators i WHERE i.product_id = p.id) AS has_indicators
        FROM products p
    """)
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(sql)]
    return {
        "covered": [r["name"] for r in rows if r["has_indicators"]],
        "missing": [r["name"] for r in rows if not r["has_indicators"]],
    }


def run_internal_checks(engine) -> bool:
    """Run all internal sanity checks and print a report. Returns True if all clean."""
    all_clean = True

    logger.info("── Negative/invalid values ──")
    neg = check_negative_values(engine)
    if neg:
        all_clean = False
        logger.warning(f"  {len(neg)} rows with negative trade_value_usd/trade_quantity")
        for r in neg[:10]:
            logger.warning(f"    {r}")
    else:
        logger.info("  clean")

    logger.info("── Duplicate supplier codes (same name, multiple codes) ──")
    dupes = check_duplicate_supplier_codes(engine)
    if dupes:
        all_clean = False
        logger.warning(f"  {len(dupes)} (product, market, year, supplier_name) groups with multiple supplier_codes")
        for r in dupes[:10]:
            logger.warning(f"    {r}")
    else:
        logger.info("  clean")

    logger.info("── market_context completeness ──")
    completeness = check_market_context_completeness(engine)
    total = completeness.get("total") or 0
    if total:
        for field in ("missing_gdp", "missing_gdp_per_capita", "missing_lpi",
                      "missing_regulatory_quality", "missing_political_stability"):
            n = completeness.get(field) or 0
            pct = n / total * 100
            log = logger.warning if pct > 20 else logger.info
            log(f"  {field}: {n}/{total} ({pct:.1f}%) missing")
    else:
        logger.warning("  market_context table is empty")

    logger.info("── market_share_pct consistency ──")
    mismatches = check_market_share_consistency(engine)
    if mismatches:
        all_clean = False
        logger.warning(f"  {len(mismatches)} indicator rows where market_share_pct doesn't match recomputed value")
        for r in mismatches[:10]:
            logger.warning(f"    {r}")
    else:
        logger.info("  clean")

    logger.info("── Score bounds [0, 100] ──")
    bad_scores = check_score_bounds(engine)
    if bad_scores:
        all_clean = False
        logger.warning(f"  {len(bad_scores)} indicator rows with a score outside [0, 100]")
        for r in bad_scores[:10]:
            logger.warning(f"    {r}")
    else:
        logger.info("  clean")

    logger.info("── Product coverage ──")
    coverage = check_product_coverage(engine)
    logger.info(f"  {len(coverage['covered'])} products have indicator data, {len(coverage['missing'])} do not")
    if coverage["missing"]:
        logger.info(f"    missing: {coverage['missing']}")

    return all_clean


# ── Live API spot-checks ──────────────────────────────────────────────────────

def spot_check_trade_flows(engine, n: int) -> list[dict]:
    """
    Sample n trade_flows rows, re-fetch the same (HS code, importer, year)
    from the live Comtrade API, and diff trade_value_usd against what's stored.
    """
    sql = text("""
        SELECT tf.id, tf.importer_code, tf.year, tf.trade_value_usd, p.hs_codes
        FROM trade_flows tf JOIN products p ON p.id = tf.product_id
        ORDER BY random() LIMIT :n
    """)
    with engine.connect() as conn:
        samples = [dict(r._mapping) for r in conn.execute(sql, {"n": n})]

    results = []
    for s in samples:
        importer, year = s["importer_code"], s["year"]
        stored = float(s["trade_value_usd"]) if s["trade_value_usd"] is not None else None

        try:
            live_total = 0.0
            for hs in s["hs_codes"]:
                df = fetch.fetch_mirror_exports(hs, [year])
                if df.empty:
                    continue
                match = df[df["importer_code"] == importer]
                live_total += float(pd.to_numeric(match["trade_value_usd"], errors="coerce").sum())
        except Exception as exc:
            logger.warning(f"  live re-fetch failed for trade_flow {s['id']} ({importer}/{year}): {exc}")
            results.append({
                "trade_flow_id": s["id"], "importer_code": importer, "year": year,
                "hs_codes": s["hs_codes"], "stored_value": stored, "live_value": None,
                "diff_pct": None, "error": str(exc),
            })
            continue

        diff_pct = abs(live_total - stored) / stored * 100 if stored else None
        results.append({
            "trade_flow_id": s["id"], "importer_code": importer, "year": year,
            "hs_codes": s["hs_codes"], "stored_value": stored, "live_value": live_total,
            "diff_pct": diff_pct,
        })
    return results


def spot_check_market_context(engine, n: int) -> list[dict]:
    """
    Sample n market_context rows, re-fetch GDP for the same (country, year)
    from the live World Bank API, and diff against what's stored.

    market_context.country_code is already ISO-3 alpha (the Comtrade-numeric
    mapping is only ever built in-memory for scoring, never written back to
    this table) -- so no translation is needed before querying the WB API.
    """
    sql = text("""
        SELECT id, country_code, year, gdp_usd
        FROM market_context WHERE gdp_usd IS NOT NULL
        ORDER BY random() LIMIT :n
    """)
    with engine.connect() as conn:
        samples = [dict(r._mapping) for r in conn.execute(sql, {"n": n})]

    results = []
    for s in samples:
        iso3 = s["country_code"]
        stored = float(s["gdp_usd"]) if s["gdp_usd"] is not None else None
        try:
            live_map = fetch._fetch_wb_indicator_chunk([iso3], "NY.GDP.MKTP.CD", [s["year"]])
        except Exception as exc:
            logger.warning(f"  live re-fetch failed for market_context {s['id']} ({iso3}/{s['year']}): {exc}")
            results.append({
                "market_context_id": s["id"], "country_code": s["country_code"], "iso3": iso3,
                "year": s["year"], "stored_gdp_usd": stored, "live_gdp_usd": None,
                "diff_pct": None, "error": str(exc),
            })
            continue
        live_value = live_map.get(iso3, {}).get(s["year"])

        diff_pct = abs(live_value - stored) / stored * 100 if (stored and live_value) else None
        results.append({
            "market_context_id": s["id"], "country_code": s["country_code"], "iso3": iso3,
            "year": s["year"], "stored_gdp_usd": stored, "live_gdp_usd": live_value,
            "diff_pct": diff_pct,
        })
    return results


def run_spot_checks(engine, n: int) -> bool:
    """Run live API spot-checks and print a report. Returns True if all within tolerance."""
    all_clean = True

    logger.info(f"── Live spot-check: {n} trade_flows rows vs Comtrade ──")
    for r in spot_check_trade_flows(engine, n):
        if r["diff_pct"] is None or r["diff_pct"] > 1.0:
            all_clean = False
            logger.warning(f"  MISMATCH {r}")
        else:
            logger.info(
                f"  OK  importer={r['importer_code']} year={r['year']} "
                f"stored=${r['stored_value']:,.0f} live=${r['live_value']:,.0f} "
                f"(diff {r['diff_pct']:.2f}%)"
            )

    logger.info(f"── Live spot-check: {n} market_context rows vs World Bank ──")
    for r in spot_check_market_context(engine, n):
        if r["diff_pct"] is None or r["diff_pct"] > 1.0:
            all_clean = False
            logger.warning(f"  MISMATCH {r}")
        else:
            logger.info(
                f"  OK  country={r['country_code']} year={r['year']} "
                f"stored=${r['stored_gdp_usd']:,.0f} live=${r['live_gdp_usd']:,.0f} "
                f"(diff {r['diff_pct']:.2f}%)"
            )

    return all_clean


def main():
    parser = argparse.ArgumentParser(description="Verify ETL data correctness")
    parser.add_argument(
        "--spot-check", action="store_true",
        help="Also re-fetch a live sample from Comtrade/World Bank and diff against stored data",
    )
    parser.add_argument(
        "--spot-check-n", type=int, default=5,
        help="Sample size for spot-checks (default 5)",
    )
    args = parser.parse_args()

    engine = _engine()

    logger.info("=" * 60)
    logger.info("Internal sanity checks")
    logger.info("=" * 60)
    internal_clean = run_internal_checks(engine)

    spot_clean = True
    if args.spot_check:
        logger.info("=" * 60)
        logger.info("Live API spot-checks")
        logger.info("=" * 60)
        spot_clean = run_spot_checks(engine, args.spot_check_n)

    logger.info("=" * 60)
    if internal_clean and spot_clean:
        logger.info("All checks passed")
    else:
        logger.warning("Some checks flagged issues -- see above")
        sys.exit(1)


if __name__ == "__main__":
    main()
