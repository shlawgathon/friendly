"""Friendly backend — FastAPI application."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.neo4j import get_driver, close_driver
from app.db.schema import init_schema
from app.routers import ingest, jobs, discover, chat, webhooks
from app.workers.yutori_poller import start_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Friendly backend...")
    await get_driver()
    await init_schema()

    # Start Yutori poller background task
    poller_task = asyncio.create_task(start_poller())
    logger.info("Backend ready")

    yield

    # Shutdown
    poller_task.cancel()
    await close_driver()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="Friendly",
    description="Semantic social graph — find friends through shared passions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(ingest.router)
app.include_router(jobs.router)
app.include_router(discover.router)
app.include_router(chat.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "friendly-backend"}
