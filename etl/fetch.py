"""
Data fetch layer: UN Comtrade + World Bank Development Indicators.

Comtrade improvements over the original client:
- Single generic fetch function replaces 6 near-identical functions
- Exponential backoff retry on rate-limit / network errors
- Proper SSL verification via certifi (no global monkey-patch)
"""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

import certifi
import comtradeapicall
import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Afghanistan's UN Comtrade numeric reporter code
AFGHANISTAN_NUMERIC = "4"

# Delay between successive API calls (seconds) to stay within rate limits
_API_DELAY = 1.0

# Patch comtradeapicall to use certifi bundle if it uses requests internally.
# This replaces the unsafe ssl._create_unverified_context monkey-patch used in
# the original comtrade_client.py.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


def _get_api_key() -> str | None:
    key = os.environ.get("COMTRADE_API_KEY")
    if not key:
        logger.warning("COMTRADE_API_KEY not set — API calls will likely fail")
    return key


class ComtradeRateLimitError(Exception):
    pass


def _call_comtrade(
    period: str,
    hs_code: str,
    flow_code: str,
    reporter_code: str | None,
    partner_code: str | None,
) -> pd.DataFrame:
    """
    Single wrapper around comtradeapicall.getFinalData.

    flow_code: 'M' = imports, 'X' = exports
    reporter_code: None → all reporters
    partner_code: None → all partners

    partner2Code, customsCode and motCode are all pinned to their "TOTAL"
    sentinel rather than left as None. Comtrade breaks a trade flow out along
    several optional dimensions -- secondary partner (re-export/transshipment),
    customs procedure, and mode of transport (sea/air/land) among them -- and
    for each one, a pre-aggregated "TOTAL" row (partner2Code='0', motCode='0',
    customsCode='C00') coexists with breakdown rows that sum up to it. Leaving
    any of them as None returns *all* rows for that dimension together, and
    nothing downstream deduplicates or sums them correctly: summing every row
    naively double-counts (aggregate + its own components), while a plain
    per-(reporter,partner,year) upsert with ON CONFLICT DO UPDATE just keeps
    whichever breakdown row happened to load last -- an arbitrary fragment,
    not the total. Pinning all three to their TOTAL value selects only the
    single pre-aggregated total, which is also what standard trade dashboards
    (Comtrade's own DataViz, ITC Trade Map, WITS) report as "the" bilateral
    trade value.
    """
    api_key = _get_api_key()
    response = comtradeapicall.getFinalData(
        subscription_key=api_key,
        typeCode="C",
        freqCode="A",
        clCode="HS",
        period=period,
        reporterCode=reporter_code,
        cmdCode=hs_code,
        flowCode=flow_code,
        partnerCode=partner_code,
        partner2Code="0",
        customsCode="C00",
        motCode="0",
    )
    time.sleep(_API_DELAY)

    if response is None:
        return pd.DataFrame()
    if isinstance(response, pd.DataFrame):
        return response if not response.empty else pd.DataFrame()
    if isinstance(response, list):
        return pd.DataFrame(response) if response else pd.DataFrame()
    return pd.DataFrame()


@retry(
    retry=retry_if_exception_type((ComtradeRateLimitError, ConnectionError, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(2),
    reraise=True,
)
def fetch_mirror_exports(hs_code: str, years: list[int]) -> pd.DataFrame:
    """
    Fetch Afghanistan's exports via mirror data (all countries' imports FROM Afghanistan).

    Since Afghanistan does not report to UN Comtrade, we query the opposite side:
    all countries' import flows where Afghanistan is the partner/exporter.

    Returns a DataFrame with columns:
        hs_code, year, importer_code, trade_value_usd, trade_quantity, net_weight_kg
    """
    hs_clean = hs_code.replace(".", "")
    period = ",".join(str(y) for y in years)
    logger.info(f"fetch_mirror_exports: HS {hs_clean}, years {period}")

    raw = _call_comtrade(
        period=period,
        hs_code=hs_clean,
        flow_code="M",
        reporter_code=None,          # all importing countries
        partner_code=AFGHANISTAN_NUMERIC,  # Afghanistan as exporter
    )

    if raw.empty:
        logger.warning(f"No mirror export data returned for HS {hs_clean}")
        return pd.DataFrame()

    return _normalise_mirror(raw, hs_clean)


@retry(
    retry=retry_if_exception_type((ComtradeRateLimitError, ConnectionError, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(2),
    reraise=True,
)
def fetch_global_imports(hs_code: str, years: list[int]) -> pd.DataFrame:
    """
    Fetch the full global import picture for an HS code: all reporters × all partners.

    This single API call replaces three separate functions in the original client:
      - fetch_unified_global_imports
      - fetch_market_imports_batch (world totals via partnerCode='0')
      - fetch_market_imports_by_partner_batch (supplier breakdowns)

    Returns a DataFrame with raw Comtrade columns plus a normalised 'year' int column.
    Callers use transform.py to extract the slices they need.
    """
    hs_clean = hs_code.replace(".", "")
    period = ",".join(str(y) for y in years)
    logger.info(f"fetch_global_imports: HS {hs_clean}, years {period}")

    raw = _call_comtrade(
        period=period,
        hs_code=hs_clean,
        flow_code="M",
        reporter_code=None,   # all importers
        partner_code=None,    # all suppliers (including World '0')
    )

    if raw.empty:
        logger.warning(f"No global import data returned for HS {hs_clean}")
        return pd.DataFrame()

    # Normalise year column
    if "refYear" in raw.columns:
        raw["year"] = pd.to_numeric(raw["refYear"], errors="coerce").astype("Int64")
    elif "period" in raw.columns:
        raw["year"] = pd.to_numeric(raw["period"], errors="coerce").astype("Int64")

    raw["reporterCode"] = raw["reporterCode"].astype(str)
    raw["partnerCode"] = raw["partnerCode"].astype(str)
    raw["quantity_unit"] = _resolve_quantity_units(raw)

    return raw[raw["year"].isin(years)].copy()


# ── World Bank Development Indicators ────────────────────────────────────────

_WB_BASE = "https://api.worldbank.org/v2"

# Indicator codes we fetch from WDI and WGI.
# NB: the WGI codes were renamed by the World Bank — the old RQ.EST / PV.EST
# codes are archived and return "indicator not found".
#
# Both WGI fields deliberately use the .SC ("Governance score, 0-100")
# variant instead of the .EST ("Governance estimate, approx -2.5 to +2.5")
# variant -- a plain 0-100 range is much clearer to reason about (and to
# display) than a signed, roughly-normal estimate. Neither needs rescaling
# in _score_market_quality() in etl/transform.py; both are used as-is.
_WB_INDICATORS = {
    "gdp_usd": "NY.GDP.MKTP.CD",
    "gdp_per_capita_usd": "NY.GDP.PCAP.CD",
    "lpi_score": "LP.LPI.OVRL.XQ",
    "regulatory_quality": "GOV_WGI_RQ.SC",
    "political_stability": "GOV_WGI_PV.SC",
}

_WB_SESSION = requests.Session()
_WB_SESSION.verify = certifi.where()


# Max countries per batched WB request. The API accepts semicolon-separated
# country codes in the URL path; keeping chunks modest avoids overly long
# URLs and keeps per_page comfortably above chunk_size * len(years) rows.
_WB_CHUNK_SIZE = 20


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, requests.RequestException)),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _fetch_wb_indicator_chunk(country_codes: list[str], indicator_code: str,
                              years: list[int]) -> dict[str, dict[int, float]]:
    """
    Fetch one World Bank indicator for a batch of countries in a single call.

    Timeout is 60s, not the 30s a single indicator lookup might suggest: a
    chunk of _WB_CHUNK_SIZE (20) countries x up to 5 years is ~100 data
    points in one response, and a 30s timeout was observed to fail on the
    live API for exactly this shape of request (confirmed via etl_run.log:
    two 20-country chunks of NY.GDP.PCAP.CD timed out and exhausted all 4
    retries, silently leaving ~40 major economies -- including China, India,
    Germany -- with NULL gdp_per_capita_usd for every requested year). This
    is the same class of fix as the WITS 20s->90s timeout correction below.
    """
    year_range = f"{min(years)}:{max(years)}"
    countries = ";".join(country_codes)
    url = f"{_WB_BASE}/country/{countries}/indicator/{indicator_code}"
    params = {"format": "json", "date": year_range, "per_page": 2000}
    resp = _WB_SESSION.get(url, params=params, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    # The WB API signals errors (e.g. unknown indicator) with HTTP 200 and a
    # single-element message payload — surface those instead of returning empty.
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) and "message" in data[0]:
        messages = data[0]["message"]
        raise ValueError(f"World Bank API error for {indicator_code}: {messages}")
    if not isinstance(data, list) or len(data) < 2:
        return {}

    result: dict[str, dict[int, float]] = {}
    for entry in data[1] or []:
        iso3 = (entry.get("countryiso3code") or "").upper()
        yr_str = entry.get("date")
        value = entry.get("value")
        if iso3 and yr_str and value is not None:
            try:
                result.setdefault(iso3, {})[int(yr_str)] = float(value)
            except (ValueError, TypeError):
                pass
    return result


def fetch_world_bank_indicators(country_codes: list[str], years: list[int]) -> list[dict]:
    """
    Fetch World Bank development indicators for a list of countries.

    country_codes: ISO-3 alpha codes (e.g. ['IND', 'PAK', 'DEU'])
    Returns a list of dicts mapping to the market_context DB table.

    Batches countries into groups of _WB_CHUNK_SIZE per indicator call (the
    WB API accepts semicolon-separated country codes) instead of one request
    per country per indicator. For 70 countries x 5 indicators that's ~20
    requests instead of 350 -- far less exposure to slow/unresponsive calls.
    """
    # field -> iso3 -> year -> value
    per_indicator: dict[str, dict[str, dict[int, float]]] = {f: {} for f in _WB_INDICATORS}

    for field, wb_code in _WB_INDICATORS.items():
        for chunk in _chunk(country_codes, _WB_CHUNK_SIZE):
            try:
                chunk_result = _fetch_wb_indicator_chunk(chunk, wb_code, years)
                per_indicator[field].update(chunk_result)
            except Exception as exc:
                logger.warning(f"World Bank {wb_code} failed for chunk {chunk}: {exc}")
            time.sleep(0.2)  # gentle rate-limit respect

    rows = []
    for iso3 in country_codes:
        all_years = set()
        for field_data in per_indicator.values():
            all_years.update(field_data.get(iso3, {}).keys())

        for yr in sorted(all_years):
            rows.append({
                "country_code": iso3,
                "year": yr,
                "gdp_usd": per_indicator["gdp_usd"].get(iso3, {}).get(yr),
                "gdp_per_capita_usd": per_indicator["gdp_per_capita_usd"].get(iso3, {}).get(yr),
                "lpi_score": per_indicator["lpi_score"].get(iso3, {}).get(yr),
                "regulatory_quality": per_indicator["regulatory_quality"].get(iso3, {}).get(yr),
                "political_stability": per_indicator["political_stability"].get(iso3, {}).get(yr),
            })

    logger.info(f"World Bank fetch complete: {len(rows)} rows for {len(country_codes)} countries")
    return rows


# ── WITS tariff data ─────────────────────────────────────────────────────────
# WITS (World Integrated Trade Solution) — UNCTAD TRAINS tariff database.
# SDMX 2.1 REST endpoint. Working URL format (segment order matters):
#   /datasource/TRN/reporter/{NUM}/partner/{NUM}/product/{HS6|all}/year/{YYYY}/datatype/reported
#
# - Country codes are UN numeric, zero-padded to 3 digits (India=356, AFG=004,
#   World partner=000). ISO-3 alpha codes and reporter=ALL are rejected (403/400).
# - AHS vs MFN is selected via the partner segment, not an indicator code:
#   partner=000 → MFN rates; partner=004 → rates applied specifically to
#   Afghanistan (preferential where a scheme exists). 404 = not reported.
# - We request product/all per (reporter, partner, year) and cache the parsed
#   result, so each market's full tariff schedule is downloaded once per run
#   and shared across all products.

_WITS_BASE = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN"

_WITS_SESSION = requests.Session()
_WITS_SESSION.verify = certifi.where()
# requests.Session defaults to a 10-connection pool per host. Products run
# concurrently (see _PRODUCT_MAX_WORKERS in etl/run.py) and each spins up its
# own _TARIFF_MAX_WORKERS threads against this one shared session, so peak
# concurrent WITS requests can reach _PRODUCT_MAX_WORKERS * _TARIFF_MAX_WORKERS.
# A pool smaller than that forces the excess requests to open a fresh
# connection (full TCP+TLS handshake) instead of reusing one, adding avoidable
# latency on top of WITS's already-slow responses.
_WITS_SESSION.mount(
    "https://",
    requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=30),
)

_WITS_AFG_PARTNER = "004"
_WITS_WORLD_PARTNER = "000"

# Comtrade reporter codes that differ from the UN numeric codes WITS uses.
_COMTRADE_TO_WITS_NUMERIC = {
    "699": "356",  # India
    "842": "840",  # United States
    "757": "756",  # Switzerland
    "251": "250",  # France
    "579": "578",  # Norway
}

# {(reporter, partner, year): {hs6: rate}} — one fetch per key per process
_wits_cache: dict[tuple[str, str, int], dict[str, float]] = {}

# Disk-backed cache so re-running the ETL doesn't re-fetch combos already
# downloaded recently (each one costs 30-60s against WITS). Entries expire
# after _WITS_CACHE_TTL so an update WITS publishes upstream is still picked
# up automatically within that window, rather than being cached forever.
_WITS_CACHE_PATH = Path(__file__).parent / ".cache" / "wits_tariffs.json"
_WITS_CACHE_TTL = timedelta(days=7)
_wits_disk_cache_lock = threading.Lock()


def _load_wits_disk_cache() -> dict:
    if not _WITS_CACHE_PATH.exists():
        return {}
    try:
        with open(_WITS_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"WITS disk cache unreadable, starting fresh: {exc}")
        return {}


def _save_wits_disk_cache(cache: dict) -> None:
    _WITS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _WITS_CACHE_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    tmp_path.replace(_WITS_CACHE_PATH)  # atomic replace, safe if a run is killed mid-write


_wits_disk_cache = _load_wits_disk_cache()


@retry(
    # 404 ("not reported") returns {} immediately below, before raise_for_status
    # can fire, so it never enters this retry loop -- that's already a real,
    # trustworthy answer from WITS and retrying it wouldn't change anything.
    # This retry budget exists purely for the ambiguous case (timeout,
    # connection drop, 5xx) where we genuinely don't know yet whether there's
    # data or not. 5 attempts with backoff up to 30s gives a flaky connection
    # a real chance to clear before we give up *for this call* -- see
    # _cached_wits_tariffs for what happens after that (a "still don't know"
    # is never written to cache, so the next run tries again from scratch
    # rather than a transient blip being remembered as "confirmed no data").
    retry=retry_if_exception_type((ConnectionError, TimeoutError, requests.RequestException)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _fetch_wits_tariffs(reporter: str, partner: str, year: int) -> dict[str, float]:
    """
    Fetch the full tariff schedule one reporter applies to one partner in one year.
    Returns {hs6_code: simple_average_rate_pct}; {} when the combination was
    never reported (HTTP 404 — normal, e.g. no preferential scheme for AFG).

    Timeout is 90s, not the ~1s one might expect from a single lookup: this
    endpoint returns the *entire* product=all tariff schedule for the
    (reporter, partner, year) in one response, and measured against the live
    API this genuinely takes 30-60s end-to-end (confirmed for both 200 and
    404 responses) -- it is not a network hang. A prior version of this
    function set the timeout to 20s on the assumption that successful calls
    return in under a second; that assumption was wrong and made every real
    call fail before completing, which is why tariff data silently stopped
    coming back (the caller in etl/run.py catches the resulting timeout and
    continues without tariff scores).
    """
    url = (
        f"{_WITS_BASE}/reporter/{reporter}/partner/{partner}"
        f"/product/all/year/{year}/datatype/reported"
    )
    resp = _WITS_SESSION.get(url, params={"format": "JSON"}, timeout=90)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        return {}

    return _parse_wits_tariffs(data)


def _parse_wits_tariffs(data: dict) -> dict[str, float]:
    """
    Parse an SDMX-JSON TRN response into {hs_code: rate}.

    The rate is the first element of each observation value array. The series
    key slot that indexes PRODUCTCODE is located empirically: the keyPosition
    attributes in WITS responses do not match the actual key ordering.
    """
    try:
        dimensions = data["structure"]["dimensions"]["series"]
        product_values: list[str] = []
        for dim in dimensions:
            if dim.get("id") == "PRODUCTCODE":
                product_values = [v["id"] for v in dim["values"]]
                break
        if not product_values:
            return {}

        series = data["dataSets"][0]["series"]
        if not series:
            return {}

        product_slot = None
        if len(product_values) > 1:
            n_slots = len(next(iter(series)).split(":"))
            max_per_slot = [0] * n_slots
            for key in series:
                for i, part in enumerate(key.split(":")):
                    max_per_slot[i] = max(max_per_slot[i], int(part))
            candidates = [
                i for i, m in enumerate(max_per_slot)
                if m == len(product_values) - 1 and m > 0
            ]
            if not candidates:
                logger.warning("WITS response: could not locate PRODUCTCODE key slot")
                return {}
            product_slot = candidates[0]

        result: dict[str, float] = {}
        for key, s in series.items():
            if product_slot is None:
                hs_code = product_values[0]
            else:
                hs_code = product_values[int(key.split(":")[product_slot])]
            observations = s.get("observations") or {}
            obs = observations.get("0")
            if obs is None and observations:
                obs = next(iter(observations.values()))
            if obs and obs[0] is not None:
                result[hs_code] = float(obs[0])
        return result
    except (KeyError, IndexError, ValueError, TypeError):
        logger.warning("Failed to parse WITS SDMX-JSON response")
        return {}


def _cached_wits_tariffs(reporter: str, partner: str, year: int, refresh: bool = False) -> dict[str, float]:
    key = (reporter, partner, year)
    if key in _wits_cache:
        return _wits_cache[key]

    disk_key = f"{reporter}|{partner}|{year}"
    if not refresh:
        with _wits_disk_cache_lock:
            entry = _wits_disk_cache.get(disk_key)
        if entry is not None:
            age = datetime.now(UTC) - datetime.fromisoformat(entry["fetched_at"])
            if age < _WITS_CACHE_TTL:
                _wits_cache[key] = entry["data"]
                return entry["data"]

    try:
        data = _fetch_wits_tariffs(reporter, partner, year)
    except Exception as exc:
        # A failed fetch (timeout/connection error, all 5 retries exhausted in
        # _fetch_wits_tariffs) is NOT the same thing as WITS confirming there's
        # no data -- a real 404 already returns a plain {} from
        # _fetch_wits_tariffs without raising, and that IS worth remembering.
        # Caching a failure the same way would silently persist a false "no
        # data" for up to _WITS_CACHE_TTL (7 days). So on failure we
        # deliberately skip both caches, leaving this combo to be retried
        # fresh next time it's requested -- later in this same run (another
        # product needing the same market), or the next scheduled run --
        # instead of every future lookup trusting a guess.
        logger.warning(f"WITS fetch failed for reporter {reporter} partner {partner} {year}: {exc}")
        time.sleep(0.5)
        return {}

    _wits_cache[key] = data
    with _wits_disk_cache_lock:
        _wits_disk_cache[disk_key] = {
            "data": data,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        _save_wits_disk_cache(_wits_disk_cache)
    time.sleep(0.5)
    return data


# Concurrent market lookups for the WITS step: it can't batch multiple
# reporters into one request (comma-separated reporters get HTTP 400), and
# with 160+ markets a fully serial loop is at the mercy of every individual
# call's timeout. A small thread pool lets slow/stuck calls overlap instead
# of blocking everything behind them.
_TARIFF_MAX_WORKERS = 8


def _tariff_rows_for_market(market_code: str, hs_set: set[str], years_desc: list[int],
                            refresh: bool = False) -> list[dict]:
    reporter = _COMTRADE_TO_WITS_NUMERIC.get(market_code, market_code).zfill(3)

    found: dict[str, float] = {}
    indicator_used = None
    for year in years_desc:
        ahs = _cached_wits_tariffs(reporter, _WITS_AFG_PARTNER, year, refresh=refresh)
        found = {hs: ahs[hs] for hs in hs_set if hs in ahs}
        if found:
            indicator_used = "AHS"
        else:
            mfn = _cached_wits_tariffs(reporter, _WITS_WORLD_PARTNER, year, refresh=refresh)
            found = {hs: mfn[hs] for hs in hs_set if hs in mfn}
            if found:
                indicator_used = "MFN"
        if found:
            if year < years_desc[0]:
                logger.debug(f"WITS: using {year} data for market {market_code}")
            break

    return [
        {
            "market_code": market_code,
            "hs_code": hs,
            "tariff_rate_pct": float(rate),
            "indicator": indicator_used,
            "year": year,
        }
        for hs, rate in found.items()
    ]


def fetch_tariff_rates(market_codes: list[str], hs_codes: list[str],
                       years: list[int], refresh_cache: bool = False) -> list[dict]:
    """
    Fetch tariff rates for the given markets (Comtrade numeric codes) and HS codes.

    Per market, years are tried descending (WITS lags 2–3 years behind trade
    data). Within a year, Afghanistan-specific applied rates ('AHS', partner=004)
    are preferred, falling back to MFN rates (partner=000).

    Downloads are cached per (reporter, partner, year) covering all products,
    on disk as well as in-process, so subsequent runs reuse them too as long
    as the entry is under _WITS_CACHE_TTL old. Pass refresh_cache=True to
    bypass the disk cache and force a fresh fetch regardless of age. Markets
    are looked up concurrently (see _TARIFF_MAX_WORKERS) with progress logged
    periodically.

    Returns list of dicts:
      {market_code: str, hs_code: str, tariff_rate_pct: float,
       indicator: 'AHS'|'MFN', year: int}
    'year' is the actual year the rate was reported for, which is frequently
    earlier than the latest year requested (WITS lag) -- callers should not
    assume it matches whatever year the resulting indicator row is computed for.
    """
    hs_set = {h.replace(".", "") for h in hs_codes}
    years_desc = sorted(years, reverse=True)

    rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=_TARIFF_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_tariff_rows_for_market, market_code, hs_set, years_desc,
                       refresh_cache): market_code
            for market_code in market_codes
        }
        for future in as_completed(futures):
            market_code = futures[future]
            try:
                rows.extend(future.result())
            except Exception as exc:
                logger.warning(f"WITS tariff lookup failed for market {market_code}: {exc}")
            done += 1
            if done % 20 == 0 or done == len(market_codes):
                logger.info(f"  WITS tariffs: {done}/{len(market_codes)} markets processed")

    logger.info(f"WITS tariff fetch complete: {len(rows)} rates across {len(market_codes)} markets")
    return rows


# ── Quantity-unit reference (qtyUnitCode -> label) ─────────────────────────────
# Comtrade's trade-flow API (getFinalData) reliably returns qtyUnitCode (a
# numeric code, e.g. 2) but leaves qtyUnitAbbr (the text label, e.g. "m2")
# blank in practice -- confirmed empirically: Woven Carpets (570210), Italy
# importing from Afghanistan, 2023 returns qtyUnitCode=2, qtyUnitAbbr=None,
# even though Comtrade's own website displays "m2" for that same row. The
# text label lives in a separate reference dataset (comtradeapicall's
# 'qtyunit' category, no subscription key needed) that the website resolves
# client-side but the bulk API does not -- so we fetch and cache that lookup
# table ourselves. Unlike the WITS tariff cache this is small (~40 rows) and
# effectively static, so an in-process cache (refetched once per run) is
# enough -- no disk persistence needed.
#
# Products are fetched concurrently (_PRODUCT_MAX_WORKERS in etl/run.py), so
# the first call from *each* worker thread can race to populate this cache
# at once -- confirmed to happen in practice (a getReference() call from one
# thread hit Comtrade's rate limit while others were in flight). A lock plus
# a double-checked None-check avoids redundant concurrent fetches; failures
# are deliberately *not* written to the cache (same reasoning as the WITS
# disk cache) -- caching a transient 429 as "the labels are {}" would
# silently and permanently blank out unit resolution for every product
# processed afterward in that run, not just the one that hit the limit.
_qty_unit_labels: dict[str, str] | None = None
_qty_unit_labels_lock = threading.Lock()


def _load_qty_unit_labels() -> dict[str, str]:
    global _qty_unit_labels
    if _qty_unit_labels is not None:
        return _qty_unit_labels
    with _qty_unit_labels_lock:
        if _qty_unit_labels is not None:  # another thread just finished while we waited
            return _qty_unit_labels
        try:
            ref = comtradeapicall.getReference("qtyunit")
            labels = {
                str(int(row["qtyCode"])): row["qtyAbbr"]
                for row in ref.to_dict("records")
                if row.get("qtyAbbr") and str(row["qtyAbbr"]).strip().upper() != "N/A"
            }
        except Exception as exc:
            logger.warning(f"Failed to fetch Comtrade quantity-unit reference table: {exc}")
            return {}
        _qty_unit_labels = labels
        return _qty_unit_labels


def _resolve_quantity_units(df: pd.DataFrame) -> pd.Series:
    """
    Resolve a display label per row, preferring qtyUnitAbbr on the rare
    chance the API does populate it directly, falling back to a lookup of
    qtyUnitCode against the reference table otherwise (the common case).

    Built as a plain Python list rather than chained vectorised pandas ops
    (.apply().combine_first()) deliberately: a per-row result that's mostly
    real strings with a handful of None gaps gets inferred by pandas as its
    dedicated string extension dtype, which silently represents those None
    gaps as NaN instead -- and a float NaN landing in a Postgres TEXT column
    doesn't become SQL NULL, it gets adapted to the literal string "NaN"
    (confirmed empirically: 30/1994 competitor_flows rows for Woven Carpets
    ended up with quantity_unit = 'NaN' before this was written as a plain
    list with an explicit object dtype instead).
    """
    def _resolve_one(abbr, code) -> str | None:
        if isinstance(abbr, str) and abbr.strip():
            return abbr
        if code is None or (isinstance(code, float) and pd.isna(code)):
            return None
        try:
            return _load_qty_unit_labels().get(str(int(float(code))))
        except (TypeError, ValueError):
            return None

    abbrs = df["qtyUnitAbbr"] if "qtyUnitAbbr" in df.columns else [None] * len(df)
    codes = df["qtyUnitCode"] if "qtyUnitCode" in df.columns else [None] * len(df)
    values = [_resolve_one(a, c) for a, c in zip(abbrs, codes)]
    return pd.Series(values, index=df.index, dtype=object)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalise_mirror(df: pd.DataFrame, hs_code: str) -> pd.DataFrame:
    """Standardise column names from a mirror-export API response."""
    out = pd.DataFrame()

    # Year
    if "refYear" in df.columns:
        out["year"] = pd.to_numeric(df["refYear"], errors="coerce").astype("Int64")
    elif "period" in df.columns:
        out["year"] = pd.to_numeric(df["period"], errors="coerce").astype("Int64")

    # Importer (reporter in mirror query = the importing country)
    if "reporterCode" in df.columns:
        out["importer_code"] = df["reporterCode"].astype(str)
    elif "reporterISO" in df.columns:
        out["importer_code"] = df["reporterISO"]
    else:
        logger.warning("No reporter column found in mirror response")
        out["importer_code"] = None

    # Importer name (best-effort)
    if "reporterDesc" in df.columns:
        out["importer_name"] = df["reporterDesc"]
    else:
        out["importer_name"] = None

    # Trade value
    if "primaryValue" in df.columns:
        out["trade_value_usd"] = pd.to_numeric(df["primaryValue"], errors="coerce")
    elif "cifvalue" in df.columns:
        out["trade_value_usd"] = pd.to_numeric(df["cifvalue"], errors="coerce")

    # Quantity
    if "qty" in df.columns:
        out["trade_quantity"] = pd.to_numeric(df["qty"], errors="coerce")
    else:
        out["trade_quantity"] = None

    out["quantity_unit"] = _resolve_quantity_units(df)

    # Net weight
    if "netWgt" in df.columns:
        out["net_weight_kg"] = pd.to_numeric(df["netWgt"], errors="coerce")
    else:
        out["net_weight_kg"] = None

    out["hs_code"] = hs_code
    return out.dropna(subset=["year", "importer_code", "trade_value_usd"])
