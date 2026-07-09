# AFG Market Diversification Tool

A market discovery platform that helps Afghan businesses and UNDP trade analysts identify and rank the best new export markets for Afghan products — modelled on the US government's [trade.gov Market Diversification Tool](https://www.trade.gov/market-diversification-tool) but built specifically for the Afghan export context.

## What it does

A user selects a product (by HS code or name), and the tool returns a ranked list of markets scored by a composite **Opportunity Score** (0–100). Each market is scored across eight dimensions:

| Dimension | Weight | Source |
|-----------|--------|--------|
| Market size (global imports of this product) | 20% | UN Comtrade |
| Market growth (CAGR of imports) | 18% | UN Comtrade |
| Market quality (governance, logistics) | 13% | World Bank WDI/WGI |
| Price competitiveness | 13% | UN Comtrade |
| Tariff rate on Afghan goods | 10% | WITS (World Bank) |
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

# Skip WITS tariff fetch (faster runs, neutral tariff scores)
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
├── config.py                    # Products (34 HS codes), score weights, country lookups
├── requirements.txt
├── pyproject.toml               # Ruff + pytest config
├── alembic.ini
├── .env.example
├── docker-compose.yml
├── Dockerfile.backend
│
├── etl/
│   ├── fetch.py                 # Comtrade + World Bank API clients
│   ├── transform.py             # Data normalisation + opportunity score computation
│   ├── load.py                  # Idempotent PostgreSQL upserts
│   └── run.py                   # ETL orchestrator (CLI entry point)
│
├── migrations/
│   └── versions/
│       ├── 0001_initial_schema.py
│       └── 0002_market_context_and_scores.py
│
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── database.py              # SQLAlchemy engine + session
│   ├── models.py                # ORM models
│   ├── schemas.py               # Pydantic response schemas
│   ├── routers/
│   │   ├── discovery.py         # GET /api/discover/*
│   │   ├── products.py          # GET /api/products/*
│   │   └── meta.py              # GET /api/indicators, /health
│   ├── services/
│   │   ├── discovery.py         # Ranked-market queries + next-step logic
│   │   └── products.py          # Product/market indicator queries
│   └── tests/
│       └── test_api.py          # 21 contract tests (SQLite, no Docker)
│
├── frontend/                    # Next.js app — planned
│
├── indicator_definitions.json   # Metric definitions for UI tooltips
│
└── .github/workflows/
    ├── ci.yml                   # Lint + tests on push to main / claude/**
    └── etl.yml                  # Monthly ETL cron (1st of month, 02:00 UTC)
```

---

## Products covered (34 HS codes)

| Category | Products |
|----------|----------|
| Tree Nuts | Almonds (in-shell, shelled), Walnuts (in-shell, shelled), Pistachios (in-shell, shelled), Pine Nuts |
| Spices & Herbs | Saffron, Cumin Seeds, Fenugreek, Asafoetida, Liquorice Root |
| Dried Fruits | Dried Grapes (Raisins), Dried Apricots, Dried Figs, Dried Pomegranate, Dried Mulberries |
| Fresh Fruits | Fresh Grapes, Fresh Pomegranate, Melons, Apricots |
| Carpets & Textiles | Knotted Carpets, Woven Carpets, Kilims |
| Luxury Fibres | Raw Cashmere, Processed Cashmere, Cashmere Sweaters, Karakul Sheepskin |
| Minerals & Stones | Lapis Lazuli, Marble & Travertine, Talc |
| Oilseeds | Sesame Seeds, Flaxseed / Linseed |

---

## Data sources & methodology

### Trade data — UN Comtrade (mirror statistics)
Afghanistan does not report directly to UN Comtrade. Instead, the pipeline uses **mirror statistics**: it queries other countries' import records where Afghanistan is listed as the exporting partner. This is the standard methodology for Afghanistan trade data.

### Market context — World Bank Development Indicators
The ETL fetches per-country, per-year indicators from the World Bank API:
- **GDP per capita** (`NY.GDP.PCAP.CD`) — market wealth / purchasing power
- **Logistics Performance Index** (`LP.LPI.OVRL.XQ`) — supply-chain connectivity
- **Regulatory Quality** (`GOV_WGI_RQ.EST`, WGI) — ease of doing business
- **Political Stability** (`GOV_WGI_PV.EST`, WGI) — market risk

### Tariffs — WITS (World Integrated Trade Solution)
For each market, the ETL queries the WITS TRN (UNCTAD TRAINS) REST API:
- Tries **Afghanistan-specific applied rates** first (partner = Afghanistan; captures preferential rates from FTAs) — reported as `AHS`
- Falls back to **MFN rates** (partner = World) when no Afghanistan-specific data is available — reported as `MFN`

The `tariff_indicator` field on each market profile tells you which series the rate came from.

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
