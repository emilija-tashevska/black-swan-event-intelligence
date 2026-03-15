from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

import os
from dotenv import load_dotenv
load_dotenv()
from collector import run_full_collection, run_enrichment_only, run_black_swan_enrichment
from database import DB_PATH, get_black_swans, get_stats, init_db

import aiosqlite

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Black Swan Analytics", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


@app.get("/api/black-swans")
async def list_black_swans(
    threshold: float = Query(0.10, ge=0.01, le=1.0),
    sort: str = Query("prediction_price"),
    order: str = Query("asc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    async for db in _get_db():
        rows = await get_black_swans(db, threshold, sort, order, limit, offset)
        return {
            "black_swans": [dict(r) for r in rows],
            "count": len(rows),
            "limit": limit,
            "offset": offset,
        }


@app.get("/api/stats")
async def stats(threshold: float = Query(0.10, ge=0.01, le=1.0)):
    async for db in _get_db():
        return await get_stats(db, threshold)


_collection_lock = asyncio.Lock()
_collection_running = False


@app.post("/api/collect")
async def trigger_collection(threshold: float = Query(0.10, ge=0.01, le=1.0)):
    global _collection_running
    if _collection_running:
        return {"status": "already_running"}
    _collection_running = True
    try:
        result = await run_full_collection(threshold)
        return {"status": "complete", **result}
    finally:
        _collection_running = False


@app.post("/api/enrich")
async def trigger_enrichment(threshold: float = Query(0.10, ge=0.01, le=1.0)):
    """Run only Phase 2 candlestick enrichment on existing market data."""
    global _collection_running
    if _collection_running:
        return {"status": "already_running"}
    _collection_running = True
    try:
        result = await run_enrichment_only(threshold)
        return {"status": "complete", **result}
    finally:
        _collection_running = False


@app.post("/api/enrich-black-swans")
async def trigger_black_swan_enrichment(
    regenerate_summaries: bool = Query(False),
):
    """Run post-detection enrichment: categories, prediction volumes, AI summaries."""
    global _collection_running
    if _collection_running:
        return {"status": "already_running"}
    _collection_running = True
    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        result = await run_black_swan_enrichment(
            api_key or None, regenerate_summaries=regenerate_summaries,
        )
        return {"status": "complete", **result}
    finally:
        _collection_running = False


@app.get("/api/health")
async def health():
    return {"status": "ok"}
