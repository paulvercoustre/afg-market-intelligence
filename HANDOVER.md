# AFG Market Diversification Tool — Colleague Handover

A walkthrough guide for onboarding. The tool helps Afghan exporters and UNDP trade analysts discover and rank new export markets for Afghan products, modelled on the [US trade.gov Market Diversification Tool](https://www.trade.gov/market-diversification-tool).

---

## 1. Prerequisites & Getting Started

### What you need installed

| Tool | Version / notes |
|------|-----------------|
| **Docker + Docker Compose** | Runs Postgres and the FastAPI backend |
| **Node.js + npm** | For local frontend dev (`frontend/`) |
| **Python 3.12** | For running tests/lint locally without Docker |
| **UN Comtrade API key** | Required for ETL — [register here](https://unstats.un.org/wiki/display/comtrade/UN+Comtrade+API) |

No API key is needed for World Bank or WITS — those are public endpoints.

### Environment setup

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `COMTRADE_API_KEY` | Yes | UN Comtrade subscription key |
| `DATABASE_URL` | Yes (local dev) | `postgresql://postgres:postgres@localhost:5432/afg_market` |
| `POSTGRES_PASSWORD` | Docker only | Defaults to `postgres` |

### Start the project

**Recommended setup** — DB + backend in Docker, frontend locally (hot reload):

```bash
# 1. Start database and backend only
docker-compose up -d --build db backend

# 2. Run the ETL to populate data (first time, or after a rebuild)
docker-compose exec backend python -m etl.run

# 3. Start the frontend dev server
cd frontend
npm install   # first time only
npm run dev
```

Then open:
- **Frontend:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

The backend container runs `alembic upgrade head` automatically on startup, applying migrations 0001–0004.

### Rebuild the database from scratch

Use this when you want a clean slate (e.g. after schema changes, or to re-ingest with updated ETL logic):

```bash
# Wipe all data and recreate Postgres
docker-compose down -v

# Start fresh (migrations run on backend startup)
docker-compose up -d --build db backend

# Repopulate
docker-compose exec backend python -m etl.run
```

A full ETL run fetches all 29 products × 5 years (2021–2025) from Comtrade, plus World Bank indicators and WITS tariffs — expect it to take a while. Products are fetched concurrently (`_PRODUCT_MAX_WORKERS = 3` in `etl/run.py`) rather than one at a time. Useful shortcuts:

```bash
# One product only
docker-compose exec backend python -m etl.run --products Saffron

# Skip slow fetches while testing
docker-compose exec backend python -m etl.run --skip-tariffs
docker-compose exec backend python -m etl.run --skip-world-bank
```

### Run tests and lint (no Docker needed)

```bash
pip install -r requirements.txt
pytest backend/tests/ -v    # 47 tests, uses in-memory SQLite
ruff check .
```

`tests/test_comtrade_fetch.py` covers the Comtrade response-parsing layer (the one external source that previously had no fetch-layer tests, unlike WITS/World Bank). `etl/tests/test_run.py` covers both failure resilience (a single HS code's fetch failing, or an entire product's `run_product()` crashing, must not take down the rest of the run) and the five pure helper functions that decide which markets get scored/detailed and how tariffs are averaged across HS codes (`_all_market_codes`, `_top_market_codes`, `_market_sizes_by_code`, `_resolve_market_name`, `_fetch_tariffs_for_product`) — previously untested. `etl/tests/test_pipeline_integration.py` runs the real fetch → transform → load chain together against Postgres (only the Comtrade HTTP call is mocked) to catch boundary bugs none of the per-layer tests can see. `etl/tests/test_verify.py` proves each of `etl/verify.py`'s checks (the ones now gating `etl.yml`) both stays quiet on clean data and actually fires when a specific problem is seeded — negative values, mismatched supplier codes, a wrong `market_share_pct`, an out-of-range score — rather than just always returning empty. All of these run as part of the normal `pytest -v`; the Postgres-backed ones (`test_load.py`, `test_pipeline_integration.py`, `test_verify.py`) need `TEST_DATABASE_URL` (see `test_load.py`'s docstring) and skip automatically without it.

**Note:** fixing this uncovered a real bug in `migrations/env.py` — `fileConfig()` was silently disabling every Python logger not explicitly listed in `alembic.ini` (only `root`/`sqlalchemy`/`alembic` are), which broke `etl.run`'s own logging the moment any test ran a migration earlier in the same process. Fixed with `disable_existing_loggers=False`. This would only bite anything that runs Alembic migrations programmatically inside a longer-lived process — the Docker `alembic upgrade head` step runs as its own short-lived process, so production was never affected — but it's worth knowing about if logging ever goes quiet after a migration runs in-process somewhere else.

`etl/tests/test_load.py` tests the real Postgres upsert SQL in `etl/load.py` (13 tests) — the rest of the suite only ever runs against SQLite or plain Python objects, so it can't catch a column dropped from an `INSERT` list. These are skipped automatically unless `TEST_DATABASE_URL` points at a real, throwaway Postgres:

```bash
docker compose up -d db_test
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/afg_market_test
pytest etl/tests/test_load.py -v
```

CI runs them automatically against a Postgres service container — see `.github/workflows/ci.yml`.

Data verification (separate from the pytest suite — checks a live/populated DB, optionally against the source APIs):

```bash
python -m etl.verify                     # internal sanity checks only (DB-only, fast)
python -m etl.verify --spot-check         # also re-fetch a live sample and diff against stored values
python -m etl.verify --spot-check-n 10    # sample size (default 5)
```

### Key API endpoints to try

```
GET /api/products                          → All products with top market
GET /api/products/091020                   → Saffron detail
GET /api/discover/091020                   → Ranked markets for Saffron
GET /api/discover/091020/markets/699       → Full market profile (India)
GET /api/indicators                        → Metric definitions for tooltips
```

---

## 2. Architecture Overview

### Data flow

```mermaid
flowchart LR
    subgraph sources [External APIs]
        C[UN Comtrade]
        WB[World Bank WDI/WGI]
        WITS[WITS Tariffs]
    end

    subgraph etl [ETL Pipeline]
        F[etl/fetch.py]
        T[etl/transform.py]
        L[etl/load.py]
        R[etl/run.py]
    end

    DB[(PostgreSQL)]
    API[FastAPI backend]
    UI[Next.js frontend]

    C --> F
    WB --> F
    WITS --> F
    F --> T --> L --> DB
    R -. orchestrates .-> F
    R -. orchestrates .-> T
    R -. orchestrates .-> L
    DB --> API --> UI
```

1. **`etl/run.py`** orchestrates the pipeline per product
2. **`etl/fetch.py`** pulls raw data from Comtrade, World Bank, and WITS
3. **`etl/transform.py`** normalises data, computes trade indicators, and calculates the 9-dimension opportunity score
4. **`etl/load.py`** idempotently upserts into Postgres
5. **`backend/`** serves ranked markets and market profiles via REST
6. **`frontend/`** renders the discovery UI (product browse → ranked markets → market profile)

### Docker services

| Service | Port | Role |
|---------|------|------|
| `db` | 5432 | PostgreSQL 16, database `afg_market` |
| `backend` | 8000 | FastAPI app, runs migrations on start |
| `frontend` | 3000 | Next.js production build (optional — use `npm run dev` instead) |

### Key directories

```
config.py                  # Products, score weights, distance/language/FTA lookups
etl/
  fetch.py                 # Comtrade + World Bank + WITS API clients
  transform.py             # Indicator computation + opportunity scoring
  load.py                  # PostgreSQL upserts
  run.py                   # CLI orchestrator
backend/
  routers/                 # HTTP endpoints (discovery, products, meta)
  services/                # Query logic + next-step recommendations
  country_names.py         # UN M49 code → country name resolution
  models.py / schemas.py    # ORM + API response types
  tests/test_api.py        # Contract tests (SQLite, no Docker)
frontend/
  app/                     # Next.js pages (product grid, discover, market profile)
  components/              # ScoreBadge, ScoreBar, ProductGrid, etc.
  lib/api.ts               # Backend fetch client
migrations/versions/       # Alembic schema (0001–0004)
indicator_definitions.json # Tooltip text for UI metrics
```

### CI/CD

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `.github/workflows/ci.yml` | Push/PR to `main` or `claude/**` | `ruff check` + `pytest backend/tests/` |
| `.github/workflows/etl.yml` | Monthly cron (1st of month, 02:00 UTC) + manual | Full ETL run (needs `COMTRADE_API_KEY` secret) |

---

## 3. Data Sources

### UN Comtrade — trade flows (primary source)

Afghanistan does **not** report directly to Comtrade. The pipeline uses **mirror statistics**: it queries other countries' import records where Afghanistan is the exporting partner.

Two fetch patterns per HS code (in `etl/fetch.py`):

| Function | What it fetches | Used for |
|----------|------------------|----------|
| `fetch_mirror_exports` | All countries' imports **from** Afghanistan | Afghan export values per market |
| `fetch_global_imports` | All reporters × all partners for the HS code | Global market size, competitor supplier flows |

- Years: **requested** 2021–2025 (`config.py` → `YEARS`) — sent to Comtrade as-is; a given year can still come back empty if a reporter hasn't submitted data yet
- Country codes: UN M49 numeric (e.g. `276` = Germany, `699` = India)
- Rate limiting: 1-second delay between API calls, exponential backoff on errors

**Stored in:**
- `trade_flows` — per-product, per-importer, per-year import values
- `competitor_flows` — top suppliers to each market (partner breakdown)
- `markets` — country code + resolved country name
- `indicators` — computed metrics and scores (see below)

### World Bank — market quality context

Fetched per country via `fetch_world_bank_indicators()` in `etl/fetch.py`:

| Indicator | WB code | Used for |
|-----------|---------|----------|
| GDP (current USD) | `NY.GDP.MKTP.CD` | Stored on indicators (context) |
| GDP per capita | `NY.GDP.PCAP.CD` | Stored on indicators (context) |
| Logistics Performance Index | `LP.LPI.OVRL.XQ` | Market quality score (1–5 scale) |
| Regulatory Quality | `GOV_WGI_RQ.EST` (WGI) | Market quality score (-2.5 to 2.5) |
| Political Stability | `GOV_WGI_PV.EST` (WGI) | Market quality score (-2.5 to 2.5) |

Requested as a single `2021:2025` date range per indicator; WB doesn't publish evenly across it (LPI is only released in select years, WGI typically lags 1–2 years), so actual per-country/year coverage is whatever the API returns.

Stored in `market_context` table (migration 0002), keyed by ISO-3 country code and year — every field keeps its own year there, so this table is always the authoritative source for "what year did this value come from."

When denormalized onto `indicators` (see below), `_latest_wb_context()` in `etl/transform.py` resolves each field **independently** to the latest year ≤ `computed_for_year` — e.g. if `lpi_score` is null for 2024/2025 but present for 2022, the 2022 value is used while `regulatory_quality` might still come from 2024. `indicators.lpi_score_year`, `regulatory_quality_year`, and `political_stability_year` (migration 0005) record which year each resolved value actually came from — the same idea as `tariff_year` below, applied to World Bank fields. `gdp_per_capita_usd` doesn't get this treatment: it's requested for every year with no publishing gaps, so a missing value there means the *fetch* failed, not that the data doesn't exist (see the 60s timeout fix just below — a 30s timeout was silently dropping GDP-per-capita for ~40 major economies, confirmed via `etl_run.log`, because a 20-country × 5-year chunk response routinely took longer than 30s).

### WITS — tariff rates

Fetched via `fetch_tariff_rates()` in `etl/fetch.py`:

- Tries **AHS** first (effectively applied tariff with Afghanistan as partner, partner code `004` — captures preferential/FTA rates)
- Falls back to **MFN** (general rate, partner code `000`) when no Afghanistan-specific rate is reported
- No bulk/`reporter=ALL` fetch — WITS rejects that (400/403). Each market is fetched individually, in parallel via an 8-worker thread pool (`_TARIFF_MAX_WORKERS` in `etl/fetch.py`), with the full per-(reporter, partner, year) schedule cached so all HS codes in a product share one download
- Walks backward through `YEARS` descending (2025 → 2021) per market until it finds reported data (WITS typically lags 2–3 years behind Comtrade)

Stored as columns on the `indicators` table: `tariff_rate_pct`, `tariff_indicator` (migration 0003), and `tariff_year` (migration 0004) — the actual year WITS reported the rate for, which is frequently earlier than the row's `computed_for_year` because of the lag above. Without `tariff_year` there was no way to tell, from the data alone, how stale a given market's tariff rate actually is.

### Static lookups (no API)

Defined in `config.py`:

| Lookup | Purpose |
|--------|---------|
| `DISTANCE_FROM_KABUL_KM` | Straight-line km from Kabul to ~60 trading partners |
| `LANGUAGE_SIMILARITY` | 0.0–1.0 score based on Dari/Pashto trade-communication overlap |
| `FTA_STATUS` | Afghanistan's preferential access (SAPTA, ECO, EU/UK GSP+) |

### Products tracked

38 products across 39 unique HS codes (Fenugreek and Liquorice Root intentionally share `121190` — see README for why), defined in `config.py` → `PRODUCTS`:

| Category | Examples |
|----------|----------|
| Tree Nuts | Almonds, Walnuts, Pistachios, Pine Nuts |
| Spices & Herbs | Saffron, Cumin, Fenugreek, Asafoetida, Liquorice Root, Liquorice Extract |
| Dried Fruits | Raisins, Dried Apricots, Dried Figs, Dried Pomegranate |
| Fresh Fruits | Fresh Grapes, Fresh Pomegranate, Watermelons, Melons, Apricots, Mulberries (Fresh), Mulberries (Prepared/Frozen) |
| Carpets & Textiles | Knotted Carpets, Woven Carpets (incl. Kilims) |
| Luxury Fibres | Raw/Processed Cashmere, Cashmere Sweaters, Karakul Sheepskin |
| Minerals & Stones | Lapis Lazuli (×3), Marble & Travertine (×2), Talc |
| Oilseeds | Sesame Seeds, Flaxseed |

Each product maps to one or more 6-digit HS codes. The primary code is used for discovery URLs (e.g. Saffron → `091020`). Several categories intentionally split what looks like one product into several (Lapis Lazuli, Marble, Mulberries) or fall back to a broader catch-all code (Pomegranate, Liquorice Root) because the Harmonized System has no dedicated code for them — see the README's product-notes section for the reasoning behind each.

### Country name resolution

Comtrade sometimes returns placeholder names (`"None"`, raw numeric codes). The recent `backend/country_names.py` module resolves these at ETL load time and in API responses via `resolve_country_name()`, using a UN M49 lookup table. No migration backfills are needed — a rebuilt DB gets clean names from ingestion.

### Database tables (summary)

| Table | Contents |
|-------|----------|
| `products` | Product name, category, HS codes |
| `markets` | Country code + name |
| `trade_flows` | Global import values per market/year |
| `competitor_flows` | Supplier breakdown per market/year |
| `indicators` | All computed metrics + dimension scores + composite opportunity score, incl. WITS tariff fields (`tariff_rate_pct`, `tariff_indicator`, `tariff_year`) |
| `market_context` | World Bank indicators per country/year |
| `pipeline_runs` | ETL run history (status, timing, row counts) |

---

## 4. Scoring Methodology

### What the opportunity score represents

For each (product, market) pair, the tool computes a composite **Opportunity Score (0–100)** answering: *"How attractive is this market for Afghan exporters of this product?"*

Higher = more opportunity. Markets are ranked by this score in the discovery view.

### The 9 dimensions

Each dimension is normalised to 0–100, then combined using configurable weights from `config.py` → `OPPORTUNITY_SCORE_WEIGHTS`:

| Dimension | Weight | Source | What it measures |
|-----------|--------|--------|------------------|
| **Market size** | 20% | Comtrade | Global import volume for this product in this market |
| **Market growth** | 18% | Comtrade | CAGR of global imports (trend) |
| **Market quality** | 13% | World Bank | Composite of LPI, regulatory quality, political stability |
| **Price competitiveness** | 13% | Comtrade | Afghan unit price vs market average |
| **Tariff rate** | 10% | WITS | Import tariff Afghanistan faces (lower = better) |
| **Afghan foothold** | 10% | Comtrade | Existing Afghan export presence in the market |
| **Distance** | 10% | Static | Geographic proximity to Kabul |
| **Language similarity** | 4% | Static | Dari/Pashto communication overlap |
| **FTA status** | 2% | Static | Preferential trade access (small bonus) |

Weights must sum to 1.0. Change them in `config.py` and re-run the ETL.

### How each dimension is scored (0–100)

Implemented in `etl/transform.py`:

| Dimension | Scoring formula |
|-----------|----------------|
| **Market size** | Log-scale: `log1p(size_usd) / log_max × 100`, capped at 100 |
| **Market growth** | CAGR mapping: 0% → 50, +20% → 100, -20% → 0 (linear) |
| **Market quality** | Average of sub-scores: LPI (1–5 → 0–100), WGI indicators (-2.5–2.5 → 0–100). Defaults to 50 if no data |
| **Price competitiveness** | Categorical: Highly Competitive → 100, Competitive → 75, Average → 50, Above Market → 25 |
| **Tariff** | Linear: `max(0, 100 - rate × 3)`. 0% → 100, 33%+ → 0. Defaults to 50 if unavailable |
| **Afghan foothold** | Log-scale of export value: $0 → 25, $1M → ~60, $10M → ~75, $100M → ~90 |
| **Distance** | Linear: 0 km → 100, 15,000 km → 0. Defaults to 50 if unknown |
| **Language** | `LANGUAGE_SIMILARITY × 100` (0.0–1.0 lookup) |
| **FTA** | 100 if partial/full FTA, 0 otherwise |

### Composite calculation

```
opportunity_score = Σ (dimension_score × weight)
```

All dimension scores and the composite are stored per (product, market, year) in the `indicators` table. The discovery API ranks markets by `opportunity_score` for the latest computed year.

### Price competitiveness categories

Thresholds in `config.py` → `PRICE_COMPETITIVENESS`:

| Category | Condition |
|----------|-----------|
| Highly Competitive | Afghan price > 10% below market average |
| Competitive | Up to 10% below market average |
| Average | Within ±10% of market average |
| Above Market | More than 10% above market average |

### What the frontend shows

- **Product grid** (`/`) — all 29 products with top market and opportunity score
- **Discovery page** (`/discover/[hs_code]`) — ranked markets with score breakdown bars across all 9 dimensions
- **Market profile** (`/discover/[hs_code]/markets/[market_code]`) — full trade data, competitors, score breakdown, and practical next steps

### Practical next steps

`backend/services/discovery.py` generates market-entry guidance per profile (documentation requirements, tariff claims, buyer contacts, trade fairs). This is a key differentiator over raw trade data tools.

---

## 5. Suggested Walkthrough Order

When going through this with your colleague, a natural order:

1. **Start the stack** — `docker-compose up -d db backend`, then `npm run dev` in `frontend/`
2. **Browse the UI** — product grid → pick Saffron → see ranked markets → drill into India
3. **Hit the API** — open http://localhost:8000/docs, try `/api/discover/091020`
4. **Trace the data** — pick one market, follow it from Comtrade fetch → `indicators` table → API response
5. **Understand scoring** — read `config.py` weights, then `etl/transform.py` scoring functions
6. **Run the ETL** — `docker-compose exec backend python -m etl.run --products Saffron` and watch the logs
7. **Run tests** — `pytest backend/tests/ -v` to see what's contractually guaranteed

---

## 6. Known Quirks & Recent Changes

- **Mirror data only** — Afghan export values come from partner countries' import records, not direct Afghan reporting
- **Genuine zero vs. reporting lag for Afghan exports** — `afg_export_value_usd` stays pinned to `trade_data_year` even when Afghanistan simply isn't in that year's partner breakdown (a real signal, not missing data — see `_resolve_afg_last_export()`'s docstring in `etl/transform.py`). Two extra columns, `afg_last_export_year`/`afg_last_export_value_usd` (migration 0007), separately surface the most recent year (bounded at `AFG_LAST_EXPORT_FLOOR_YEAR = 2022`) Afghanistan had any recorded export to that market, purely for display context — never folded into `market_share_pct`, `afg_supplier_rank`, or the opportunity score, since mixing years there would compare an old Afghan figure against a newer global market size
- **Comtrade numeric codes** — markets use UN M49 codes (not ISO). `country_names.py` handles resolution
- **WITS lag** — tariff data may be 2–3 years behind; the fetcher walks back through years automatically, and (as of migration 0004) the actual year used is stamped on each indicator row as `tariff_year` so staleness is visible in the data itself, not just inferred
- **WITS 404s are normal** — a (reporter, partner, year) combination with no reported schedule (e.g. no preferential scheme for Afghanistan) returns 404; the pipeline treats that as "no data" and falls back, not as an error
- **WITS timeouts** — the per-schedule endpoint genuinely takes 30–60s even for a 404, not a network hang; the client timeout is set to 90s accordingly (see comment in `etl/fetch.py::_fetch_wits_tariffs`)
- **Product-level concurrency** — `etl/run.py` fetches up to 3 products concurrently (`_PRODUCT_MAX_WORKERS`); log lines are tagged with `[Product Name]` so interleaved output stays readable
- **Country name cleanup** — ETL and API resolve dirty Comtrade names (`"None"`, raw numeric codes) at ingestion/read time via `country_names.py`; no DB migration backfills needed on rebuild
- **`YEARS` extended to include 2025** — `config.py` now requests 2021–2025 (previously 2021–2024); Comtrade/World Bank/WITS each handle a year with no data differently (see §3 above), so this doesn't guarantee 2025 rows exist yet for every source
- **Several HS codes were corrected** — Pistachios, Cumin Seeds, and Asafoetida were previously pointing at the wrong 6-digit codes; Kilims, Dried Mulberries, and Lapis Lazuli/Marble were each collapsed into or split out of catch-all codes to match how these goods are actually reported (see README's "Products covered" notes for the reasoning per product)
- **HS codes are now validated against official reference data, not just eyeballed** — `reference/` holds Comtrade's own HS2017 (`hs_h5.json`) and HS2022 (`hs_h6.json`) nomenclature plus the WCO/UNSD HS2017↔HS2022 correlation table (`hs2017_hs2022_correlation.csv`). `tests/test_config.py` cross-checks every `PRODUCTS` code against these: it must be a real, product-level (leaf) code, must cover every year in `YEARS` under whichever HS revision was in force that year (2021 = HS2017, 2022+ = HS2022), and any revision-boundary split/merge must have its correlated successor/predecessor also present in `codes`. This caught a real bug: **Pine Nuts** was using `080290`, a code retired at the HS2022 cutover — fixed to include the HS2017 code (covers 2021) alongside its two HS2022 successors `080291`/`080292` (covers 2022+). Worth re-running this suite any time a product is added or an HS code is changed.
- **`etl/verify.py`** (new) — a standalone data-verification tool, separate from the pytest suite: internal DB sanity checks plus optional live spot-checks against the source APIs (see §1 above for usage). Its internal checks now also run automatically as a step in `.github/workflows/etl.yml`, right after every scheduled/manual ETL run, and fail that workflow on real structural problems (negative values, duplicate supplier codes, `market_share_pct` mismatches, out-of-range scores) — not on expected source-data gaps like WGI's publishing lag
