# Market Intelligence Tool — Data Specification

| Field | Value |
|---|---|
| **Version** | 0.1 (draft) |
| **Status** | Draft — for internal review and ACCI co-design |
| **Date** | 2026-07-01 |
| **Authors** | ICPSD Crisis Resilience team |
| **Parent document** | [SCOPING_NOTE.md](../../SCOPING_NOTE.md) |
| **Related documents** | [FUNCTIONAL_SPECIFICATION.md](./FUNCTIONAL_SPECIFICATION.md) |

---

## 1. Purpose

This Data Specification defines **where data comes from**, **how it is transformed**, **how it is stored**, and **what quality standards apply** for the Market Intelligence Tool. It is the technical companion to the Functional Specification and the basis for ETL development, data licensing review, and ACCI handover planning.

---

## 2. Data architecture overview

```mermaid
flowchart TB
    subgraph sources [External sources]
        Comtrade[UN Comtrade API]
        WB[World Bank API]
        WITS[WITS Tariff API]
        Static[Static lookups in config.py]
        FutureB[Tier B sources - Phase 1 gaps]
        FutureC[Tier C sources - Phase 2-3]
    end
    subgraph etl [ETL pipeline - etl/]
        Fetch[fetch.py]
        Transform[transform.py]
        Load[load.py]
        Run[run.py orchestrator]
    end
    subgraph storage [PostgreSQL]
        Products[products]
        Markets[markets]
        TradeFlows[trade_flows]
        CompFlows[competitor_flows]
        MktContext[market_context]
        Indicators[indicators]
        PipelineRuns[pipeline_runs]
    end
    subgraph api [FastAPI backend]
        Discovery[/api/discover]
        ProductsAPI[/api/products]
    end
    Comtrade --> Fetch
    WB --> Fetch
    WITS --> Fetch
    Static --> Transform
    Fetch --> Transform --> Load --> storage
    storage --> api
    FutureB -.-> Fetch
    FutureC -.-> Fetch
```

**Pattern:** Batch ETL (fetch → transform → load) with pre-computed indicators and scores. The API serves read-only queries against PostgreSQL; no live API calls at request time.

---

## 3. Source inventory

Sources from the scoping note are classified into three tiers based on current integration status and pilot needs.

### 3.1 Tier A — In use (integrated in ETL)

#### UN Comtrade

| Attribute | Value |
|---|---|
| **Provider** | United Nations Statistics Division |
| **API** | Yes — `comtradeapicall` Python package |
| **Access** | Subscription key (`COMTRADE_API_KEY` env var) |
| **Rate limits** | ~1 request/second (enforced by `_API_DELAY = 1.0` in `etl/fetch.py`); exponential backoff on rate-limit errors |
| **Licensing** | UN Comtrade terms of use; redistribution of processed aggregates generally permitted with attribution |
| **Cost** | Free tier available; premium subscription may be needed at scale |
| **Refresh cadence** | Monthly (ETL cron: 1st of month, 02:00 UTC) |
| **Fallback** | None for core trade data; pipeline logs warning and skips product on empty response |

**Data used:**

| Comtrade query | Purpose | Key fields |
|---|---|---|
| Mirror exports (`flow=M`, `partner=AFG`) | Afghanistan's exports to each market (importer reports imports from AFG) | `reporterCode`, `refYear`, `primaryValue`, `qty`, `netWgt` |
| Global imports (`flow=M`, all reporters × all partners) | Market size, competitor supplier breakdown | `reporterCode`, `partnerCode`, `refYear`, `primaryValue`, `qty` |

**Granularity:** 6-digit HS code, annual, bilateral (reporter × partner).

**Years covered:** 2021–2025 (configurable in `config.py` → `YEARS`). Requested directly per year; a given year can return empty if a reporter hasn't submitted data to Comtrade yet.

---

#### World Bank — Development Indicators (WDI + WGI)

| Attribute | Value |
|---|---|
| **Provider** | World Bank |
| **API** | Yes — REST `https://api.worldbank.org/v2` |
| **Access** | No key required |
| **Rate limits** | Gentle throttling (`time.sleep(0.2)` between countries); 60s request timeout per 20-country batch (raised from 30s — see Known Issues below) |
| **Licensing** | Open data; attribution required |
| **Cost** | Free |
| **Refresh cadence** | Monthly (with ETL) |
| **Fallback** | Missing indicators → `NULL` in `market_context`; market quality score defaults to 50 (neutral) |

**Indicators fetched:**

| Internal field | WB indicator code | Description |
|---|---|---|
| `gdp_usd` | `NY.GDP.MKTP.CD` | GDP (current USD) |
| `gdp_per_capita_usd` | `NY.GDP.PCAP.CD` | GDP per capita (current USD) |
| `lpi_score` | `LP.LPI.OVRL.XQ` | Logistics Performance Index (overall) |
| `regulatory_quality` | `GOV_WGI_RQ.SC` | WGI: Regulatory Quality (score, 0-100) |
| `political_stability` | `GOV_WGI_PV.SC` | WGI: Political Stability (score, 0-100) |

**Granularity:** Country (ISO-3), annual.

**Storage:** `market_context` table, keyed by ISO-3 `country_code` — every field keeps its own year here.

**Year resolution on `indicators` (denormalised copy):** `lpi_score`, `regulatory_quality`, and `political_stability` are not published annually without gaps (LPI is triennial, WGI lags 1–2 years), so `_latest_wb_context()` resolves each field *independently* to the latest year ≤ `computed_for_year` with a non-null value. `indicators.lpi_score_year`, `regulatory_quality_year`, and `political_stability_year` (migration 0005) record which year each resolved value actually came from. `gdp_per_capita_usd` has no equivalent `_year` column — it publishes annually with no structural gaps, so a `NULL` there indicates a fetch failure, not a data gap (see Known Issues).

**Known issues:**
- A 30s per-batch timeout (fixed in migration-adjacent code change, 2026-08-05) was silently dropping `gdp_per_capita_usd` for entire 20-country batches on slow responses — confirmed via `etl_run.log` showing repeated `Read timed out` warnings for `NY.GDP.PCAP.CD` chunks including major economies (China, India, Germany, UK, France, Turkey). Raised to 60s. A stale run predating this fix may still have `NULL` `gdp_per_capita_usd` for affected countries until the ETL is re-run.

---

#### WITS (World Integrated Trade Solution)

| Attribute | Value |
|---|---|
| **Provider** | World Bank |
| **API** | Yes — SDMX/JSON `https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN` |
| **Access** | No key required |
| **Rate limits** | One `product/all` call per (reporter, partner, year), cached across products; 0.5s delay between calls |
| **Licensing** | World Bank open data terms |
| **Cost** | Free |
| **Refresh cadence** | Monthly (with ETL) |
| **Fallback** | No tariff data → neutral tariff score (50); `tariff_rate_pct = NULL` |

**Rates used** (selected via the `partner` URL segment; endpoint format is
`reporter/{NUM}/partner/{NUM}/product/{HS6|all}/year/{YYYY}/datatype/reported`
with UN numeric country codes):

| Rate | Partner segment | Description | Priority |
|---|---|---|---|
| `AHS` | `004` (Afghanistan) | Effectively applied tariff, simple average (preferential where a scheme exists) | First |
| `MFN` | `000` (World) | Most-Favoured Nation tariff, simple average | Fallback |

**Strategy:** Per market, for each year (descending, 2025 → 2021), fetch the reporter's full tariff schedule (`product/all`) once per (reporter, partner, year) and cache it across products. If no Afghanistan-specific rates exist, use MFN. WITS data typically lags 2–3 years behind Comtrade, so the year that actually yields data is often earlier than the latest year requested.

**Non-traded goods filter:** WITS reports MFN/Applied rates for a product even when the reporter doesn't actually trade it at all — its own site states this directly ("MFN and Applied Tariff are provided for both traded and non-traded goods") — and the tariff API response carries no "is this traded" flag to distinguish the two. `enrich_indicators_with_scores()` derives that signal from Comtrade instead: a fetched rate is discarded (`tariff_rate_pct`/`tariff_indicator`/`tariff_year` all `NULL`, `has_fta` forced `False`) unless `afg_export_value_usd` shows real Afghan exports to that market — this year, or (same fallback the foothold score uses) historically via `afg_last_export_value_usd`. Applies identically regardless of whether WITS reported the rate as `AHS` or `MFN`.

A rate discarded this way falls back to `score_tariff = 50` (neutral) via the same missing-data handling as any other unscoreable dimension (§4.6) — deliberately not 0. `score_afg_foothold` already scores low for a market with no Afghan trade history; zeroing `score_tariff` for the identical underlying fact would double-count it across two dimensions (22% of the composite combined) and penalize the untapped markets the tool exists to surface.

**Granularity:** 6-digit HS code, country (UN numeric code), annual.

**Storage:** Denormalised into `indicators.tariff_rate_pct`, `indicators.tariff_indicator`, and `indicators.tariff_year` (migration 0004) — the last one records the actual year WITS reported the stored rate for, since it can differ from the row's `computed_for_year`.

---

#### Static lookups (`config.py`)

| Lookup | Keyed by | Purpose | Provenance |
|---|---|---|---|
| `DISTANCE_FROM_KABUL_KM` | Comtrade numeric country code | Proximity scoring | Great-circle capital-to-capital km from CEPII GeoDist (Mayer & Zignago, 2011), joined via `NUMERIC_TO_ISO3`; regenerate with `reference/build_distance_reference.py`. Palestine and Montenegro have no CEPII entry and fall back to a neutral score. |
| `LANGUAGE_SIMILARITY` | Comtrade numeric country code | Language/cultural scoring (0.0–1.0) | Blend of DICL's `lp` (linguistic proximity, weight 0.8) and `cnl` (common native language, weight 0.2) — Gurevich, Herman, Toubal & Yotov (2025), https://doi.org/10.7910/DVN/8WGJTL; regenerate with `reference/build_language_reference.py` |
| `PRODUCTS` | Product name | 34 pilot products with HS codes | UNDP/ACCI product selection |
| `OPPORTUNITY_SCORE_WEIGHTS` | Dimension name | Scoring model weights | Scoping note methodology |

**Limitations:** Static lookups do not auto-update between data-source refreshes — rerun the relevant `reference/build_*.py` script and the ETL to pick up new CEPII/DICL releases.

**Preferential trade access (`has_fta` / `score_fta`)** is no longer a static lookup — it's derived live in `etl/transform.py` (`enrich_indicators_with_scores`) from WITS's own AHS/MFN partner-segment indicator (`indicators.tariff_indicator == 'AHS'`), reusing the same WITS fetch that already powers the tariff dimension rather than a hand-maintained "which FTAs is Afghanistan in" dict. `AHS` means WITS has an Afghanistan-specific applied-tariff record on file for that reporter; it doesn't guarantee that specific rate is lower than the MFN rate (MFN is only fetched as a fallback when AHS is unavailable, not always both), but the actual rate — whichever indicator it came from — is already fully captured in `score_tariff` separately.

---

### 3.2 Tier B — Needed for Phase 1 features (not yet integrated)

| Source | Features blocked | API | Licensing risk | Priority |
|---|---|---|---|---|
| **ITC Trade Map** | Top Importers Directory, buyer contacts | Limited (specific circumstances) | **High** — company data redistribution restricted | Critical |
| **Trade Atlas** | Company-level buyer/supplier search | Yes | **High** — commercial licence | High |
| **Kompass** | B2B buyer directory | Yes | **High** — commercial licence | Medium |
| **Market Access Map (ITC)** | Full tariff breakdown (VAT, fees, NTMs) | No (web only) | Medium — may require ITC partnership | High |
| **EU Access2Markets** | EU regulatory requirements, SPS, labelling | No (web only) | Low — public EU data | High |
| **WTO Tariff & Trade Data (IDB/CTS)** | Bound vs. applied tariffs, import data | Yes | Low — WTO open data | Medium |
| **ACCI Afghanistan** | Afghanistan-specific trade data by industry | No | Unknown — **must confirm with ACCI** | High |
| **NSIA Afghanistan** | Official Afghan trade balance, commodity exports | No | Unknown — government data sharing agreement needed | Medium |

**Action required before build:** Confirm data availability, licensing terms, and redistribution rights for each Tier B source. See §8 Open Questions.

---

### 3.3 Tier C — Phase 2–3 sources (not yet integrated)

| Source | Planned feature | API | Notes |
|---|---|---|---|
| **ITC Export Potential Map** | Market opportunity validation, trade fair recommendations | Limited | Pre-calculated indicators; complements Comtrade |
| **FAO FAOSTAT** | Agricultural commodity prices | Yes | Food/agriculture products only |
| **OEC (Observatory of Economic Complexity)** | Trend forecasts, export potential | Yes | Visualization and trend data |
| **World Bank LPI 2.0** | Route & logistics scoring | No | Latest 2023–2024 dataset; supply-chain tracking |
| **UN ESCAP APTIAD** | Trade agreement details (Asia-Pacific) | No | Agreement-country matrix |
| **WTO SPS/TBT notifications** | Regulatory change alerts | Yes | Sanitary/phytosanitary and technical barriers |

---

## 4. Methodology notes

### 4.1 Mirror statistics for Afghanistan

Afghanistan does **not** report trade data directly to UN Comtrade. The ETL uses **mirror statistics**: for each HS code, it queries all countries' **import** records where Afghanistan (`partnerCode = 4`) is listed as the exporting partner.

```
Importer (reporter) reports: "I imported $X of HS 091020 from Afghanistan"
→ This becomes Afghanistan's export to that importer.
```

This is the standard UN-recommended approach for non-reporting countries. Mirror data may undercount Afghanistan's true exports when:

- Trading partners do not report bilateral detail
- Transit trade is attributed to the transit country, not Afghanistan
- Informal border trade is not captured

**Implication:** Afghan export values should be treated as a **lower bound**, not a complete picture.

### 4.2 Market size calculation

Global market size for a product in a destination market = total imports of that HS code by the market (Comtrade `partnerCode = 0`, i.e. world total as partner).

### 4.3 Competitor identification

For each (product, market) pair, all supplying countries (excluding world total `partnerCode = 0`) are ranked by import value. Top 15 suppliers are stored in `competitor_flows`. Afghanistan's rank among suppliers is stored as `afg_supplier_rank`.

### 4.4 Growth metrics

All four metrics are computed from Afghanistan's own bilateral export value to that one market, year by year — not the market's overall global import growth (that's `global_market_size_usd`, a separate field feeding `score_market_size`).

| Metric | Formula | Notes |
|---|---|---|
| YoY growth | `(value_t − value_{t−1}) / value_{t−1} × 100` | Requires ≥2 years of data. Always the two most recent chronological years — no fallback (see below), since "year over year" is definitionally about consecutive years. |
| CAGR | `(value_last / value_first)^(1/n) − 1) × 100` | `n` = years between first and last. See "CAGR window fallback" below — `first`/`last` are not always simply the earliest/latest year with data. |
| Absolute growth | `value_last − value_first` | USD. Always the full raw first/last data points — see "Why absolute stays on the raw span" below. |
| Growth % | `(value_last − value_first) / value_first × 100`, over the **CAGR-resolved** window | Un-annualized version of the same trend `cagr_pct` describes — see below for why this one moves with the CAGR fallback while Absolute growth doesn't. |

**CAGR window fallback (`_find_sensical_cagr_window()`, `etl/transform.py`):** naively using the literal earliest and latest year with data breaks when one endpoint is a near-zero-base artifact (a single tiny/trace shipment) or an anomalous one-off spike — either can produce a CAGR of thousands of percent that isn't a real trend. Real case: Dried Apricots → France reported $6.35 in 2022, then $72,692.83 / $19,165.71 / $10,423.27 in 2023-2025. The naive 2022→2025 CAGR is +1,080% (an artifact of the $6.35 opening year); dropping 2022 and recomputing 2023→2025 gives −62% — the real trend is a decline, not explosive growth.

The fix: if the naive first/last-year CAGR exceeds ±500% (`etl/transform.py`'s `_MAX_SENSICAL_CAGR_PCT`), retry with a narrower (first_year, last_year) window — widest span first, preferring to trim the earliest year before the latest when spans tie — until one produces a CAGR within that bound, or no window (down to the minimum 2-year span) does, in which case `cagr_pct` is `NULL`. 500% was chosen deliberately loose: it's well above where it would matter to `score_market_growth` anyway (which already saturates at ±20%, so a real 25% CAGR and a fake 100,000% CAGR score identically), so the only job this threshold does is keep the *displayed* `cagr_pct` credible, not affect scoring. Checked against live data (2026-08-28): flags 30 of 691 then-computed `cagr_pct` values (4.3%) for the retry.

`first_year`/`last_year` always describe whichever window `cagr_pct` was ultimately computed over (the frontend shows them as `cagr_pct`'s own sub-label, e.g. "CAGR: 3.6% / 2021–2025") — so if the window narrows, the displayed year range narrows with it, and if no sensical window exists at all, both are `NULL` alongside `cagr_pct` rather than showing a year range for a CAGR that isn't there.

**Why `growth_pct` shares the CAGR window but `absolute_growth_usd` doesn't:** `growth_pct` divides by `value_first` exactly like `cagr_pct` does, so it has the identical near-zero-base blowup vulnerability — before this was fixed, the Dried Apricots/France row above stored `growth_pct = +164,046%` (the same $6.35-base artifact, un-annualized) sitting right next to a correctly-fixed `cagr_pct = −62%`, directly contradicting each other in the same row. `absolute_growth_usd` is a plain subtraction with no such risk, and answers a genuinely different question ("total dollar change across the whole observed history") than the CAGR-window metrics — moving it to the narrower window would also make it `NULL` for a clean `$0 → $1,000` opening year, discarding a real, meaningful fact for no corresponding bug fixed.

### 4.5 Price competitiveness

Afghan unit price = `trade_value_usd / net_weight_kg` (basis `"kg"`), **except** for products in `config.NATIVE_UNIT_PRICE_BASES` (currently `{"m²", "u"}`, i.e. Woven/Knotted Carpets and Cashmere Sweaters) where, if every one of Afghanistan's own rows for that market/year agrees on that exact reported unit, `trade_value_usd / trade_quantity` on that native unit is used instead — see "Native-unit pricing" below for why and when. **No fallback beyond that allowlist** — if neither basis is available (net weight wasn't reported, and no unanimous native unit applies), `unit_price_usd` is `NULL`, not an estimate on some other, unverifiable basis. Each competitor's implied unit price follows the identical two-basis rule, computed on whichever basis Afghanistan's own price used; a competitor missing that basis (no net weight, on the default path; a different or missing `quantity_unit`, on the native-unit path) is excluded from the comparison rather than included on a possibly-incompatible unit.

`unit_price_usd` and `market_avg_price_usd` are always accompanied by `price_basis` (`"kg"` or the native unit actually used, e.g. `"m²"`) — a bare price figure is ambiguous once different products can be priced on different bases; the frontend shows it as a unit suffix (`$45/kg` vs `$120/m²`).

Market average price = mean unit price across the suppliers who *do* have data on the same basis, **after excluding unit-mismatched outliers** (see below). If Afghanistan has no usable basis, or no competitor shares the one it used, `market_avg_price_usd`, `price_vs_market_pct`, and `price_competitiveness` are all `NULL` for that row — see "No fallback policy" below.

| Label | Condition (% vs. market average) |
|---|---|
| Substantially Below Market | < −10% |
| Below Market | −10% to 0% |
| Near Market | 0% to +10% |
| Above Market | > +10% |

Thresholds defined in `config.py` → `PRICE_COMPETITIVENESS`.

**Known limitation — quantity-unit inconsistency across reporters.** Comtrade lets each reporting country submit `trade_quantity` in whatever unit its own customs system uses (kg, m², pieces, ...), and the unit label (`qtyUnitAbbr`) is frequently blank — confirmed empirically for several products in this dataset (e.g. Woven Carpets → Italy, 2025: implied unit price ranged $11.47 to $5,834.57 across suppliers for the same product/market/year, a ~500x spread explainable only by unit mismatch, not real pricing).

*Handling, three parts:*

1. **Use only a consistent basis — no unverified fallback (`_unit_price()` and `_price_competitiveness()`, `etl/transform.py`).** Both default to `net_weight_kg`/`netWgt`. Net weight in kilograms is reported far more consistently across countries than the free-form "quantity" field, which each reporter's customs system expresses in whatever unit it natively uses (kg, m², pieces, ...) — this is the trade-literature's preferred normalisation, not just a workaround (Berthou & Emlinger, *"The Trade Unit Values Database,"* CEPII Working Paper 2011-10, §2.2 and Table 5 — e.g. Germany reports 99.6% of import value in kg vs. the US only 19.5%, for the same product categories; the same paper notes this is also the methodology behind CEPII's BACI database, Gaulier & Zignago 2010). An earlier version of this fix fell back to the ambiguous `trade_quantity`/`qty` field whenever weight was missing — that blanket fallback was deliberately removed: a silent fallback re-introduces the exact unit-mismatch risk this section exists to prevent. Leaving the figure `NULL` is the intended, safer outcome when neither basis below is usable.

   **Native-unit pricing (2026-08).** Once `quantity_unit` started being reliably resolved (via a Comtrade reference-table lookup — `qtyUnitAbbr` itself is blank in practice, see `etl/fetch.py`'s `_load_qty_unit_labels()`), a live check across all 38 products found something the blanket policy above couldn't take advantage of: *when a unit is reported at all, every supplier that reports one agrees on the same unit* — there's no per-product mixing to filter, just a null/non-null split. For most products that unit is `"kg"` anyway, so nothing changes. But for carpets it's `"m²"` and for Cashmere Sweaters it's `"u"` (pieces) — a genuinely more meaningful basis than weight for those goods, not just a different scale of the same thing. `config.NATIVE_UNIT_PRICE_BASES` lists exactly these two; a third consistent case, Lapis Lazuli (Worked) reporting in `"carat"`, was deliberately left off the list — carat is still a weight unit (1kg = 5000 carats exactly), so switching to it wouldn't change the price signal, only add a redundant weight-basis path. `_unit_price()` only takes the native-unit path when **every** row on Afghanistan's side for that market/year agrees on one of these units (`_native_unit_basis()`); any disagreement, or a unit outside the allowlist, falls back to `net_weight_kg` exactly as before. `_price_competitiveness()` then computes competitor prices on that *same* basis Afghanistan's price used — a competitor reporting a different (or no) unit is excluded from that market's comparison rather than mixed in, the same exclusion principle as the weight-basis path.

   *Why this needed a real fix along the way, not just the feature itself:* the reference-table lookup that makes `quantity_unit` resolvable at all first had two bugs worth recording. (1) A `None` result from that lookup could get silently reinterpreted by pandas as a float `NaN` internal to a `.combine_first()` chain, which then round-tripped through Postgres as the literal string `"NaN"` in a `TEXT` column instead of `NULL` — fixed by building the resolved Series from a plain Python list with an explicit `object` dtype instead of chained vectorised ops. (2) Because `etl/run.py` fetches products concurrently (`_PRODUCT_MAX_WORKERS`), several threads raced to populate the same in-process reference-table cache at once; an unsynchronised write from one racing thread that hit Comtrade's rate limit could permanently blank the cache (`{}`) for every product processed afterward in that run — fixed with a lock (`_qty_unit_labels_lock`) plus never caching a failure. Both are covered by regression tests in `tests/test_comtrade_fetch.py` (`TestResolveQuantityUnits`).
2. **Trim what still gets through.** Net weight isn't perfectly guaranteed to be error-free either (a data-entry mistake, or gross-weight-vs-net-weight confusion, can still produce an implausible value even within a nominally consistent unit). `_price_competitiveness()` computes the median unit value across suppliers who reported weight, then excludes any whose implied price falls outside `median × PRICE_OUTLIER_BAND_MULTIPLIER` / `median ÷ PRICE_OUTLIER_BAND_MULTIPLIER` before averaging what remains — the same outlier band CEPII uses when cleaning raw Comtrade unit values (same paper, §2.3 and Appendix A2). `PRICE_OUTLIER_BAND_MULTIPLIER = 10.0` is defined in `config.py` rather than inlined specifically so its sensitivity can be tested — `etl/tests/test_transform.py::TestPriceOutlierBandRobustness` confirms the exclusion outcome is stable across a range of reasonable multipliers (3x–20x), and separately confirms it does start breaking down at an unreasonably generous one (50x) — i.e. 10x isn't an arbitrary pick that happens to work only at that exact value, nor a value assumed to be safe no matter how large.
3. **Leave it undetermined rather than guess (UI).** When `price_competitiveness` is `NULL`, the market profile page shows "No unit data for comparison" instead of a label, plus a short note that this dimension wasn't meaningfully factored into the opportunity score for that row. Backend-side, `_score_price(None)` still returns the same neutral default (50) every other missing dimension in this model uses (§4.6, "Missing data handling") — this fix doesn't change *that* mechanism, it only changes how often a genuinely unverifiable number gets treated as if it were a real one.

Together, (1) and (2) don't recover the *true* unit for every row — that would require either unit labels Comtrade often doesn't provide, or a full mirror-flow-derived conversion-factor exercise (same CEPII paper, §2.2) — so a non-null `price_competitiveness` should still be read as an indicative signal, not a precise measurement; the international statistics literature broadly cautions against treating customs-derived unit values as reliable price proxies even after cleaning (Silver, *"Do Unit Value Export, Import, and Terms of Trade Indices Represent or Misrepresent Price Indices?,"* IMF/UN ECE — unit value indices formally fail the price-index "commensurability" test when units of measurement vary, §III.B).

**A narrower gap the no-fallback policy doesn't close:** the mitigations above only *detect* mismatches where there's a peer group to compare against — that's true for competitors (several suppliers to compare) but never true for Afghanistan's own figure, which is always a single, independently-sourced value regardless of which field it's built from. Removing the `trade_quantity` fallback closes the *loud* failure mode (Afghanistan's number silently computed on an ambiguous unit) — but if Afghanistan's own reported `net_weight_kg` is itself wrong for some other reason (data entry error, gross/net confusion), there's still no second data point to catch that. A genuine fix for that residual case would need a different technique — e.g. cross-checking `unit_price_usd` (from `mirror_df`) against Afghanistan's own entry within the competitor breakdown (`global_df`, a second, independently-fetched source for the same fact) — not yet implemented.

Downstream effects: `unit_price_usd`, `market_avg_price_usd`, `price_vs_market_pct`, `price_competitiveness`, and `score_price_competitiveness` (13% of `opportunity_score`) all inherit this limitation, and are `NULL`/neutral more often now than under the old fallback behaviour (in exchange for those that *aren't* null being more trustworthy). `global_market_size_usd`, `afg_export_value_usd`, `market_share_pct`, and `afg_supplier_rank` are **not** affected — they're computed from `trade_value_usd` alone, never divided by quantity.

### 4.6 Opportunity score computation

Each of eight dimensions is normalised to 0–100, then combined as a weighted sum:

| Dimension | Weight | Normalisation method |
|---|---|---|
| Market size | 20% | Log min-max vs. a fixed floor F: `100 × ln(size/F) / ln(max_size/F)` across all markets for the product — see below |
| Market growth | 18% | Min-max vs. a fixed symmetric band ±W: `50 + cagr_pct × (50/W)`, clamped [0,100] — see below |
| Market quality | 13% | Composite of LPI + regulatory quality + political stability |
| Price competitiveness | 13% | Label-based: Substantially Below Market=100, Below Market=75, Near Market=50, Above Market=25 |
| Tariff | 12% | `max(0, 100 − rate × 3)` — 0% tariff=100, 33%+=0 |
| Afghan foothold | 10% | Log-scaled existing export value |
| Distance | 10% | Inverse distance from Kabul (closer = higher) |
| Language | 4% | `similarity × 100` (0.0–1.0 lookup) |

Weights must sum to 1.0 (enforced in `config.py`).

**FTA access (`score_fta`) is computed but excluded from the composite.** WITS's AFG-specific (`partner=004`) tariff schedule returns "NoRecordsFound" for every reporter checked, so `has_fta` is `False` and `score_fta` is 0 for essentially every row — a weight that could never move the score. Its former 2% share was folded into Tariff (10% → 12%) above. `has_fta`/`score_fta` are still computed per row and stored in `indicators` in case WITS's coverage improves, and remain available via the API, but are no longer part of `opportunity_score` and are not shown in the frontend's score breakdown.

**Missing data handling:** If a dimension cannot be computed (e.g. no WITS tariff), its sub-score defaults to 50 (neutral) and the composite score is still calculated. This avoids excluding markets with data gaps while not over-penalising them. Implemented in `etl/transform.py` (`_score_tariff`, `_score_market_quality`, `_score_distance`, `_score_price`). **Market size and market growth are the two exceptions** — see below.

**Market size normalisation (log min-max against a fixed floor).** `_score_market_size()` (`etl/transform.py`) follows OECD (2008, *Handbook on Constructing Composite Indicators*, Step 5, §5.1): the indicator is log-transformed prior to normalisation to correct positive skew, then normalised by the Min-Max method (§5.3). Departing from the percentile-trimming approach the Handbook also discusses in §5.1, and from Min-Max's usual data-derived minimum, the lower bound is set to a fixed exogenous threshold **F** rather than the observed minimum, following the external-reference logic of §5.4 ("Distance to a reference") — this avoids the instability the Handbook notes for data-derived bounds in §5.3 ("not stable when data for a new time point become available... the composite indicator for the existing data must be re-calculated") without collapsing the ranking of the smallest traders.

`F = MARKET_SIZE_LOG_FLOOR_USD = $500` (`config.py`), fixed across every product and year — not recomputed per product. `v_max` (the log-max denominator) *is* recomputed per product, so the largest market for each product still scores exactly 100. Three distinct states, kept apart deliberately:
- `global_market_size_usd` is `NULL` (no data at all): `score_market_size` is `NULL`, excluded from the composite (see renormalisation below) — rather than guessing a neutral default the way most other dimensions do. (In practice this doesn't currently occur — every scored row has a real market size — but the pipeline handles it correctly if a future data gap produces one.)
- `global_market_size_usd == 0` (a genuine reported zero): scores 0.
- `0 < global_market_size_usd ≤ F`: real but below the noise floor — clipped to 0 rather than going negative.

**Market growth normalisation (Min-Max against a fixed symmetric band).** `_score_growth()` (`etl/transform.py`) is the *same* method as market size, applied more directly: plain Min-Max (OECD §5.3) with a fixed external reference range `[-W, +W]` (§5.4) instead of the observed sample min/max. Substituting `min=-W, max=+W` into the general Min-Max formula `(x-min)/(max-min)×100` algebraically simplifies to `50 + cagr_pct×(50/W)` — the `50` isn't a separate constant tacked onto a made-up formula, it's the direct consequence of Min-Max applied to a range centred at zero (0% CAGR, the natural "no growth" point, lands exactly on the output scale's own midpoint).

`W = CAGR_SCORE_BAND_PCT` (`config.py`), fixed across every product and year, same stability rationale as `F` above. **Derived 2026-08-30**, widened from the original `W=20`: pooling `cagr_pct` across every row with a resolved CAGR (n=665) showed p10=−52%, p25=−22%, median=+7.2%, p75=+56%, p90=+129% — `W=20` clamped 446/665 rows (67%) to a flat 0 or 100, providing almost no differentiation between markets. `W=75` sits close to the data's actual P75/\|P25\| spread and clamps only 167/665 (25%). Checked against a chart comparing ±20/±50/±75/±100 side by side before choosing.

`cagr_pct` is `NULL` (no data at all, not a genuine 0% reading) returns `NULL` for `score_market_growth`, excluded from the composite the same way `score_market_size` is — not the neutral-50 default most other dimensions use, since there's no principled "average" CAGR to assume for a market with no growth data at all.

**Renormalisation when market size and/or market growth are missing:** the composite is computed by summing each *present* dimension's `score × weight` and dividing by the sum of only the *present* dimensions' weights — so if one is missing, the remaining weights are rescaled to sum back to 1.0; if both are missing, the remaining 6 dimensions' weights rescale together. This generalises rather than special-casing "market size missing" and "market growth missing" separately (`etl/transform.py`, `enrich_indicators_with_scores`).

**F's derivation:** pooled `global_market_size_usd` across every scored product/market row (n=1042, 2026-08-28) and looked for where real trade ends and rounding/reporting noise begins. The data shows a ~3.5× gap between three likely-noise values under $200 (Saffron/Kyrgyzstan $94, Apricots/Yemen $132, Dried Apricots/Yemen $160) and a continuous cluster of plausible small-but-real markets starting at $562 (Dried Figs/Liberia). F=$500 sits just below that cluster: it clips the 3 likely-noise values to 0 while every other observed market scores positive (no real trader clipped). Checked at F=$100/$500/$1,000/$2,000 against Dried Figs (leader: India, $207.8M) — at F=$1,000, Liberia's real $562 market clips to 0; at F=$500 it scores a small but positive 0.9, which is the intended "tiny but real" signal.

**F is fixed, not recomputed per ETL run.** Recalculating it fresh from each run's data would reintroduce exactly the instability OECD §5.3 warns about — the same market could score differently month to month purely because the bound moved, not because anything about the market changed. Instead, `etl.verify`'s `check_market_size_floor_calibration()` runs on every ETL and reports (as a `WARNING`, not a hard failure) how many real markets are clipping at the floor — a small, stable count (the 3 above) is expected; a growing one signals the data's scale has shifted and F should be manually re-derived using the same process described above, following the same "flag for human review, don't auto-correct" pattern as `check_score_bounds`.

### 4.7 Country code conventions

The system uses **two country code systems** that must be kept consistent:

| Context | Code system | Example (India) |
|---|---|---|
| Comtrade trade flows, indicators, competitor flows | UN M49 numeric (string) | `"699"` or `"356"` |
| World Bank, WITS tariffs, `market_context` | ISO 3166-1 alpha-3 | `"IND"` |
| `markets.country_code` | UN M49 numeric (string) | `"699"` |

**Known issue:** Comtrade sometimes returns placeholder country names (`"None"`, raw numeric codes). The ETL and API layer use `backend/country_names.py` → `resolve_country_name()` to display human-readable names at ingestion and read time.

**Rule for new development:** Store Comtrade M49 numeric codes in trade-related tables; store ISO-3 in World Bank / WITS tables; maintain a mapping table or lookup function between the two.

---

## 5. Data dictionary

### 5.1 `products`

Pilot product catalogue. Seeded from `config.py` → `PRODUCTS` on ETL run.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | INTEGER | PK | Auto-increment |
| `name` | TEXT | NOT NULL, UNIQUE | Display name (e.g. "Saffron") |
| `category` | TEXT | NOT NULL | Product category (e.g. "Spices & Herbs") |
| `hs_codes` | TEXT[] | NOT NULL | One or more 6-digit HS codes (no dots) |
| `description` | TEXT | Yes | Short product description |

**Source:** `config.py` (static, version-controlled).

---

### 5.2 `markets`

Reference table of trading partner countries.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | INTEGER | PK | Auto-increment |
| `country_code` | TEXT | NOT NULL, UNIQUE | UN M49 numeric code (string) |
| `country_name` | TEXT | Yes | Display name |
| `region` | TEXT | Yes | Geographic region (not yet populated) |

**Source:** Derived from Comtrade reporter codes encountered during ETL.

---

### 5.3 `market_context`

World Bank development indicators per country per year.

| Column | Type | Nullable | Description | Source |
|---|---|---|---|---|
| `id` | INTEGER | PK | Auto-increment | — |
| `country_code` | TEXT | NOT NULL | ISO-3 alpha code | World Bank |
| `year` | INTEGER | NOT NULL | Data year | World Bank |
| `gdp_usd` | NUMERIC(20,2) | Yes | GDP, current USD | `NY.GDP.MKTP.CD` |
| `gdp_per_capita_usd` | NUMERIC(20,2) | Yes | GDP per capita, current USD | `NY.GDP.PCAP.CD` |
| `lpi_score` | NUMERIC(5,3) | Yes | Logistics Performance Index | `LP.LPI.OVRL.XQ` |
| `regulatory_quality` | NUMERIC(6,3) | Yes | WGI regulatory quality score (0-100) | `RQ.SC` |
| `political_stability` | NUMERIC(6,3) | Yes | WGI political stability score (0-100) | `PV.SC` |
| `fetched_at` | TIMESTAMPTZ | NOT NULL | ETL fetch timestamp | System |

**Unique key:** (`country_code`, `year`).

---

### 5.4 `trade_flows`

Afghanistan's mirror export flows: one row per (product, importer, year).

| Column | Type | Nullable | Description | Source |
|---|---|---|---|---|
| `id` | INTEGER | PK | Auto-increment | — |
| `product_id` | INTEGER | FK → products | Product reference | — |
| `importer_code` | TEXT | NOT NULL | Importing country (M49 numeric) | Comtrade `reporterCode` |
| `importer_name` | TEXT | Yes | Importing country name | Comtrade `reporterDesc` |
| `year` | INTEGER | NOT NULL | Trade year | Comtrade `refYear` |
| `trade_value_usd` | NUMERIC(20,2) | Yes | Trade value, USD | Comtrade `primaryValue` |
| `trade_quantity` | NUMERIC(20,4) | Yes | Quantity traded | Comtrade `qty` |
| `quantity_unit` | TEXT | Yes | Unit of quantity | Comtrade `qtyUnitAbbr`, resolved from `qtyUnitCode` against Comtrade's reference table when `qtyUnitAbbr` is blank (the common case) -- `etl/fetch.py`'s `_resolve_quantity_units()` |
| `net_weight_kg` | NUMERIC(20,4) | Yes | Net weight, kg | Comtrade `netWgt` |
| `fetched_at` | TIMESTAMPTZ | NOT NULL | ETL fetch timestamp | System |

**Unique key:** (`product_id`, `importer_code`, `year`).

---

### 5.5 `competitor_flows`

Supplier countries exporting a product to a given market.

| Column | Type | Nullable | Description | Source |
|---|---|---|---|---|
| `id` | INTEGER | PK | Auto-increment | — |
| `product_id` | INTEGER | FK → products | Product reference | — |
| `market_code` | TEXT | NOT NULL | Importing market (M49 numeric) | Comtrade `reporterCode` |
| `year` | INTEGER | NOT NULL | Trade year | Comtrade `refYear` |
| `supplier_code` | TEXT | NOT NULL | Exporting country (M49 numeric) | Comtrade `partnerCode` |
| `supplier_name` | TEXT | NOT NULL | Exporting country name | Comtrade `partnerDesc` |
| `trade_value_usd` | NUMERIC(20,2) | Yes | Import value from this supplier, USD | Comtrade `primaryValue` |
| `trade_quantity` | NUMERIC(20,4) | Yes | Quantity | Comtrade `qty` |
| `quantity_unit` | TEXT | Yes | Unit of quantity | Same resolution as `trade_flows.quantity_unit` above |

**Unique key:** (`product_id`, `market_code`, `supplier_code`, `year`).

---

### 5.6 `indicators`

Pre-computed trade indicators and opportunity scores. One row per (product, market, year). This is the primary table served by the discovery API.

| Column | Type | Description | Source |
|---|---|---|---|
| `id` | INTEGER PK | Auto-increment | — |
| `product_id` | INTEGER FK | Product reference | — |
| `market_code` | TEXT | Market country code (M49 numeric) | Comtrade |
| `computed_for_year` | INTEGER | Year the indicators are computed for | ETL (latest in `YEARS`) |
| **Trade indicators** | | | |
| `global_market_size_usd` | NUMERIC(20,2) | Total market imports of product, USD | Comtrade (world total) |
| `afg_export_value_usd` | NUMERIC(20,2) | Afghanistan exports to market, USD | Comtrade (mirror) |
| `yoy_growth_pct` | NUMERIC(10,4) | Year-on-year export growth % | Computed |
| `cagr_pct` | NUMERIC(10,4) | Compound annual growth rate % | Computed |
| `absolute_growth_usd` | NUMERIC(20,2) | Absolute export growth, USD | Computed |
| `growth_pct` | NUMERIC(10,4) | Total growth % over period | Computed |
| `first_year` | INTEGER | First year in growth calculation | Computed |
| `last_year` | INTEGER | Last year in growth calculation | Computed |
| `market_share_pct` | NUMERIC(10,6) | Afghanistan's share of market imports % | Computed |
| `afg_supplier_rank` | INTEGER | Afghanistan's rank among suppliers | Computed |
| `unit_price_usd` | NUMERIC(20,6) | Afghan unit price, USD | Computed |
| `price_basis` | TEXT | What `unit_price_usd`/`market_avg_price_usd` are priced per -- `"kg"` or a native unit from `config.NATIVE_UNIT_PRICE_BASES` (e.g. `"m²"`); see §4.5 | Computed |
| `market_avg_price_usd` | NUMERIC(20,6) | Market average unit price, USD, same basis as `price_basis` | Computed |
| `price_vs_market_pct` | NUMERIC(10,4) | Afghan price vs. market average % | Computed |
| `price_competitiveness` | TEXT | Competitiveness label | Computed |
| **Opportunity score** | | | |
| `opportunity_score` | NUMERIC(5,2) | Composite score 0–100 | Computed |
| **Static context** | | | |
| `distance_km` | INTEGER | Distance from Kabul, km | `config.py` |
| `has_fta` | BOOLEAN | Preferential trade access exists | `config.py` |
| `language_similarity` | NUMERIC(4,3) | Language similarity 0.0–1.0 | `config.py` |
| **World Bank context (denormalised)** | | | |
| `gdp_per_capita_usd` | NUMERIC(20,2) | GDP per capita | World Bank |
| `lpi_score` | NUMERIC(5,3) | Logistics Performance Index | World Bank |
| `lpi_score_year` | INTEGER | Year `lpi_score` was actually reported for (LPI is triennial — can lag `computed_for_year`) | World Bank |
| `regulatory_quality` | NUMERIC(6,3) | Regulatory quality score (0-100) | World Bank |
| `regulatory_quality_year` | INTEGER | Year `regulatory_quality` was actually reported for (WGI lags 1–2 years) | World Bank |
| `political_stability` | NUMERIC(6,3) | Political stability score (0-100) | World Bank |
| `political_stability_year` | INTEGER | Year `political_stability` was actually reported for | World Bank |
| **WITS tariff** | | | |
| `tariff_rate_pct` | NUMERIC(6,3) | Import tariff rate % | WITS |
| `tariff_indicator` | TEXT | `'AHS'` (preferential) or `'MFN'` (general) | WITS |
| `tariff_year` | INTEGER | Year WITS actually reported the rate for (can be earlier than `computed_for_year` — WITS lags) | WITS |
| **Sub-scores (0–100 each)** | | | |
| `score_market_size` | NUMERIC(5,2) | Market size dimension score | Computed |
| `score_market_growth` | NUMERIC(5,2) | Market growth dimension score | Computed |
| `score_market_quality` | NUMERIC(5,2) | Market quality dimension score | Computed |
| `score_price_competitiveness` | NUMERIC(5,2) | Price competitiveness dimension score | Computed |
| `score_afg_foothold` | NUMERIC(5,2) | Afghan foothold dimension score | Computed |
| `score_distance` | NUMERIC(5,2) | Proximity dimension score | Computed |
| `score_language` | NUMERIC(5,2) | Language dimension score | Computed |
| `score_fta` | NUMERIC(5,2) | FTA access dimension score — stored but not weighted into `opportunity_score` (§4.6) | Computed |
| `score_tariff` | NUMERIC(5,2) | Tariff dimension score | Computed |
| `computed_at` | TIMESTAMPTZ | Timestamp of computation | System |

**Unique key:** (`product_id`, `market_code`, `computed_for_year`).

**Note:** World Bank fields are denormalised from `market_context` for query efficiency. Tariff and static context are similarly denormalised.

---

### 5.7 `pipeline_runs`

ETL execution audit log.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `run_at` | TIMESTAMPTZ | Run start timestamp |
| `status` | TEXT | `'success'`, `'partial'`, or `'failed'` |
| `products_updated` | INTEGER | Count of products successfully processed |
| `errors_json` | JSONB | Error details per product (if any) |

---

## 6. Refresh and retention

| Parameter | Value |
|---|---|
| **ETL schedule** | Monthly — 1st of month, 02:00 UTC (GitHub Actions `etl.yml`) |
| **Manual trigger** | `docker-compose exec backend python -m etl.run` |
| **Years retained** | 2021–2025 (configurable via `config.YEARS`) |
| **Upsert strategy** | Idempotent — `load.py` upserts on unique keys; re-running ETL replaces existing rows |
| **Partial runs** | Supported: `--products "Saffron" "Dried Grapes (Raisins)"` |
| **Skip flags** | `--skip-world-bank`, `--skip-tariffs`, `--dry-run` |
| **Retention policy** | All years in `YEARS` are kept; older years are not automatically purged |
| **Audit trail** | Every ETL run logged in `pipeline_runs` with status and error details |

### ETL orchestration flow

```
etl.run
  ├── Phase A: fetch_world_bank_indicators(country_codes, years)  [unless --skip-world-bank]
  │     └── build market_context lookup (used by all products)
  ├── Phase B: For each product in config.PRODUCTS (or --products filter):
  │     ├── fetch_mirror_exports(hs_code, years)
  │     ├── fetch_global_imports(hs_code, years)
  │     ├── transform → trade_flows, competitor_flows, indicators
  │     ├── fetch_tariff_rates(market_codes, hs_codes, years)  [unless --skip-tariffs; per product]
  │     ├── enrich_indicators_with_scores(static lookups, WB context, WITS tariffs)
  │     └── load → upsert to PostgreSQL
  └── log pipeline_run(status, products_updated, errors)
```

---

## 7. Data quality rules

The ETL and API layers should enforce or validate the following rules. Rules marked **Enforced** are implemented today; **Planned** are recommended additions.

| # | Rule | Severity | Status |
|---|---|---|---|
| DQ-1 | `OPPORTUNITY_SCORE_WEIGHTS` values must sum to 1.0 ± 0.001 | Error | **Enforced** (config) |
| DQ-2 | `opportunity_score` must be in [0, 100] when not NULL | Error | **Enforced** (transform) |
| DQ-3 | All `score_*` sub-scores must be in [0, 100] | Error | **Enforced** (transform) |
| DQ-4 | `trade_value_usd` must be ≥ 0 when not NULL | Error | **Planned** |
| DQ-5 | `tariff_rate_pct` must be in [0, 100] when not NULL | Warning | **Planned** |
| DQ-6 | `market_code` / `importer_code` / `supplier_code` must resolve to a known country via `resolve_country_name()` | Warning | **Partial** (display layer only) |
| DQ-7 | `computed_for_year` must be in `config.YEARS` | Error | **Enforced** (ETL) |
| DQ-8 | Each product must have ≥ 1 market with a non-NULL `opportunity_score` after ETL | Warning | **Planned** (post-ETL check) |
| DQ-9 | `pipeline_runs.status` must be `'failed'` if any product errors occurred | Error | **Enforced** (ETL) |
| DQ-10 | Duplicate rows on unique keys must be upserted, not inserted | Error | **Enforced** (load.py) |
| DQ-11 | WITS tariff indicator must be `'AHS'` or `'MFN'` when `tariff_rate_pct` is not NULL | Warning | **Planned** |
| DQ-12 | Mirror export value for a market should not exceed global market size for that market | Warning | **Planned** (sanity check) |

### Recommended post-ETL validation report

After each ETL run, generate a summary:

- Products processed / failed
- Markets scored per product
- % of markets with missing tariff data
- % of markets with missing World Bank context
- Top 5 markets by score per product (spot-check)
- Any DQ rule violations

---

## 8. Open questions

These questions from the scoping note and data review must be resolved before Phase 1 features depending on external data can be built.

| # | Question | Impact | Owner |
|---|---|---|---|
| OQ-1 | **Which ACCI data is currently available for our use?** (trade by industry, by destination) | Could supplement or validate Comtrade mirror data; may enable Afghanistan-specific insights | ACCI / UNDP |
| OQ-2 | **Can we collect primary data through ACCI?** (surveys, exporter registrations) | Would enable data not available from international sources | ACCI / UNDP |
| OQ-3 | **How to transfer subscription-based API data at handover?** (Comtrade key, ITC access, Trade Atlas) | Blocks sustainable operations post-UNDP; must be in handover plan | UNDP / ACCI |
| OQ-4 | **What are the redistribution terms for ITC Trade Map company data?** | Blocks Top Importers Directory (FR-3.x) | ITC / UNDP legal |
| OQ-5 | **Is a Trade Atlas or Kompass commercial licence feasible within project budget?** | Alternative source for buyer directory | UNDP procurement |
| OQ-6 | **Can VAT and port fee data be sourced from Market Access Map or EU Access2Markets?** (no API) | Blocks full Customs & Tariff Breakdown (FR-2.4) | UNDP / ITC |
| OQ-7 | **Should methodology version be stored alongside scores?** (for historical comparability when weights change) | Data model change; recommended yes | Engineering |
| OQ-8 | **What is the canonical country code mapping between M49 numeric and ISO-3?** | Ongoing data quality issue (`backend/country_names.py`) | Engineering |

---

## 9. Environment variables

| Variable | Required | Description |
|---|---|---|
| `COMTRADE_API_KEY` | Yes | UN Comtrade subscription key |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Docker only | PostgreSQL password for Docker Compose |

No API keys are currently required for World Bank or WITS.

---

## 10. Document history

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-07-01 | ICPSD Crisis Resilience team | Initial draft from scoping note, ETL pipeline, and database schema |
