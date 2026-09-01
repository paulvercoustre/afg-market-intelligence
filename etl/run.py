"""
ETL orchestrator — runs the full pipeline for all products in config.PRODUCTS.

Usage:
    python -m etl.run                   # full run
    python -m etl.run --products Saffron "Dried Grapes (Raisins)"
    python -m etl.run --dry-run         # fetch & transform only, skip DB writes
"""

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

# Ensure repo root is on sys.path when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.country_names import resolve_country_name
from config import NUMERIC_TO_ISO3, PRODUCTS, TOP_N_MARKETS, YEARS
from etl import fetch, load, transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("etl_run.log"),
    ],
)
logger = logging.getLogger(__name__)

# Products are fetched from Comtrade concurrently: each product's mirror +
# global-import calls are independent, and Comtrade's own client hardcodes a
# 120s timeout per HTTP attempt with no way to shorten it (see etl/fetch.py),
# so one slow/stuck product no longer blocks the other 32 behind it serially.
# Kept modest (not e.g. 8+) since higher concurrency means more simultaneous
# load against a subscription-key-rate-limited API and against WITS's own
# internal thread pool if tariffs aren't skipped.
_PRODUCT_MAX_WORKERS = 3


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return create_engine(url, pool_pre_ping=True)


def _all_market_codes(global_df: pd.DataFrame) -> list[str]:
    """Return all unique reporter codes appearing in global import data."""
    if global_df.empty or "reporterCode" not in global_df.columns:
        return []
    codes = global_df["reporterCode"].dropna().unique().tolist()
    # Exclude aggregates (code '0' = World) and Afghanistan itself
    return [str(c) for c in codes if str(c) not in ("0", "4")]


def _top_market_codes(mirror_df: pd.DataFrame, global_df: pd.DataFrame, top_n: int) -> list[str]:
    """Return codes for the top N markets by latest-year total import value."""
    if global_df.empty:
        return []
    latest_year = max(YEARS)
    world_totals = global_df[
        (global_df["partnerCode"] == "0") & (global_df["year"] == latest_year)
    ].copy()
    world_totals["primaryValue"] = pd.to_numeric(world_totals["primaryValue"], errors="coerce")
    top = (
        world_totals.groupby("reporterCode")["primaryValue"]
        .sum()
        .nlargest(top_n)
        .index.tolist()
    )
    return [str(c) for c in top]


def _market_sizes_by_code(global_df: pd.DataFrame, year: int) -> dict[str, float]:
    """Return {market_code: total_import_usd} for partnerCode==0 at the given year."""
    if global_df.empty:
        return {}
    sub = global_df[(global_df["partnerCode"] == "0") & (global_df["year"] == year)].copy()
    sub["primaryValue"] = pd.to_numeric(sub["primaryValue"], errors="coerce")
    return dict(
        sub.groupby("reporterCode")["primaryValue"]
        .sum()
        .items()
    )


def run_product(
    engine,
    product_name: str,
    cfg: dict,
    dry_run: bool,
    market_context: dict[str, dict],  # {country_code: {year: {field: value}}}
    skip_tariffs: bool = False,
    refresh_cache: bool = False,
) -> dict:
    hs_codes = cfg["codes"]
    logger.info(f"▶  {product_name}  ({', '.join(hs_codes)})")
    errors = []
    # Products run concurrently (see _PRODUCT_MAX_WORKERS), so every log line
    # below is prefixed with the product name -- without it, interleaved
    # output from multiple products would be unreadable.
    tag = f"[{product_name}]"

    # 1. Upsert product row, get its id
    product_id = None
    if not dry_run:
        product_id = load.upsert_product(
            engine,
            name=product_name,
            category=cfg.get("category", "Other"),
            hs_codes=hs_codes,
            description=cfg.get("description", ""),
        )

    # 2. Fetch mirror exports (Afghanistan's side)
    mirror_frames = []
    for hs in hs_codes:
        try:
            df = fetch.fetch_mirror_exports(hs, YEARS)
            if not df.empty:
                mirror_frames.append(df)
        except Exception as e:
            logger.error(f"  {tag} fetch_mirror_exports failed for HS {hs}: {e}")
            errors.append({"hs": hs, "stage": "fetch_mirror", "error": str(e)})

    mirror_df = pd.concat(mirror_frames, ignore_index=True) if mirror_frames else pd.DataFrame()

    # 3. Fetch global import picture (one call per HS code)
    global_frames = []
    for hs in hs_codes:
        try:
            df = fetch.fetch_global_imports(hs, YEARS)
            if not df.empty:
                global_frames.append(df)
        except Exception as e:
            logger.error(f"  {tag} fetch_global_imports failed for HS {hs}: {e}")
            errors.append({"hs": hs, "stage": "fetch_global", "error": str(e)})

    global_df = pd.concat(global_frames, ignore_index=True) if global_frames else pd.DataFrame()

    if mirror_df.empty and global_df.empty:
        logger.warning(f"  {tag} No data fetched — skipping")
        return {"product": product_name, "status": "no_data", "errors": errors}

    # 4. Determine markets: ALL markets for scoring, top N for competitor flows
    all_codes = _all_market_codes(global_df)
    top_codes = _top_market_codes(mirror_df, global_df, TOP_N_MARKETS)
    logger.info(f"  {tag} Markets for scoring: {len(all_codes)}, top {TOP_N_MARKETS} for detail: {top_codes}")

    if dry_run:
        logger.info(f"  {tag} [dry-run] Skipping DB writes")
        return {"product": product_name, "status": "dry_run", "errors": errors}

    # 5. Upsert market rows for all scored markets
    for code in all_codes:
        name = _resolve_market_name(global_df, code)
        load.upsert_market(engine, code, name)

    # 6. Transform + load trade flows
    flow_rows = transform.to_trade_flows(mirror_df, product_id)
    n_flows = load.bulk_upsert_trade_flows(engine, flow_rows)
    logger.info(f"  {tag} Upserted {n_flows} trade_flow rows")

    # 7. Transform + load competitor flows (top markets only)
    comp_rows = transform.to_competitor_flows(global_df, product_id, top_codes)
    n_comp = load.bulk_upsert_competitor_flows(engine, comp_rows)
    logger.info(f"  {tag} Upserted {n_comp} competitor_flow rows")

    # 8. Compute indicators for ALL markets
    latest_year = max(YEARS)
    all_market_sizes = _market_sizes_by_code(global_df, latest_year)
    ind_rows = transform.compute_indicators(product_id, all_codes, mirror_df, global_df, YEARS)

    # 9. Fetch tariffs for the markets we'll score
    if skip_tariffs:
        tariffs = load.load_tariffs_for_product(engine, product_id)
        logger.info(f"  {tag} Reusing {len(tariffs)} previously-stored tariff rates (--skip-tariffs)")
    else:
        tariffs = {}
        try:
            tariffs = _fetch_tariffs_for_product(all_codes, hs_codes, YEARS, refresh_cache=refresh_cache)
            logger.info(f"  {tag} Fetched tariff data for {len(tariffs)} markets")
        except Exception as exc:
            logger.warning(f"  {tag} Tariff fetch failed: {exc} — falling back to previously-stored tariffs")
            errors.append({"hs": ",".join(hs_codes), "stage": "fetch_tariffs", "error": str(exc)})
            tariffs = load.load_tariffs_for_product(engine, product_id)

    # 10. Enrich with opportunity scores
    ind_rows = transform.enrich_indicators_with_scores(
        ind_rows, market_context, all_market_sizes, tariffs=tariffs,
    )

    n_ind = load.bulk_upsert_indicators(engine, ind_rows)
    logger.info(f"  {tag} Upserted {n_ind} indicator rows (all markets, with scores)")

    return {"product": product_name, "status": "success", "errors": errors}


def _fetch_tariffs_for_product(market_codes: list[str], hs_codes: list[str],
                               years: list[int], refresh_cache: bool = False) -> dict[str, dict]:
    """
    Fetch tariff data for the given markets and HS codes.
    Returns {market_numeric_code: {'rate': float, 'indicator': str, 'year': int}}
    where rate is averaged across the product's HS codes. 'year' is the actual
    year WITS reported the rate for (see fetch.fetch_tariff_rates) -- since
    _tariff_rows_for_market stops at the first year with any data, every HS
    code returned for a given market shares the same year, so taking the last
    one seen (like 'indicator' below) is safe.
    """
    rows = fetch.fetch_tariff_rates(market_codes, hs_codes, years, refresh_cache=refresh_cache)

    # Aggregate per market: average rate across the product's HS codes.
    by_market: dict[str, list[float]] = {}
    indicator_by_market: dict[str, str] = {}
    year_by_market: dict[str, int] = {}
    for r in rows:
        code = r["market_code"]
        by_market.setdefault(code, []).append(r["tariff_rate_pct"])
        indicator_by_market[code] = r["indicator"]
        year_by_market[code] = r["year"]

    return {
        code: {
            "rate": sum(rates) / len(rates),
            "indicator": indicator_by_market.get(code),
            "year": year_by_market.get(code),
        }
        for code, rates in by_market.items()
    }


def _resolve_market_name(global_df: pd.DataFrame, code: str) -> str | None:
    if "reporterDesc" in global_df.columns:
        match = global_df[global_df["reporterCode"] == code]["reporterDesc"]
        if not match.empty:
            name = resolve_country_name(code, match.iloc[0])
            if name:
                return name
    if "reporterISO" in global_df.columns:
        match = global_df[global_df["reporterCode"] == code]["reporterISO"]
        if not match.empty:
            name = resolve_country_name(code, match.iloc[0])
            if name:
                return name
    return resolve_country_name(code)


def _build_market_context(wb_rows: list[dict]) -> dict[str, dict[int, dict]]:
    """
    Restructure flat WB rows (keyed by ISO-3) into the shape scoring expects:
    {comtrade_numeric_code: {year: {field: value}}}.

    The remap to Comtrade numeric codes is essential — transform.py looks up
    context by the numeric market_code that appears in trade data.
    """
    ctx_iso3: dict[str, dict[int, dict]] = {}
    for row in wb_rows:
        cc = row["country_code"]
        yr = row["year"]
        ctx_iso3.setdefault(cc, {})[yr] = {
            k: _to_float(row[k])
            for k in ("gdp_usd", "gdp_per_capita_usd", "lpi_score",
                      "regulatory_quality", "political_stability")
        }

    return {
        numeric: ctx_iso3[iso3]
        for numeric, iso3 in NUMERIC_TO_ISO3.items()
        if iso3 in ctx_iso3
    }


def _to_float(v) -> float | None:
    return None if v is None else float(v)


def main():
    parser = argparse.ArgumentParser(description="AFG Market Intelligence ETL")
    parser.add_argument(
        "--products", nargs="+", metavar="NAME",
        help="Run only these products (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and transform but do not write to DB",
    )
    parser.add_argument(
        "--skip-world-bank", action="store_true",
        help="Skip World Bank indicator fetch (use existing market_context rows)",
    )
    parser.add_argument(
        "--skip-tariffs", action="store_true",
        help="Skip WITS tariff fetch (faster runs; tariff scores default to neutral)",
    )
    parser.add_argument(
        "--refresh-cache", action="store_true",
        help="Bypass the on-disk WITS tariff cache and force a fresh fetch, "
             "regardless of cache age (normally cache entries auto-expire after 7 days)",
    )
    args = parser.parse_args()

    target = args.products or list(PRODUCTS.keys())
    unknown = [p for p in target if p not in PRODUCTS]
    if unknown:
        logger.error(f"Unknown products: {unknown}")
        sys.exit(1)

    engine = None if args.dry_run else _engine() #database engine

    # ── Phase A: World Bank fetch (once per run, across all markets) ──────────
    market_context: dict[str, dict[int, dict]] = {}

    if not args.dry_run:
        if args.skip_world_bank:
            # Reuse whatever a previous run stored in market_context.
            wb_rows = load.load_market_context(engine)
            market_context = _build_market_context(wb_rows)
            logger.info(f"Loaded {len(wb_rows)} existing market_context rows (--skip-world-bank)")
        else:
            # Map Comtrade numeric codes to ISO-3 alpha for the WB API
            # (WB accepts ISO-3 alpha; Comtrade uses numeric codes).
            #
            # The set of countries to fetch is driven directly by
            # NUMERIC_TO_ISO3's own keys -- it must NOT be filtered through an
            # unrelated table like DISTANCE_FROM_KABUL_KM (a prior version did
            # exactly that): that table is maintained for a different scoring
            # dimension entirely and has its own, different set of gaps, so
            # gating World Bank fetches on it silently dropped every country
            # present in one table but not the other, regardless of whether WB
            # data was actually available for them.
            iso3_codes = list(NUMERIC_TO_ISO3.values())

            logger.info(f"Fetching World Bank indicators for {len(iso3_codes)} countries…")
            try:
                wb_rows = fetch.fetch_world_bank_indicators(iso3_codes, YEARS)
                market_context = _build_market_context(wb_rows)
                n_ctx = load.bulk_upsert_market_context(engine, wb_rows)
                logger.info(f"Upserted {n_ctx} market_context rows")
            except Exception as exc:
                logger.error(f"World Bank fetch failed: {exc} — continuing without WB data")

    # ── Phase B: Per-product ETL ──────────────────────────────────────────────
    # Products are independent (their own HS codes, own DB rows), so they run
    # concurrently -- see _PRODUCT_MAX_WORKERS for why the pool is kept small.
    results = []
    all_errors = []
    with ThreadPoolExecutor(max_workers=_PRODUCT_MAX_WORKERS) as pool:
        futures = {
            pool.submit(run_product, engine, name, PRODUCTS[name], dry_run=args.dry_run,
                       market_context=market_context, skip_tariffs=args.skip_tariffs,
                       refresh_cache=args.refresh_cache): name
            for name in target
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error(f"[{name}] run_product crashed: {exc}")
                result = {
                    "product": name, "status": "error",
                    "errors": [{"hs": None, "stage": "run_product", "error": str(exc)}],
                }
            results.append(result)
            all_errors.extend(result.get("errors", []))

    successes = sum(1 for r in results if r["status"] == "success")
    logger.info(f"\n{'─'*60}")
    logger.info(f"ETL complete: {successes}/{len(results)} products succeeded")
    if all_errors:
        logger.warning(f"  {len(all_errors)} errors logged (see etl_run.log for details)")

    if engine and not args.dry_run:
        status = "success" if not all_errors else "partial"
        load.log_pipeline_run(engine, status, successes, all_errors)


if __name__ == "__main__":
    main()
