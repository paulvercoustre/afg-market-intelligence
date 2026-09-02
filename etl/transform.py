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
    CAGR_SCORE_BAND_PCT,
    DISTANCE_FROM_KABUL_KM,
    LANGUAGE_SIMILARITY,
    LANGUAGE_SIMILARITY_DEFAULT,
    MARKET_SIZE_LOG_FLOOR_USD,
    MAX_GREAT_CIRCLE_DISTANCE_KM,
    NATIVE_UNIT_PRICE_BASES,
    OPPORTUNITY_SCORE_WEIGHTS,
    PRICE_COMPETITIVENESS,
    PRICE_OUTLIER_BAND_MULTIPLIER,
    TARIFF_SCORE_LOG_CEILING_PCT,
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
            "quantity_unit": r.get("quantity_unit"),
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

        # Unit price -- basis is net_weight_kg unless every one of
        # Afghanistan's own rows for this year agrees on one of
        # NATIVE_UNIT_PRICE_BASES (see config.py), e.g. carpets priced by m²
        unit_price, price_basis = _unit_price(afg_to_market, trade_data_year)

        # Market average price and competitiveness -- computed on the SAME
        # basis as unit_price, so the comparison is apples-to-apples; a
        # competitor that doesn't share that basis is excluded rather than
        # silently mixed in on a different unit.
        market_avg_price, price_vs_market_pct, competitiveness = _price_competitiveness(
            global_df, market_code, unit_price, price_basis, trade_data_year
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
            "price_basis": price_basis,
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

# A CAGR beyond this is treated as a near-zero-base artifact rather than a
# real trend -- see _find_sensical_cagr_window(). Chosen deliberately loose:
# 500%/year compounded is already extreme (a 2-year span at the limit is a
# 36x increase, a 4-year span is 1296x), so this only catches the most
# extreme cases, minimising the risk of trimming a genuinely fast-growing
# small market. It's also well above where it would matter to the score
# anyway -- _score_growth saturates at +-20%/year, so a real 25% CAGR and a
# fake 100,000% CAGR score identically (100). Checked against live data
# (2026-08-28): flags 30/691 (4.3%) of currently-computed cagr_pct values
# for the fallback below, e.g. Dried Apricots/France, whose naive 2022-2025
# CAGR of +1079% is an artifact of a $6.35 opening year -- dropping that
# year reveals the real trend is a -62% decline, not growth at all.
_MAX_SENSICAL_CAGR_PCT = 500.0


def _safe_pct(value: float | None) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value if abs(value) <= _MAX_PCT_MAGNITUDE else None


def _find_sensical_cagr_window(
    year_list: list[int], val_list: list[float], limit: float
) -> tuple[float | None, int | None, int | None, float | None, float | None]:
    """
    Find the (first_year, last_year) pair whose CAGR is <= limit in
    magnitude, preferring the widest possible span and, among spans of
    equal width, preferring to trim the earliest year before the latest.

    Exists because a single unrepresentative endpoint -- e.g. one year with
    a near-zero trade value from a single tiny/one-off shipment -- can blow
    up the naive first-year-to-last-year CAGR into a meaningless number
    (see _MAX_SENSICAL_CAGR_PCT), even though the years around it show a
    perfectly normal trend. Rather than discarding the CAGR entirely
    whenever this happens, retry with that endpoint dropped before giving
    up -- exactly like _score_tariff/_score_growth etc. fall back to a
    neutral default only when there's truly nothing usable, not the first
    time the naive calculation looks wrong.

    Returns (cagr, first_year, last_year, first_val, last_val), or a tuple
    of Nones if no window (down to the minimum 2-year span) qualifies.
    """
    n = len(year_list)
    for span in range(n - 1, 0, -1):
        max_start = n - 1 - span
        for start_idx in range(max_start, -1, -1):  # trim start before end
            end_idx = start_idx + span
            first_year, last_year = year_list[start_idx], year_list[end_idx]
            first_val, last_val = val_list[start_idx], val_list[end_idx]
            year_gap = last_year - first_year
            if year_gap <= 0 or first_val <= 0:
                continue
            cagr = _safe_pct(((last_val / first_val) ** (1 / year_gap) - 1) * 100)
            if cagr is not None and abs(cagr) <= limit:
                return cagr, first_year, last_year, first_val, last_val
    return None, None, None, None, None


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

    year_list = [int(y) for y in yearly["year"]]
    val_list = [float(v) for v in yearly["trade_value_usd"]]

    # yoy always compares the two most recent chronological years -- unlike
    # cagr, there's no meaningful "try a different pair" fallback for a
    # metric that's definitionally about consecutive years, so this stays
    # independent of the window search below.
    yoy = None
    prev_val, latest_val = val_list[-2], val_list[-1]
    if prev_val > 0:
        yoy = (latest_val - prev_val) / prev_val * 100

    # absolute always describes the full raw data span, unconditionally --
    # a plain subtraction has no near-zero-base blowup risk (unlike cagr's
    # and pct's division below), so an opening value of exactly $0 still
    # gives a perfectly meaningful "$0 -> $1,000, +$1,000" rather than
    # something to discard, and it answers a genuinely different question
    # ("total dollar change across the whole observed history") than the
    # windowed metrics below.
    raw_first_val, raw_last_val = val_list[0], val_list[-1]
    absolute = raw_last_val - raw_first_val

    # first_year/last_year is specifically cagr_pct's own displayed span
    # (the frontend shows it as CAGR's sub-label, "CAGR: 3.6% / 2021-2025").
    # pct shares this same window rather than the raw span above -- unlike
    # absolute, pct divides by first_val exactly like cagr does, so it has
    # the identical near-zero-base blowup vulnerability (a $6.35 opening
    # year made a real stored growth_pct read 164,046% while the already-
    # fixed cagr_pct on the same row correctly read -62%) and needs the
    # same fix, not just the same window for cosmetic consistency.
    cagr, first_year, last_year, resolved_first_val, resolved_last_val = (
        _find_sensical_cagr_window(year_list, val_list, _MAX_SENSICAL_CAGR_PCT)
    )
    pct = (
        _safe_pct((resolved_last_val - resolved_first_val) / resolved_first_val * 100)
        if resolved_first_val is not None
        else None
    )

    return {
        "yoy": _safe_pct(yoy), "cagr": cagr, "absolute": absolute,
        "pct": pct, "first_year": first_year, "last_year": last_year,
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


def _native_unit_basis(sub: pd.DataFrame) -> str | None:
    """
    Returns the single unit every row in `sub` agrees on, if it's one of
    NATIVE_UNIT_PRICE_BASES (config.py) -- e.g. carpets reported in m² --
    else None. Requires unanimous agreement: a product/market/year where
    even one row reports a different (or missing) unit falls back to
    net_weight_kg rather than risk mixing bases.
    """
    units = sub.get("quantity_unit", pd.Series(dtype=object)).dropna().unique()
    if len(units) == 1 and units[0] in NATIVE_UNIT_PRICE_BASES:
        return units[0]
    return None


def _unit_price(afg_df: pd.DataFrame, year: int) -> tuple[float | None, str | None]:
    """
    Returns (price_per_unit, basis) where basis is either one of
    NATIVE_UNIT_PRICE_BASES (e.g. "m²") or "kg" (net_weight_kg), or
    (None, None) if no price could be computed on either basis.
    """
    sub = afg_df[afg_df["year"] == year]
    if sub.empty:
        return None, None
    value = pd.to_numeric(sub["trade_value_usd"], errors="coerce").sum()

    native_unit = _native_unit_basis(sub)
    if native_unit is not None:
        qty = pd.to_numeric(sub.get("trade_quantity", pd.Series(dtype=float)), errors="coerce").sum()
        if qty and qty > 0:
            return float(value / qty), native_unit

    # net_weight_kg fallback -- deliberately NO fallback to the free-form
    # "quantity" field beyond the NATIVE_UNIT_PRICE_BASES allowlist above
    # (kg, m^2, pieces, ... depending on the reporter, with no reliable unit
    # label in the general case). A blanket fallback would silently
    # reintroduce the cross-country unit mismatch this is meant to prevent
    # (see DATA_SPECIFICATION.md §4.5 and Berthou & Emlinger, "The Trade
    # Unit Values Database", CEPII Working Paper 2011-10, §2.2). Better to
    # leave the price comparison undetermined -- None propagates through
    # _price_competitiveness() and surfaces as "no unit data for comparison"
    # in the UI -- than to compute one on a basis we can't verify.
    wt = pd.to_numeric(sub.get("net_weight_kg", pd.Series(dtype=float)), errors="coerce").sum()
    if wt and wt > 0:
        return float(value / wt), "kg"
    return None, None


def _price_competitiveness(
    global_df: pd.DataFrame,
    market_code: str,
    afg_price: float | None,
    afg_basis: str | None,
    year: int,
) -> tuple[float | None, float | None, str | None]:
    """
    afg_basis (from _unit_price()) is either "kg" or one of
    NATIVE_UNIT_PRICE_BASES -- competitor prices are computed on that SAME
    basis, so the comparison stays apples-to-apples. A competitor reporting
    a different (or no) unit is excluded rather than silently mixed in.
    """
    if afg_price is None or afg_basis is None or global_df.empty:
        return None, None, None

    suppliers = global_df[
        (global_df["reporterCode"] == market_code)
        & (global_df["partnerCode"] != "0")
        & (global_df["year"] == year)
    ].copy()
    if suppliers.empty:
        return None, None, None

    suppliers["_val"] = pd.to_numeric(suppliers["primaryValue"], errors="coerce")

    if afg_basis in NATIVE_UNIT_PRICE_BASES:
        on_basis = suppliers[suppliers.get("quantity_unit") == afg_basis].copy()
        on_basis["_qty"] = pd.to_numeric(on_basis.get("qty", pd.Series(dtype=float)), errors="coerce")
        on_basis["_price"] = on_basis.apply(
            lambda r: r["_val"] / r["_qty"] if r["_qty"] > 0 else None, axis=1
        )
        valid = on_basis["_price"].dropna()
    else:
        # Net weight (kg) only -- same reasoning as _unit_price(): no fallback
        # to the free-form "quantity" field. A supplier that didn't report
        # net weight is excluded from the comparison entirely (its _price
        # stays None and gets dropped below) rather than being included on a
        # potentially incompatible unit basis.
        suppliers["_wt"] = pd.to_numeric(
            suppliers.get("netWgt", pd.Series(dtype=float)), errors="coerce"
        )
        suppliers["_price"] = suppliers.apply(
            lambda r: r["_val"] / r["_wt"] if r["_wt"] > 0 else None, axis=1
        )
        valid = suppliers["_price"].dropna()

    if valid.empty:
        return None, None, None

    # Comtrade lets each reporter submit "quantity" in whatever unit its own
    # customs system uses (kg, m^2, pieces, ...) with no reliable unit label
    # (qtyUnitAbbr is frequently blank) -- so dividing value/quantity across
    # suppliers can silently mix incompatible units, producing wild implied
    # "prices" that are really just unit mismatches (e.g. one HS6 code, one
    # market, one year: $11/unit to $5,834/unit across suppliers). We can't
    # recover the true unit, but a unit-mismatched supplier is a stark outlier
    # against the rest, who are more likely reporting comparably -- so filter
    # by distance from the median before averaging, the same outlier band
    # CEPII uses when cleaning raw Comtrade data for this exact reason (an
    # observation is dropped if it exceeds median*10 or is below median/10;
    # see Berthou & Emlinger, "The Trade Unit Values Database", CEPII Working
    # Paper 2011-10, Appendix A2).
    median_price = float(valid.median())
    if median_price > 0:
        filtered = valid[
            (valid >= median_price / PRICE_OUTLIER_BAND_MULTIPLIER)
            & (valid <= median_price * PRICE_OUTLIER_BAND_MULTIPLIER)
        ]
        if not filtered.empty:
            valid = filtered

    market_avg = float(valid.mean())
    pct_diff = (afg_price - market_avg) / market_avg * 100 if market_avg > 0 else None

    label = None
    if pct_diff is not None:
        thresholds = PRICE_COMPETITIVENESS
        if pct_diff < thresholds["substantially_below_market"]:
            label = "Substantially Below Market"
        elif pct_diff < thresholds["below_market"]:
            label = "Below Market"
        elif pct_diff < thresholds["near_market"]:
            label = "Near Market"
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

    # Pre-compute log-normalised market size across all markets for this product.
    # log_max is the denominator of _score_market_size's log min-max formula --
    # see that function's docstring for why the floor is MARKET_SIZE_LOG_FLOOR_USD
    # (an external reference) rather than the observed minimum.
    sizes = [v for v in all_market_sizes.values() if v and v > 0]
    max_size = max(sizes) if sizes else None
    if max_size and max_size > MARKET_SIZE_LOG_FLOOR_USD:
        log_max = math.log(max_size / MARKET_SIZE_LOG_FLOOR_USD)
    else:
        log_max = 1.0

    # Pre-compute the per-product ceiling for _score_foothold's log min-max --
    # Afghanistan's single best recorded trade relationship for this product,
    # current-year or historical (whichever is larger), so the historical
    # fallback path still has a meaningful reference even when no market
    # currently has current-year data. See _score_foothold's docstring for
    # why this needs no external floor the way market_size's does.
    afg_values = []
    for row in indicator_rows:
        v = row.get("afg_export_value_usd")
        if v and v > 0:
            afg_values.append(v)
        lv = row.get("afg_last_export_value_usd")
        if lv and lv > 0:
            afg_values.append(lv)
    max_afg_value = max(afg_values) if afg_values else None

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
        # WITS deliberately reports MFN/Applied tariff rates for products a
        # market doesn't actually trade at all -- its own site says so
        # outright ("MFN and Applied Tariff are provided for both traded and
        # non-traded goods"), and there's no "is this traded" flag anywhere
        # in the tariff API response to filter those out. So this is derived
        # from our own Comtrade data instead: a rate is only trusted if
        # Afghanistan has real export evidence for this market -- this year
        # or (falling back, same as the foothold score) historically. This
        # is a raw-value check (> 0 on the actual float), not a rounded or
        # displayed figure, so a genuine but tiny shipment still counts as
        # traded. Applies the same way regardless of whether WITS reported
        # the rate as AHS or MFN -- that only says which regime the rate
        # came from, not whether Afghanistan actually trades here.
        has_afg_trade_evidence = (
            (row.get("afg_export_value_usd") or 0) > 0
            or (row.get("afg_last_export_value_usd") or 0) > 0
        )
        tariff_info = tariffs.get(mc) or {}
        if not has_afg_trade_evidence:
            tariff_info = {}
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
            row.get("afg_export_value_usd"), max_afg_value, row.get("afg_last_export_value_usd")
        )
        s_distance = _score_distance(dist_km)
        s_language = lang * 100
        s_fta = 100.0 if has_fta else 0.0
        s_tariff = _score_tariff(tariff_rate)

        row["score_market_size"] = round(s_size, 2) if s_size is not None else None
        row["score_market_growth"] = round(s_growth, 2) if s_growth is not None else None
        row["score_market_quality"] = round(s_quality, 2) if s_quality is not None else None
        row["score_price_competitiveness"] = round(s_price, 2)
        row["score_afg_foothold"] = round(s_foothold, 2)
        row["score_distance"] = round(s_distance, 2) if s_distance is not None else None
        row["score_language"] = round(s_language, 2)
        row["score_fta"] = round(s_fta, 2)
        row["score_tariff"] = round(s_tariff, 2) if s_tariff is not None else None

        # score_fta/has_fta are still computed and stored above for every row
        # (in case WITS's AFG-specific tariff coverage improves), but not
        # weighted into the composite -- see config.py's OPPORTUNITY_SCORE_WEIGHTS
        # comment for why (WITS has_fta is currently False for 100% of rows).
        #
        # market_size, market_growth, market_quality, tariff and distance are
        # the five dimensions with no sensible neutral-default value to fall
        # back to when their underlying raw data is missing entirely --
        # rather than guessing, a missing one is dropped from the composite
        # and the remaining weights renormalised to sum back to 1.0. This is
        # written to generalise over any combination being missing at once,
        # not as separate hardcoded cases.
        nullable_dims = {
            "market_size": s_size, "market_growth": s_growth,
            "market_quality": s_quality, "tariff": s_tariff,
            "distance": s_distance,
        }
        fixed_dims = {
            "price_competitiveness": s_price, "afg_foothold": s_foothold,
            "language": s_language,
        }
        weighted_sum = sum(v * weights[k] for k, v in fixed_dims.items())
        present_weight = sum(weights[k] for k in fixed_dims)
        for k, v in nullable_dims.items():
            if v is not None:
                weighted_sum += v * weights[k]
                present_weight += weights[k]
        composite = weighted_sum / present_weight
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


def _score_market_size(size_usd: float | None, log_max: float) -> float | None:
    """
    Log-transform, then Min-Max normalise against a fixed floor (F) instead
    of the observed sample minimum -- OECD (2008) Handbook on Constructing
    Composite Indicators, Step 5: log-transformed prior to normalisation to
    correct positive skew (§5.1), then normalised by the Min-Max method
    (§5.3). Departing from the percentile-trimming approach cited at §5.1,
    the lower bound is set to a fixed exogenous threshold F
    (MARKET_SIZE_LOG_FLOOR_USD, config.py) rather than the observed minimum,
    following the external-reference logic of §5.4 -- this avoids the
    instability the Handbook notes for data-derived bounds (§5.3, "not
    stable when data for a new time point become available") without
    collapsing the ranking of the smallest traders. v_max (via log_max,
    pre-computed by the caller) is still the observed leader for this
    product, recomputed per product so the leader always scores 100.

    Three distinct states, kept apart deliberately:
    - size_usd is None: no data at all -- returns None (missing), which the
      caller excludes from the composite and renormalises the remaining
      dimensions' weights for, rather than guessing best- or worst-case.
    - size_usd == 0: a genuine reported zero -- scores 0, same as before.
    - 0 < size_usd <= F: real but below the noise floor -- clipped to 0
      rather than going negative (ln(size/F) would be <= 0 here). This
      shouldn't happen for a well-chosen F on real data; if it does, F is
      probably set too high (see the derivation note on
      MARKET_SIZE_LOG_FLOOR_USD in config.py).
    - size_usd > F: scored on the log scale, min-maxed between F and v_max.
    """
    if size_usd is None:
        return None
    if size_usd <= 0:
        return 0.0
    if size_usd <= MARKET_SIZE_LOG_FLOOR_USD:
        return 0.0
    return max(0.0, min(100.0, 100.0 * math.log(size_usd / MARKET_SIZE_LOG_FLOOR_USD) / log_max))


def _score_growth(cagr_pct: float | None) -> float | None:
    """
    Min-Max normalise cagr_pct onto 0-100 against a fixed, symmetric
    external reference band [-W, +W] (W = CAGR_SCORE_BAND_PCT, config.py;
    not the observed sample min/max) -- same external-reference-over-data-
    derived-bounds logic as _score_market_size's floor F (OECD 2008
    Handbook, Step 5, §5.3 Min-Max with the §5.4 external-reference variant
    in place of the data-derived minimum/maximum). 0% CAGR (no growth) is
    the natural zero-point of the underlying quantity, so it's centred at
    the scale's own midpoint, 50 -- that's the direct algebraic result of
    Min-Max on a range centred at zero, not a separate constant added on
    top: substituting min=-W, max=+W into (x-min)/(max-min)*100 gives
    100*(cagr+W)/(2W), which is exactly 50 + cagr*(50/W).

    cagr_pct is None (no data at all, not a genuine 0% reading) returns
    None -- like _score_market_size, there's no sensible neutral default to
    guess here, so the caller excludes this dimension from the composite
    and renormalises the remaining weights, rather than defaulting to 50.
    """
    if cagr_pct is None:
        return None
    return max(0.0, min(100.0, 50.0 + cagr_pct * (50.0 / CAGR_SCORE_BAND_PCT)))


def _score_market_quality(ctx: dict) -> float | None:
    """
    Average of LPI, regulatory quality and political stability sub-scores.

    regulatory_quality and political_stability are both fetched on the WGI
    "score" scale (GOV_WGI_RQ.SC / GOV_WGI_PV.SC), already 0-100 -- see the
    note by _WB_INDICATORS in etl/fetch.py. Only lpi_score (1-5) still needs
    rescaling here.

    Returns None (not a guessed neutral default) if all three sub-fields are
    missing -- same treatment as _score_market_size/_score_growth when their
    underlying raw data is missing entirely: the caller excludes this
    dimension from the composite and renormalises the remaining weights,
    rather than assuming an "average" market quality with zero information
    to base it on.
    """
    sub: list[float] = []

    lpi = ctx.get("lpi_score")
    if lpi is not None:
        sub.append(max(0.0, min(100.0, (lpi - 1) / 4 * 100)))  # 1–5 → 0–100

    reg = ctx.get("regulatory_quality")
    if reg is not None:
        sub.append(max(0.0, min(100.0, reg)))  # already 0–100

    pv = ctx.get("political_stability")
    if pv is not None:
        sub.append(max(0.0, min(100.0, pv)))  # already 0–100

    return float(sum(sub) / len(sub)) if sub else None


def _score_price(competitiveness: str | None) -> float:
    mapping = {
        "Substantially Below Market": 100.0,
        "Below Market": 75.0,
        "Near Market": 50.0,
        "Above Market": 25.0,
    }
    return mapping.get(competitiveness or "", 50.0)


def _score_foothold(
    afg_value: float | None,
    max_afg_value: float | None,
    afg_last_export_value: float | None = None,
) -> float:
    """
    Existing Afghan presence signals market acceptance.

    Per-product log min-max, same method as _score_market_size:
    100 * log1p(x) / log1p(max_afg_value), where max_afg_value (precomputed
    by the caller) is Afghanistan's single best recorded trade relationship
    for this product across all its markets -- current-year or historical,
    whichever is larger -- so the market with Afghanistan's strongest
    foothold in THIS product always scores exactly 100, and every other
    market scales smoothly relative to it. No external floor is needed the
    way market_size's F is: unlike global_market_size_usd, there's no
    noise/artifact ambiguity to guard against here -- even a tiny genuine
    shipment (e.g. $7) is real trade evidence, consistent with the
    trade-evidence rule in enrich_indicators_with_scores's tariff logic
    above, so log1p(0)=0 is already the right, natural floor.

    Replaced 2026-09-02: the previous min(100, log10(x+1)*14) used an
    arbitrary multiplier with an undocumented, product-independent ceiling
    (clamped at ~$13.9M) -- 22 of 36 products never had ANY market reach
    100 under it, purely because that product's biggest trade relationship
    happened to sit below that fixed threshold, unrelated to whether it was
    genuinely Afghanistan's strongest market for that product.

    afg_value is this year's figure -- the same one used everywhere else,
    including a genuine current-year zero when Afghanistan isn't in this
    year's partner breakdown (see _resolve_afg_last_export()'s docstring).
    A genuine zero shouldn't score identically to a market with no Afghan
    trade history at all, though: when afg_value is missing/zero but
    Afghanistan has a recent bounded-year export on record
    (afg_last_export_value, see AFG_LAST_EXPORT_FLOOR_YEAR), that's still
    real evidence of market acceptance -- score it, just at a discount
    (0.7x, capped at 90) versus an active current-year presence. This
    discount/cap structure is unchanged from before.
    """
    has_ceiling = max_afg_value is not None and max_afg_value > 0
    if afg_value is not None and afg_value > 0 and has_ceiling:
        return min(100.0, 100.0 * math.log1p(afg_value) / math.log1p(max_afg_value))
    if afg_last_export_value is not None and afg_last_export_value > 0 and has_ceiling:
        return min(90.0, 100.0 * math.log1p(afg_last_export_value) / math.log1p(max_afg_value) * 0.7)
    return 0.0  # no Afghan trade on record at all, current or historical


def _score_distance(dist_km: int | None) -> float | None:
    """
    Closer is better, log-scaled: 0 km → 100, MAX_GREAT_CIRCLE_DISTANCE_KM → 0.

    Log rather than linear because trade/transport costs scale with the
    *ratio* of distance, not the absolute km gap (the standard gravity-model
    treatment -- see MAX_GREAT_CIRCLE_DISTANCE_KM's definition in config.py).
    A neighbor at 400km vs. a market 3.5x farther at 1400km loses meaningfully
    more score than two far markets 1000km apart at 9000km vs. 10000km (only
    11% farther), even though both pairs differ by the same 1000km.

    Returns None (not a guessed neutral default) when dist_km is missing --
    same treatment as _score_market_size/_score_growth/_score_market_quality/
    _score_tariff: the caller excludes this dimension from the composite and
    renormalises the remaining weights. This isn't a hypothetical case --
    a handful of real markets (e.g. Andorra, Montenegro, Palestine) have no
    CEPII GeoDist entry for their ISO-3 code at all (see
    DISTANCE_FROM_KABUL_KM in config.py), so there's genuinely no distance
    on file to fall back to a guess for.
    """
    if dist_km is None:
        return None
    if dist_km <= 0:
        return 100.0
    return max(0.0, 100.0 * (1 - math.log1p(dist_km) / math.log1p(MAX_GREAT_CIRCLE_DISTANCE_KM)))


def _score_tariff(rate_pct: float | None) -> float | None:
    """
    Lower tariff is better. Log-transform then Min-Max against a fixed
    external ceiling (OECD 2008 Handbook, Step 5, §5.1 log-transform for
    positive skew + §5.3 Min-Max with the §5.4 external-reference variant
    -- same method as _score_market_size/_score_growth/_score_foothold):

        score = 100 * (1 - log1p(rate) / log1p(ceiling))

    0% -> 100, ~3.3% (the real median) -> ~59, 10% -> ~33, 20% -> ~15,
    ceiling%+ -> 0 (clamped). See TARIFF_SCORE_LOG_CEILING_PCT (config.py)
    for why log-transform + Min-Max was chosen over a plain linear scale
    (real tariffs are positively skewed -- most are small, log-transform
    spreads out exactly that dense region instead of the rare high-tariff
    tail), over a squared-ratio alternative (does the opposite: crowds the
    dense region even tighter), and for how the ceiling itself (35, not the
    30 first tried) was re-optimised for this specific transform.

    Returns None (not a guessed neutral default) when tariff data is
    unavailable -- same treatment as _score_market_size/_score_growth/
    _score_market_quality: the caller excludes this dimension from the
    composite and renormalises the remaining weights, rather than assuming
    a neutral tariff with no real basis for that assumption. rate_pct ends
    up None for two different reasons that both collapse to this same
    treatment: WITS genuinely has no tariff schedule on file for this
    reporter/product, or WITS has a rate but it's discarded because
    Afghanistan has no real trade evidence for this market (the
    non-traded-goods filter above) -- either way, there's no trustworthy
    tariff number to score.
    """
    if rate_pct is None:
        return None
    rate = max(0.0, float(rate_pct))
    return max(0.0, min(100.0, 100.0 * (1 - math.log1p(rate) / math.log1p(TARIFF_SCORE_LOG_CEILING_PCT))))
