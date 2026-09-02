# AFG Market Diversification Tool

A market discovery platform that helps Afghan businesses and UNDP trade analysts identify and rank the best new export markets for Afghan products — modelled on the US government's [trade.gov Market Diversification Tool](https://www.trade.gov/market-diversification-tool) but built specifically for the Afghan export context.

## What it does

A user selects a product (by HS code or name), and the tool returns a ranked list of markets scored by a composite **Opportunity Score** (0–100). Each market is scored across eight dimensions:

| Dimension | Weight | Source |
|-----------|--------|--------|
| Market size (global imports of this product) | 20% | UN Comtrade |
| Market growth (CAGR of Afghan exports to this market) | 18% | UN Comtrade |
| Market quality (governance, logistics) | 13% | World Bank WDI/WGI |
| Price competitiveness | 13% | UN Comtrade |
| Tariff rate on Afghan goods | 12% | WITS (World Bank) |
| Existing Afghan foothold | 10% | UN Comtrade (mirror stats) |
| Geographic proximity to Kabul | 10% | Static lookup |
| Language / cultural similarity | 4% | Static lookup |
| FTA / preferential trade access | 2% | Static lookup |

The tool also surfaces **practical next steps** per market (documentation, tariff claims, buyer contacts, trade fairs) as its key differentiator over existing tools.

---

## Architecture

```
UN Comtrade API + World Bank API
        ↓
  etl/  (fetch → transform → load)
        ↓
  PostgreSQL (trade data + opportunity scores)
        ↓
  backend/  (FastAPI — serves ranked markets + market profiles)
        ↓
  frontend/  (Next.js — discovery wizard UI)  ← planned
```

**Stack:** Python · FastAPI · PostgreSQL · Alembic · Docker Compose · Next.js (planned) · GitHub Actions

---

## Quick start

### Prerequisites

- Docker and Docker Compose
- UN Comtrade API key ([register here](https://unstats.un.org/wiki/display/comtrade/UN+Comtrade+API))

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set COMTRADE_API_KEY and POSTGRES_PASSWORD
```

### 2. Start services

```bash
docker-compose up -d
```

This starts PostgreSQL and the FastAPI backend. On first start, the backend container runs `alembic upgrade head` automatically.

### 3. Run the ETL pipeline

```bash
# Full run — all 34 products + World Bank indicators
docker-compose exec backend python -m etl.run

# Specific products only
docker-compose exec backend python -m etl.run --products Saffron "Dried Grapes (Raisins)"

# Skip World Bank fetch (use cached data)
docker-compose exec backend python -m etl.run --skip-world-bank

# Skip WITS tariff fetch (faster runs; reuses each product's previously-stored tariffs)
docker-compose exec backend python -m etl.run --skip-tariffs

# Dry run — fetch and transform but don't write to DB
python -m etl.run --dry-run
```

### 4. Explore the API

With the backend running at `http://localhost:8000`:

```
GET /api/discover/091020              → Ranked markets for Saffron
GET /api/discover/091020?limit=10     → Top 10 markets only
GET /api/discover/091020?min_score=60 → Markets scoring 60+
GET /api/discover/091020/markets/699  → Full profile for India market
GET /api/products                     → All products
GET /api/products/091020              → Product detail with market indicators
GET /api/indicators                   → Indicator definitions / tooltips
GET /health                           → Health check
```

Interactive API docs: `http://localhost:8000/docs`

---

## Development

### Run tests (no Docker needed)

```bash
pip install -r requirements.txt
pytest backend/tests/ -v
```

Tests use an in-memory SQLite DB — no external dependencies.

### Lint

```bash
ruff check .
```

### Database migrations

```bash
# Apply all migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

---

## Project structure

```
afg-market-intelligence/
├── config.py                    # Products (38, 37 unique HS codes), score weights, country lookups
├── requirements.txt
├── pyproject.toml               # Ruff + pytest config
├── alembic.ini
├── .env.example
├── docker-compose.yml
├── Dockerfile.backend
│
├── etl/
│   ├── fetch.py                 # Comtrade + World Bank + WITS API clients
│   ├── transform.py             # Data normalisation + opportunity score computation
│   ├── load.py                  # Idempotent PostgreSQL upserts
│   ├── run.py                   # ETL orchestrator (CLI entry point)
│   └── verify.py                # DB sanity checks + optional live spot-checks
│
├── migrations/
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_market_context_and_scores.py
│       ├── 0003_tariff_rates.py
│       └── 0004_tariff_year.py
│
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── database.py              # SQLAlchemy engine + session
│   ├── models.py                # ORM models
│   ├── schemas.py                # Pydantic response schemas
│   ├── country_names.py         # UN M49 code → country name resolution
│   ├── routers/
│   │   ├── discovery.py         # GET /api/discover/*
│   │   ├── products.py          # GET /api/products/*
│   │   └── meta.py              # GET /api/indicators, /health
│   ├── services/
│   │   ├── discovery.py         # Ranked-market queries + next-step logic
│   │   └── products.py          # Product/market indicator queries
│   └── tests/                   # 47 tests total (SQLite, no Docker)
│       ├── test_api.py          # 27 contract tests
│       ├── test_country_names.py
│       └── test_next_steps.py
│
├── frontend/                    # Next.js app (discovery wizard UI, product grid, market profile)
│
├── indicator_definitions.json   # Metric definitions for UI tooltips
│
└── .github/workflows/
    ├── ci.yml                   # Lint + tests on push to main / claude/**
    └── etl.yml                  # Monthly ETL cron (1st of month, 02:00 UTC)
```

---

## Products covered (38 products, 37 unique HS codes)

| Category | Products |
|----------|----------|
| Tree Nuts | Almonds (in-shell, shelled), Walnuts (in-shell, shelled), Pistachios (in-shell, shelled), Pine Nuts |
| Spices & Herbs | Saffron, Cumin Seeds, Fenugreek, Asafoetida, Liquorice Root, Liquorice Extract |
| Dried Fruits | Dried Grapes (Raisins), Dried Apricots, Dried Figs, Dried Pomegranate |
| Fresh Fruits | Fresh Grapes, Fresh Pomegranate, Watermelons, Melons, Apricots, Mulberries (Fresh), Mulberries (Prepared/Frozen) |
| Carpets & Textiles | Knotted Carpets, Woven Carpets (incl. Kilims) |
| Luxury Fibres | Raw Cashmere, Processed Cashmere, Cashmere Sweaters, Karakul Sheepskin |
| Minerals & Stones | Lapis Lazuli (Unworked), Lapis Lazuli (Worked), Lapis Lazuli (Articles), Marble & Travertine (Crude), Marble & Travertine (Cut), Talc |
| Oilseeds | Sesame Seeds, Flaxseed / Linseed |

**Note on Pomegranate (Fresh & Dried):** pomegranate has no dedicated 6-digit HS code in the Harmonized System, despite being one of Afghanistan's major fruit exports. Trade data for these two products is pulled from the closest catch-all categories instead — `081090` ("other fresh fruit, n.e.c.") for Fresh Pomegranate and `081340` ("other dried fruit, n.e.c.") for Dried Pomegranate — so the reported figures include other minor fruits reported under the same catch-all, not pomegranate exclusively.

**Note on Kilims:** kilims do not have their own HS6 code either. Comtrade's `570210` ("woven, not tufted or flocked" carpets) explicitly names kelim/kilim rugs as part of that single category, alongside other flat-woven carpets. Rather than duplicate identical data under two product names, kilims are tracked under **Woven Carpets** rather than as a separate entry.

**Note on Liquorice Root:** the dedicated liquorice-root code (`121110`) is valid but essentially unused by reporters (only 2 global records across 2021-2024). Real root trade is captured instead via `121190`, a broader "other plants n.e.c." catch-all that also includes unrelated goods (ginseng, coca leaf, poppy straw, ephedra), so figures aren't liquorice-exclusive. **Liquorice Extract** (processed liquorice, `130212`) is tracked as a separate product and does not have this issue — it is a precise, liquorice-specific code.

**Note on Mulberries:** no "dried mulberries" code exists anywhere in the Harmonized System — mulberries only appear grouped with raspberries, blackberries and loganberries under a **fresh** heading (`081020`) or a **cooked/frozen** heading (`081120`), never in the dried-fruit chapter. Tracked as two separate products rather than one "Dried Mulberries" entry, since neither code is actually for dried fruit.

**Note on Lapis Lazuli:** lapis lazuli has no HS6 code of its own. It falls under Comtrade's general precious/semi-precious stone categories, which vary by processing stage, so it is tracked as three separate products: `710310` (unworked/roughly shaped), `710399` (worked, not strung/mounted/set), and `711620` (finished articles). Figures for each include other precious/semi-precious stones reported under the same code, not lapis lazuli exclusively.

---

## Data sources & methodology

All three sources are driven by `config.py` → `YEARS`, currently `[2021, 2022, 2023, 2024, 2025]`. Each source resolves that requested range differently — see below.

### Trade data — UN Comtrade (mirror statistics)
Afghanistan does not report directly to UN Comtrade. Instead, the pipeline uses **mirror statistics**: it queries other countries' import records where Afghanistan is listed as the exporting partner. This is the standard methodology for Afghanistan trade data.

Requested directly for all 5 years in `YEARS`; a given year can come back empty if a reporter hasn't submitted data to Comtrade yet.

### Market context — World Bank Development Indicators
The ETL fetches per-country, per-year indicators from the World Bank API, requested as a single `2021:2025` date range:
- **GDP** (`NY.GDP.MKTP.CD`) and **GDP per capita** (`NY.GDP.PCAP.CD`) — market wealth / purchasing power
- **Logistics Performance Index** (`LP.LPI.OVRL.XQ`) — supply-chain connectivity
- **Regulatory Quality** (`GOV_WGI_RQ.SC`, WGI) — ease of doing business, on WGI's 0-100 "score" scale
- **Political Stability** (`GOV_WGI_PV.SC`, WGI) — market risk, on WGI's 0-100 "score" scale

Both WGI fields deliberately use the `.SC` variant, not the `.EST` (-2.5 to +2.5 "estimate") variant — a plain 0-100 range is clearer to reason about and display.

Coverage isn't even across the requested range: LPI is only published in select years, and the WGI indicators typically lag 1–2 years behind the current year. For each market profile, `lpi_score`, `regulatory_quality`, and `political_stability` each resolve independently to the latest year ≤ the profile's `computed_for_year` with a non-null value — `lpi_score_year`, `regulatory_quality_year`, and `political_stability_year` record which year each one actually came from, since they frequently differ from each other and from `computed_for_year`. `gdp_per_capita_usd` doesn't need this: it's published annually with no gaps, so a missing value there means the fetch failed rather than the data not existing — the WB fetch uses a 60s timeout per 20-country batch for exactly this reason (a 30s timeout was previously dropping GDP-per-capita for large batches of countries on slow responses).

### Tariffs — WITS (World Integrated Trade Solution)
For each market, the ETL queries the WITS TRN (UNCTAD TRAINS) REST API:
- Tries **Afghanistan-specific applied rates** first (partner = Afghanistan; captures preferential rates from FTAs) — reported as `AHS`
- Falls back to **MFN rates** (partner = World) when no Afghanistan-specific data is available — reported as `MFN`

WITS tariff data typically lags 2–3 years behind trade data, so the ETL walks backward through `YEARS` (2025 → 2021) per market until it finds a reported schedule. The `tariff_indicator` field on each market profile tells you which series the rate came from, and `tariff_year` tells you the actual year WITS reported that rate for — which is frequently earlier than the market profile's `computed_for_year`, since it reflects whenever that country last reported to TRAINS within the requested window (not necessarily 2025).

**A fetched rate is only kept if Afghanistan actually trades there.** WITS reports MFN/Applied tariff schedules for a product even when a market doesn't trade it at all — its own site says so directly ("MFN and Applied Tariff are provided for both traded and non-traded goods") — and the tariff API gives no "is this traded" flag to filter that out. So the ETL derives it from Comtrade instead: a rate is discarded (stored as `NULL`) unless `afg_export_value_usd` shows real Afghan exports to that market, this year or (falling back, same logic as the foothold score) historically. This applies the same way whether WITS reported the rate as `AHS` or `MFN` — that only says which regime the number came from, not whether Afghanistan actually trades there.

A discarded rate makes `score_tariff = NULL`, excluded from `opportunity_score` with the remaining weights renormalised — changed 2026-09-02 from a neutral-50 default. Deliberately not a guessed 0 either: `score_afg_foothold` already carries the "no Afghan trade history" penalty as a confirmed fact for its own dimension; not knowing the tariff is a genuinely different situation (we don't know what applies, not that it's bad), so excluding it avoids asserting either a false-favorable or false-punitive number and avoids double-counting the same underlying fact across two dimensions.

### Static lookups
- **Distance from Kabul** — approximate straight-line km for ~60 trading partners
- **Language similarity** — scored 0–1 based on Dari/Pashto overlap with trade-communication languages
- **FTA status** — Afghanistan's memberships: SAPTA (South Asia), ECO (Central/West Asia), EU/UK GSP+

### Opportunity score
Each dimension is normalised to 0–100 before weighting. Score thresholds are configurable in `config.py` (`OPPORTUNITY_SCORE_WEIGHTS`).

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `COMTRADE_API_KEY` | Yes | UN Comtrade subscription key |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Docker only | Password for the `postgres` user |

---

## Roadmap

- [x] ETL pipeline (Comtrade + World Bank + WITS tariffs)
- [x] Opportunity scoring model (9 dimensions, configurable weights)
- [x] FastAPI backend with discovery + products endpoints
- [x] Market-entry next steps per market (incl. tariff-aware guidance)
- [ ] Next.js frontend — discovery wizard UI
- [ ] Natural language → HS code classifier ("I sell dried figs")
- [ ] Buyer contact directory integration
- [ ] Simplified "business owner" view (vs. analyst view)
