"""
Transform raw Comtrade API responses into DB-ready row shapes.

Each public function returns a list of dicts that map 1-to-1 to a DB table.
This keeps all column-name translation in one place, decoupled from both the
API client and the DB loader.
"""

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from backend.country_names import resolve_country_name
from config import (
    DISTANCE_FROM_KABUL_KM,
    LANGUAGE_SIMILARITY,
    LANGUAGE_SIMILARITY_DEFAULT,
    MAX_GREAT_CIRCLE_DISTANCE_KM,
    OPPORTUNITY_SCORE_WEIGHTS,
    PRICE_COMPETITIVENESS,
    TARIFF_SCORE_PER_PCT,
)

logger = logging.getLogger(__name__)


# ── Trade flows (Afghanistan mirror exports per importer per year) ─────────────

def to_trade_flows(mirror_df: pd.DataFrame, product_id: int) -> list[dict]:
    """
    Convert normalised mirror-export data to trade_flows DB rows.

    mirror_df columns (from fetch.fetch_mirror_exports):
        hs_code, year, importer_code, importer_name,
        trade_value_usd, trade_quantity, quantity_unit, net_weight_kg
    """
    rows = []
    for _, r in mirror_df.iterrows():
        rows.append({
            "product_id": product_id,
            "importer_code": str(r["importer_code"]),
            "importer_name": r.get("importer_name"),
            "year": int(r["year"]),
            "trade_value_usd": _float_or_none(r.get("trade_value_usd")),
            "trade_quantity": _float_or_none(r.get("trade_quantity")),
            "quantity_unit": r.get("quantity_unit"),
            "net_weight_kg": _float_or_none(r.get("net_weight_kg")),
        })
    return rows


# ── Competitor flows (all suppliers to each market) ───────────────────────────

def to_competitor_flows(global_df: pd.DataFrame, product_id: int, market_codes: list[str]) -> list[dict]:
    """
    Extract competitor (supplier) rows for the top markets from the global import DataFrame.

    global_df is the raw response from fetch.fetch_global_imports — it contains
    all reporter × partner combinations. We exclude partnerCode='0' (world aggregate)
    to get actual supplier relationships.

    Only rows where reporterCode is in market_codes are included.
    """
    if global_df.empty:
        return []

    supplier_mask = (
        (global_df["partnerCode"] != "0")
        & (global_df["reporterCode"].isin(market_codes))
    )
    suppliers = global_df[supplier_mask].copy()

    if suppliers.empty:
        return []

    rows = []
    for _, r in suppliers.iterrows():
        supplier_name = resolve_country_name(
            r["partnerCode"],
            r.get("partnerDesc") or r.get("partnerISO"),
        )
        qty = _float_or_none(r.get("qty") if "qty" in r.index else None)
        if qty is None and "netWgt" in r.index:
            qty = _float_or_none(r.get("netWgt"))

        rows.append({
            "product_id": product_id,
            "market_code": str(r["reporterCode"]),
            "year": int(r["year"]),
            "supplier_code": str(r["partnerCode"]),
            "supplier_name": supplier_name,
            "trade_value_usd": _float_or_none(r.get("primaryValue")),
            "trade_quantity": qty,
        })
    return rows


# ── Indicators (one row per product × market, latest year) ────────────────────

def compute_indicators(
    product_id: int,
    market_codes: list[str],
    mirror_df: pd.DataFrame,
    global_df: pd.DataFrame,
    years: list[int],
) -> list[dict]:
    """
    Compute all indicators for each (product, market) pair.

    Returns a list of dicts mapping to the indicators DB table.
    """
    if mirror_df.empty or global_df.empty:
        return []

    latest_year = max(years)
    rows = []

    # World-total imports per market per year (partnerCode == '0')
    world_totals = global_df[global_df["partnerCode"] == "0"].copy()
    world_totals["primaryValue"] = pd.to_numeric(world_totals["primaryValue"], errors="coerce")

    for market_code in market_codes:
        afg_to_market = mirror_df[mirror_df["importer_code"] == market_code].copy()
        if afg_to_market.empty:
            continue

        market_world = world_totals[world_totals["reporterCode"] == market_code].copy()

        # Trade fields target this market's own most recent reported year,
        # at or before latest_year -- falling back the same way
        # _latest_wb_context() already does for World Bank fields, so a
        # market whose latest_year submission hasn't landed at Comtrade yet
        # reuses its own last known year instead of coming back empty (and
        # dragging the score down for a reason that has nothing to do with
        # the market's actual attractiveness).
        trade_data_year = _resolve_trade_year(market_world, afg_to_market, latest_year)

        # Global market size (trade_data_year)
        global_market_size = _sum_year(market_world, "primaryValue", trade_data_year)

        # Afghanistan's export value to this market (trade_data_year)
        afg_value_latest = _sum_year(afg_to_market, "trade_value_usd", trade_data_year)

        # Afghanistan's own most recent export year to this market, independent
        # of trade_data_year -- see _resolve_afg_last_export() docstring.
        afg_last_export_year, afg_last_export_value = _resolve_afg_last_export(
            afg_to_market, latest_year
        )

        # Growth metrics
        growth = _growth_metrics(afg_to_market, years)

        # Market share
        market_share_pct = (
            (afg_value_latest / global_market_size * 100)
            if afg_value_latest is not None and global_market_size and global_market_size > 0
            else None
        )

        # Afghanistan's rank among all suppliers to this market
        afg_rank = _afg_rank(global_df, market_code, afg_value_latest, trade_data_year)

        # Unit price
        unit_price = _unit_price(afg_to_market, trade_data_year)

        # Market average price and competitiveness
        market_avg_price, price_vs_market_pct, competitiveness = _price_competitiveness(
            global_df, market_code, unit_price, trade_data_year
        )

        rows.append({
            "product_id": product_id,
            "market_code": market_code,
            "computed_for_year": latest_year,
            "trade_data_year": trade_data_year,
            "global_market_size_usd": _float_or_none(global_market_size),
            "afg_export_value_usd": _float_or_none(afg_value_latest),
            "afg_last_export_year": afg_last_export_year,
            "afg_last_export_value_usd": _float_or_none(afg_last_export_value),
            "yoy_growth_pct": _float_or_none(growth["yoy"]),
            "cagr_pct": _float_or_none(growth["cagr"]),
            "absolute_growth_usd": _float_or_none(growth["absolute"]),
            "growth_pct": _float_or_none(growth["pct"]),
            "first_year": growth["first_year"],
            "last_year": growth["last_year"],
            "market_share_pct": _float_or_none(market_share_pct),
            "afg_supplier_rank": afg_rank,
            "unit_price_usd": _float_or_none(unit_price),
            "market_avg_price_usd": _float_or_none(market_avg_price),
            "price_vs_market_pct": _float_or_none(price_vs_market_pct),
            "price_competitiveness": competitiveness,
        })

    return rows


# ── Private helpers ───────────────────────────────────────────────────────────

def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _resolve_trade_year(
    market_world: pd.DataFrame, afg_to_market: pd.DataFrame, up_to_year: int
) -> int | None:
    """
    The most recent year <= up_to_year that this market has *any* reported
    data for -- its own global-import totals or Afghanistan's exports to it.
    Comtrade reporters submit a full year's trade lines at once, so "this
    market's global totals exist for year Y" is a reliable signal that Y is
    a real reporting year for it, not just a year we happened to ask about.
    """
    years_with_data: set[int] = set()
    if not market_world.empty:
        years_with_data |= set(pd.to_numeric(market_world["year"], errors="coerce").dropna().astype(int))
    if not afg_to_market.empty:
        years_with_data |= set(pd.to_numeric(afg_to_market["year"], errors="coerce").dropna().astype(int))
    eligible = [y for y in years_with_data if y <= up_to_year]
    return max(eligible) if eligible else None


# A country genuinely halting Afghan imports is real signal worth showing as a
# zero for the current year (see _resolve_trade_year above) -- but reusing an
# arbitrarily old year to paper over that would misrepresent Afghanistan's
# *current* presence. This floor bounds how far back "last known export year"
# is allowed to look, so a market with, say, a single small shipment in 2019
# and nothing since doesn't get displayed as if it were still active.
AFG_LAST_EXPORT_FLOOR_YEAR = 2022


def _resolve_afg_last_export(
    afg_to_market: pd.DataFrame, up_to_year: int, floor_year: int = AFG_LAST_EXPORT_FLOOR_YEAR
) -> tuple[int | None, float | None]:
    """
    The most recent year (floor_year <= year <= up_to_year) that Afghanistan
    has any recorded export value to this market, and the value for that year.

    Independent of trade_data_year: trade_data_year anchors global_market_size_usd
    and afg_export_value_usd to the market's own current reporting year so
    market_share_pct/afg_supplier_rank stay same-year, apples-to-apples
    comparisons -- including a genuine zero when Afghanistan simply isn't in
    that year's partner breakdown. This instead answers "when did Afghanistan
    last actually show up here at all," purely for display, so a genuine
    current-year zero isn't shown to the user as if no data existed at all.
    """
    if afg_to_market.empty:
        return None, None
    yearly = afg_to_market.groupby("year")["trade_value_usd"].sum().reset_index()
    yearly["year"] = pd.to_numeric(yearly["year"], errors="coerce")
    yearly = yearly.dropna(subset=["year"])
    yearly["year"] = yearly["year"].astype(int)
    eligible = yearly[
        (yearly["year"] >= floor_year)
        & (yearly["year"] <= up_to_year)
        & (yearly["trade_value_usd"] > 0)
    ]
    if eligible.empty:
        return None, None
    row = eligible.sort_values("year").iloc[-1]
    return int(row["year"]), float(row["trade_value_usd"])


def _sum_year(df: pd.DataFrame, col: str, year: int) -> float | None:
    sub = df[df["year"] == year]
    if sub.empty or col not in sub.columns:
        return None
    total = pd.to_numeric(sub[col], errors="coerce").sum()
    return float(total) if total > 0 else None



# indicators.{yoy_growth_pct,cagr_pct,growth_pct} are NUMERIC(10,4) -- a growth
# rate off a near-zero prior-year base can produce a percentage in the
# millions, which overflows that column and (since these rows are upserted in
# a single multi-row INSERT) fails the whole product's batch. Such a number
# isn't meaningful growth data anyway, so treat it as undefined rather than
# storing a nonsensical figure.
_MAX_PCT_MAGNITUDE = 999_999.0


def _safe_pct(value: float | None) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value if abs(value) <= _MAX_PCT_MAGNITUDE else None


def _growth_metrics(afg_df: pd.DataFrame, years: list[int]) -> dict:
    empty = {"yoy": None, "cagr": None, "absolute": None, "pct": None,
             "first_year": None, "last_year": None}
    yearly = (
        afg_df.groupby("year")["trade_value_usd"]
        .sum()
        .reset_index()
        .sort_values("year")
    )
    yearly = yearly[yearly["year"].isin(years)]
    if len(yearly) < 2:
        return empty

    first_year = int(yearly["year"].iloc[0])
    last_year = int(yearly["year"].iloc[-1])
    first_val = float(yearly["trade_value_usd"].iloc[0])
    last_val = float(yearly["trade_value_usd"].iloc[-1])

    yoy = None
    if len(yearly) >= 2:
        prev_val = float(yearly["trade_value_usd"].iloc[-2])
        if prev_val > 0:
            yoy = (last_val - prev_val) / prev_val * 100

    n = last_year - first_year
    cagr = None
    if n > 0 and first_val > 0:
        cagr = ((last_val / first_val) ** (1 / n) - 1) * 100

    absolute = last_val - first_val
    pct = (absolute / first_val * 100) if first_val > 0 else None

    return {
        "yoy": _safe_pct(yoy), "cagr": _safe_pct(cagr), "absolute": absolute,
        "pct": _safe_pct(pct), "first_year": first_year, "last_year": last_year,
    }


def _afg_rank(global_df: pd.DataFrame, market_code: str,
              afg_value: float | None, year: int) -> int | None:
    if afg_value is None:
        return None
    suppliers = global_df[
        (global_df["reporterCode"] == market_code)
        & (global_df["partnerCode"] != "0")
        & (global_df["year"] == year)
    ].copy()
    if suppliers.empty:
        return None
    suppliers["_val"] = pd.to_numeric(suppliers["primaryValue"], errors="coerce")
    higher = (suppliers["_val"] > afg_value).sum()
    return int(higher) + 1


def _unit_price(afg_df: pd.DataFrame, year: int) -> float | None:
    sub = afg_df[afg_df["year"] == year]
    if sub.empty:
        return None
    value = pd.to_numeric(sub["trade_value_usd"], errors="coerce").sum()
    qty = pd.to_numeric(sub.get("trade_quantity", pd.Series(dtype=float)), errors="coerce").sum()
    if qty and qty > 0:
        return float(value / qty)
    # Fall back to net weight
    wt = pd.to_numeric(sub.get("net_weight_kg", pd.Series(dtype=float)), errors="coerce").sum()
    if wt and wt > 0:
        return float(value / wt)
    return None


def _price_competitiveness(
    global_df: pd.DataFrame,
    market_code: str,
    afg_price: float | None,
    year: int,
) -> tuple[float | None, float | None, str | None]:
    if afg_price is None or global_df.empty:
        return None, None, None

    suppliers = global_df[
        (global_df["reporterCode"] == market_code)
        & (global_df["partnerCode"] != "0")
        & (global_df["year"] == year)
    ].copy()
    if suppliers.empty:
        return None, None, None

    suppliers["_val"] = pd.to_numeric(suppliers["primaryValue"], errors="coerce")
    suppliers["_qty"] = pd.to_numeric(
        suppliers.get("qty", pd.Series(dtype=float)), errors="coerce"
    )
    suppliers["_price"] = suppliers.apply(
        lambda r: r["_val"] / r["_qty"] if r["_qty"] > 0 else None, axis=1
    )
    valid = suppliers["_price"].dropna()
    if valid.empty:
        return None, None, None

    market_avg = float(valid.mean())
    pct_diff = (afg_price - market_avg) / market_avg * 100 if market_avg > 0 else None

    label = None
    if pct_diff is not None:
        thresholds = PRICE_COMPETITIVENESS
        if pct_diff < thresholds["highly_competitive"]:
            label = "Highly Competitive"
        elif pct_diff < thresholds["competitive"]:
            label = "Competitive"
        elif pct_diff < thresholds["average"]:
            label = "Average"
        else:
            label = "Above Market"

    return market_avg, pct_diff, label


# ── Opportunity score ─────────────────────────────────────────────────────────

def enrich_indicators_with_scores(
    indicator_rows: list[dict],
    market_context: dict[str, dict],  # {country_code: {year: {field: value}}}
    all_market_sizes: dict[str, float],  # {market_code: global_market_size_usd latest year}
    tariffs: dict[str, dict] | None = None,  # {market_code (M49): {'rate': float, 'indicator': str}}
) -> list[dict]:
    """
    Attach opportunity scores to already-computed indicator rows.

    Each row in indicator_rows is mutated in place (new keys added) and returned.
    market_context is keyed by Comtrade numeric country code → year → field.
    all_market_sizes provides cross-market normalisation for the size dimension.
    tariffs is keyed by Comtrade numeric code → {rate, indicator}.
    """
    if not indicator_rows:
        return indicator_rows

    weights = OPPORTUNITY_SCORE_WEIGHTS
    tariffs = tariffs or {}

    # Pre-compute log-normalised market size across all markets for this product
    sizes = [v for v in all_market_sizes.values() if v and v > 0]
    log_max = math.log1p(max(sizes)) if sizes else 1.0

    for row in indicator_rows:
        mc = row["market_code"]
        year = row["computed_for_year"]

        # ── Static lookups ────────────────────────────────────────────────────
        dist_km = DISTANCE_FROM_KABUL_KM.get(mc)
        lang = LANGUAGE_SIMILARITY.get(mc, LANGUAGE_SIMILARITY_DEFAULT)

        row["distance_km"] = dist_km
        row["language_similarity"] = lang

        # ── World Bank context (latest available year ≤ computed year) ────────
        ctx_by_year = market_context.get(mc, {})
        ctx = _latest_wb_context(ctx_by_year, year)
        row["gdp_per_capita_usd"] = ctx.get("gdp_per_capita_usd")
        row["lpi_score"] = ctx.get("lpi_score")
        row["lpi_score_year"] = ctx.get("lpi_score_year")
        row["regulatory_quality"] = ctx.get("regulatory_quality")
        row["regulatory_quality_year"] = ctx.get("regulatory_quality_year")
        row["political_stability"] = ctx.get("political_stability")
        row["political_stability_year"] = ctx.get("political_stability_year")

        # ── Tariff (WITS) ─────────────────────────────────────────────────────
        tariff_info = tariffs.get(mc) or {}
        tariff_rate = tariff_info.get("rate")
        row["tariff_rate_pct"] = tariff_rate
        row["tariff_indicator"] = tariff_info.get("indicator")
        row["tariff_year"] = tariff_info.get("year")

        # 'AHS' means WITS has an Afghanistan-specific applied-tariff record on
        # file for this reporter (partner=004, vs the generic partner=000 MFN
        # rate) -- a real signal of differentiated trade treatment, sourced
        # live from the same WITS fetch as tariff_rate_pct rather than a
        # hand-maintained "which FTAs is Afghanistan in" dict. It doesn't
        # guarantee this specific product's AHS rate is lower than MFN (we
        # only fetch MFN as a fallback when AHS is unavailable, not always
        # both, so there's nothing to compare against for AHS rows) -- but
        # that actual rate, whichever indicator it came from, is already
        # fully priced into score_tariff below.
        has_fta = tariff_info.get("indicator") == "AHS"
        row["has_fta"] = has_fta

        # ── Dimension scores (0–100) ─────────────────────────────────────────
        s_size = _score_market_size(row.get("global_market_size_usd"), log_max)
        s_growth = _score_growth(row.get("cagr_pct"))
        s_quality = _score_market_quality(ctx)
        s_price = _score_price(row.get("price_competitiveness"))
        s_foothold = _score_foothold(
            row.get("afg_export_value_usd"), row.get("afg_last_export_value_usd")
        )
        s_distance = _score_distance(dist_km)
        s_language = lang * 100
        s_fta = 100.0 if has_fta else 0.0
        s_tariff = _score_tariff(tariff_rate)

        row["score_market_size"] = round(s_size, 2)
        row["score_market_growth"] = round(s_growth, 2)
        row["score_market_quality"] = round(s_quality, 2)
        row["score_price_competitiveness"] = round(s_price, 2)
        row["score_afg_foothold"] = round(s_foothold, 2)
        row["score_distance"] = round(s_distance, 2)
        row["score_language"] = round(s_language, 2)
        row["score_fta"] = round(s_fta, 2)
        row["score_tariff"] = round(s_tariff, 2)

        # score_fta/has_fta are still computed and stored above for every row
        # (in case WITS's AFG-specific tariff coverage improves), but not
        # weighted into the composite -- see config.py's OPPORTUNITY_SCORE_WEIGHTS
        # comment for why (WITS has_fta is currently False for 100% of rows).
        composite = (
            s_size * weights["market_size"]
            + s_growth * weights["market_growth"]
            + s_quality * weights["market_quality"]
            + s_price * weights["price_competitiveness"]
            + s_tariff * weights["tariff"]
            + s_foothold * weights["afg_foothold"]
            + s_distance * weights["distance"]
            + s_language * weights["language"]
        )
        row["opportunity_score"] = round(composite, 2)

    return indicator_rows


def _latest_wb_context(ctx_by_year: dict[int, dict], up_to_year: int) -> dict:
    """
    Return the most recent World Bank value per field at or before up_to_year.

    Fields are resolved independently because indicators refresh on different
    cycles — e.g. the LPI survey is triennial, so the latest year's record may
    have GDP but a null LPI while an earlier year has the survey value.

    Also returns a '{field}_year' entry alongside each resolved field, giving
    the actual year that value came from -- without it, a caller can't tell a
    fresh value from one that's several years stale (the same problem
    tariff_year solves for WITS rates).
    """
    eligible_years = sorted((yr for yr in ctx_by_year if yr <= up_to_year), reverse=True)
    merged: dict = {}
    for yr in eligible_years:
        for field, value in ctx_by_year[yr].items():
            if value is not None and field not in merged:
                merged[field] = value
                merged[f"{field}_year"] = yr
    return merged


def _score_market_size(size_usd: float | None, log_max: float) -> float:
    if size_usd is None or size_usd <= 0:
        return 0.0
    return min(100.0, math.log1p(size_usd) / log_max * 100)


def _score_growth(cagr_pct: float | None) -> float:
    """Map CAGR% → 0–100. 0% → 50, +20% → 100, -20% → 0."""
    if cagr_pct is None:
        return 50.0  # neutral default
    return max(0.0, min(100.0, 50.0 + cagr_pct * 2.5))


def _score_market_quality(ctx: dict) -> float:
    """Average of LPI, regulatory quality and political stability sub-scores."""
    sub: list[float] = []

    lpi = ctx.get("lpi_score")
    if lpi is not None:
        sub.append(max(0.0, min(100.0, (lpi - 1) / 4 * 100)))  # 1–5 → 0–100

    for wgi_key in ("regulatory_quality", "political_stability"):
        val = ctx.get(wgi_key)
        if val is not None:
            sub.append(max(0.0, min(100.0, (val + 2.5) / 5.0 * 100)))  # -2.5–2.5 → 0–100

    return float(sum(sub) / len(sub)) if sub else 50.0  # neutral if no data


def _score_price(competitiveness: str | None) -> float:
    mapping = {
        "Highly Competitive": 100.0,
        "Competitive": 75.0,
        "Average": 50.0,
        "Above Market": 25.0,
    }
    return mapping.get(competitiveness or "", 50.0)


def _score_foothold(afg_value: float | None, afg_last_export_value: float | None = None) -> float:
    """
    Existing Afghan presence signals market acceptance.

    afg_value is this year's figure -- the same one used everywhere else,
    including a genuine current-year zero when Afghanistan isn't in this
    year's partner breakdown (see _resolve_afg_last_export()'s docstring).
    A genuine zero shouldn't score identically to a market with no Afghan
    trade history at all, though: when afg_value is missing/zero but
    Afghanistan has a recent bounded-year export on record
    (afg_last_export_value, see AFG_LAST_EXPORT_FLOOR_YEAR), that's still
    real evidence of market acceptance -- score it, just at a discount
    (0.7x) versus an active current-year presence.
    """
    if afg_value is not None and afg_value > 0:
        # Log-scale: $10k → ~25, $1M → ~60, $10M → ~75, $100M → ~90
        return min(100.0, math.log10(afg_value + 1) * 14)
    if afg_last_export_value is not None and afg_last_export_value > 0:
        return min(90.0, math.log10(afg_last_export_value + 1) * 14 * 0.7)
    return 0.0  # no Afghan trade on record at all, current or historical


def _score_distance(dist_km: int | None) -> float:
    """
    Closer is better, log-scaled: 0 km → 100, MAX_GREAT_CIRCLE_DISTANCE_KM → 0.

    Log rather than linear because trade/transport costs scale with the
    *ratio* of distance, not the absolute km gap (the standard gravity-model
    treatment -- see MAX_GREAT_CIRCLE_DISTANCE_KM's definition in config.py).
    A neighbor at 400km vs. a market 3.5x farther at 1400km loses meaningfully
    more score than two far markets 1000km apart at 9000km vs. 10000km (only
    11% farther), even though both pairs differ by the same 1000km.
    """
    if dist_km is None:
        return 50.0  # neutral default
    if dist_km <= 0:
        return 100.0
    return max(0.0, 100.0 * (1 - math.log1p(dist_km) / math.log1p(MAX_GREAT_CIRCLE_DISTANCE_KM)))


def _score_tariff(rate_pct: float | None) -> float:
    """
    Lower tariff is better. 0% → 100, ~33% → 0 (linear).
    Returns a neutral 50 when tariff data is unavailable.
    """
    if rate_pct is None:
        return 50.0
    return max(0.0, 100.0 - float(rate_pct) * TARIFF_SCORE_PER_PCT)
