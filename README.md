# Black Swan Event Intelligence

Analytics engine that identifies when prediction markets were wrong. Scans [Kalshi](https://kalshi.com) markets for events that resolved **YES** despite having low implied probability — the definition of a black swan.

## What it does

1. **Collects** settled markets from Kalshi's public API (live + historical endpoints)
2. **Enriches** each market with its implied probability 7 days before close using daily candlestick data
3. **Filters** for black swans: events where the 7-day-prior price was below a configurable threshold (default 10%)
4. **Categorizes** markets (Crypto, Finance, Weather, Politics, Entertainment, etc.) and generates concise AI summaries via Gemini
5. **Analyzes** trade depth — how many contracts actually traded at the low implied probability

## Dashboard

The frontend provides:

- Adjustable probability threshold (5–25%)
- Sortable table with AI-generated event summaries, implied probability, last price, volume, and trade depth at price
- Aggregate stats: total black swans found, average implied probability, total volume, profit if you'd bought at the 7-day price
- Category breakdown showing which domains produce the most surprises

## Architecture

```
backend/
  main.py           FastAPI application (REST API)
  collector.py      Data collection & enrichment pipeline
  kalshi.py         Async Kalshi API client with pagination & rate limiting
  database.py       SQLite schema, migrations, and query layer
  models.py         Pydantic models for API responses

frontend/
  src/app/          Next.js App Router pages
  src/components/   Dashboard components (table, stats cards, threshold slider)
  src/lib/api.ts    API client with dual-mode support (live API / static JSON)

scripts/
  export_data.py    Export DB to static JSON for GitHub Pages
  update_and_deploy.sh   Orchestration: collect → export → build → deploy
```

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```
GEMINI_API_KEY=your_key_here
```

Run the data pipeline:

```bash
python3 collector.py
```

Start the API server:

```bash
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Data Pipeline

The collector runs in two phases:

- **Phase 1** — Fetch settled markets from Kalshi (incremental after first run). Filters out sports markets and enforces a minimum volume of 1,000 contracts.
- **Phase 2** — For each qualifying YES-resolved market, fetch the daily candlestick from 7 days before close to get the implied probability at that point.

Post-detection enrichment adds categories, prediction-day trading volume, trade depth at the prediction price (±$0.02), and AI-generated summaries.

## Static Deployment

To deploy as a static site (e.g. GitHub Pages):

```bash
# Run the full pipeline
./scripts/update_and_deploy.sh
```

This collects fresh data, exports it to JSON, builds a static Next.js export, and pushes to the `gh-pages` branch.

## Key Concepts

| Term | Definition |
|------|-----------|
| **Prediction price** | Candlestick close price 7 days before market close — the crowd's implied probability at that point |
| **Black swan** | A market that resolved YES despite low prediction price (configurable threshold) |
| **Depth at price** | Number of contracts that traded within ±$0.02 of the prediction price on that day |
| **Profit at 7d price** | Hypothetical profit from buying YES at the prediction price: `(1 - prediction_price) × depth_at_price` |

## Tech Stack

- **Backend**: Python, FastAPI, httpx, aiosqlite, SQLite
- **Frontend**: Next.js 16, React 19, Tailwind CSS
- **AI**: Google Gemini (market summaries)
- **Data**: Kalshi public API (unauthenticated)
