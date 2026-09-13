"""Read-only API for local development. The pipeline runs via cli.py, and the
deployed site reads static JSON, so nothing here mutates data."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import aiosqlite
from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

import config
import database as dbq

app = FastAPI(title="Black Swan Event Intelligence")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],
)


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    async with dbq.connect() as db:
        yield db


Db = Annotated[aiosqlite.Connection, Depends(get_db)]
Threshold = Annotated[float, Query(ge=0.01, le=1.0)]


@app.get("/api/black-swans")
async def list_black_swans(
    db: Db,
    threshold: Threshold = config.DEFAULT_THRESHOLD,
    sort: str = "volume",
    order: str = "desc",
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = await dbq.query_black_swans(db, threshold, sort, order, limit, offset, category)
    return {"black_swans": rows, "count": len(rows), "limit": limit, "offset": offset}


@app.get("/api/stats")
async def stats(db: Db, threshold: Threshold = config.DEFAULT_THRESHOLD):
    return await dbq.query_stats(db, threshold)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
