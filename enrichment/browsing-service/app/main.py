import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.neo4j import close_driver, get_driver
from app.routers.enrich import router as enrich_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize shared resources on startup and clean up on shutdown."""
    logger.info("Starting browsing-enrichment service (Tier 2)")
    try:
        await get_driver()
        logger.info("Neo4j driver initialized")
    except Exception:
        logger.exception("Failed to connect to Neo4j — service will start but graph writes will fail")
    yield
    logger.info("Shutting down browsing-enrichment service")
    await close_driver()


app = FastAPI(
    title="Friendly Browsing Enrichment",
    description="Tier 2 — Contextual enrichment via cloud browser agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins for hackathon
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(enrich_router)


@app.get("/health")
async def health() -> dict[str, str | int]:
    """Health check endpoint."""
    return {"status": "ok", "service": "browsing-enrichment", "tier": 2}
