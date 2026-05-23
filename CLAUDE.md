# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IDX (Indonesia Stock Exchange) trading screener and analytical platform with 34 analytical engines, AI-powered by Claude Haiku, targeting three trading modes: **swing**, **daytrading**, **scalping**.

## Architecture

```
├── backend/          FastAPI app (Python 3.11), deployed on Railway
└── frontend/         React + Vite SPA, connects to Railway backend
```

### Backend (`backend/`)

**Entry point**: `backend/main.py` — FastAPI app with lifespan that initializes DB → Redis → KnowledgeBase on startup.

**Core layer** (`backend/app/core/`):
- `database.py` — Async SQLAlchemy + asyncpg, reads `DATABASE_URL` env var
- `redis_client.py` — Async Redis, reads `REDIS_URL` env var; provides `cache_get/cache_set/cache_delete`
- `invesgo.py` — Primary data source client for Invesgo IDX API (`INVESGO_API_KEY`); implements a **3-tier data strategy**: PostgreSQL → Redis cache → Invesgo API (to minimize API quota usage)
- `claude_client.py` — Anthropic API wrapper using `claude-haiku-4-5-20251001`, semaphore-limited to 2 concurrent calls
- `knowledge_base.py` — RAG knowledge base initialization

**34 Engines** (`backend/app/engines/`) — organized in 4 groups with mode-weighted scoring:
- **Group 1** (10): PriceAction, TrendStructure, SupportResistance, VolumeIntelligence, RelativeVolume, MultiTimeframe, OrderBlock, BreakOrder, FairValueGap, Liquidity
- **Group 2** (5): Bandarmology, Inventory, FlowMapping, IntradayPositioning, ForeignFlow
- **Group 3** (13): QuantEdge, Orderbook, RelativeStrength, Fibonacci, AIPatternRecognition, SectorRotation, MacroMarket, MacroEconomics, Geopolitics, NewsSentiment, InsiderOwnership, Probability, TradingSetup
- **Group 4** (6): RiskManagement, FinalScorecard, AIConfidence, SmartRotation, RealtimeAlert, LiquidityQuality

All engines extend `BaseEngine` (`engines/base_engine.py`) and implement `async def analyze(ticker, ohlcv, mode, **kwargs) -> EngineResult`. Score range is 0–100; ≥60 = bullish, ≤40 = bearish, else neutral.

**`master_runner.py`** orchestrates all 4 groups in parallel (`run_all_engines`) or a lightweight 7-engine subset (`run_monitoring_engines`). Group weights vary by mode.

**API routers** (`backend/app/api/`):
- `screener.py` — 5-phase screener (universe filter → OHLCV pre-filter → scoring → disqualifier → top 5 ranking), uses `Semaphore(30)` for phase 2 and `Semaphore(10)` for phase 3
- `analytic.py` — single-ticker full 34-engine analysis + Claude AI narrative + dynamic SL/TP + win probability
- `monitoring.py` and `monitoring/router.py` — position monitoring (open/close/check status)
- `scalping.py` — WebSocket-based real-time scalping
- `backtest.py` — backtesting
- `enrichment/router.py` — enrichment layer (REV21): SmartMFI, KAMABands, LeleExhaustion, DivergenceStateMachine + Phase 2 (Wyckoff, Weinstein, VSA)
- `knowledge_base.py` — PDF upload and RAG query endpoints

**ML layer** (`backend/app/ml/`):
- `signal_quality.py` — in-memory scikit-learn model predicting win probability from engine scores + market regime; trained incrementally via forward test data
- `dynamic_sltp.py` — ATR-based dynamic stop-loss / take-profit calculation
- `kb_features.py` — feature extraction from knowledge base for ML model

**Knowledge Base** (`backend/app/knowledge_base/`): RAG system using PostgreSQL + `asyncpg` + Anthropic embeddings; stores trading books (PDF) chunked at 1500 chars with 200-char overlap.

**Models** (`backend/app/models/`): SQLAlchemy ORM — `StockAnalysis`, `MonitoringPosition`, `Alert`, `TradingLog`. Also uses `ohlcv_daily` table (raw SQL, not ORM).

### Frontend (`frontend/`)

React 18 + Vite + Tailwind CSS. State managed via Zustand (`src/stores/useStore.js`). Tab-based navigation in `App.jsx` — tabs: screener, analytic, monitoring, scalping, kb, backtest, sysmonitor.

API calls go through `src/utils/api.js` which reads `VITE_BACKEND_URL` env var (defaults to production Railway URL). WebSocket URL derived by replacing `https://` with `wss://`.

## Required Environment Variables

Backend:
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- `INVESGO_API_KEY` — IDX market data API key
- `ANTHROPIC_API_KEY` — Claude API key

Frontend:
- `VITE_BACKEND_URL` — Backend URL (optional; defaults to production Railway URL)

## Development Commands

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # dev server
npm run build     # production build
npm run preview   # preview production build
```

## Deployment

Backend auto-deploys to Railway on push to `main` via `.github/workflows/deploy.yml`. The Dockerfile runs uvicorn with 2 workers. Health check endpoint: `GET /health`.

## Key Patterns

**Cache TTLs** (Redis): OHLCV 4 hours, broker summary 30 min, company info 24 hours, price table 30 min, KSEI 1 hour, market regime 10 min.

**Engine result errors**: All engines use `return_exceptions=True` in `asyncio.gather`; callers must check `isinstance(r, Exception)` before accessing `.score` or `.to_dict()`.

**Numpy serialization**: Always use `NumpyEncoder` or `sanitize_for_json()` from `monitoring.py` when serializing engine results — engines return numpy types that break standard `json.dumps`.

**Invesgo `get_ohlcv_daily`**: Preferred data source for most engines. Avoid calling `get_price_table`, `get_orderbook`, `get_broker_summary`, or `get_tick` in tight loops — they are rate-limited and unstable.

**Debug endpoint**: `GET /api/analytic/debug` runs a full stack trace through OHLCV → engines → ATR → RAG → Claude, useful for diagnosing integration failures.

**Enrichment gate**: The enrichment layer (`/api/enrich/{ticker}`) checks `bandar_score >= 55` before proceeding; if Redis cache misses, it defaults gate to pass to avoid blocking the flow.
