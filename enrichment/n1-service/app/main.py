import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.neo4j import get_driver, close_driver
from app.routers import enrich

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: connect to Neo4j, ensure screenshot directory exists.
    Shutdown: close the Neo4j driver."""
    # Ensure screenshot directory exists
    screenshot_dir = Path(settings.screenshot_dir)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Screenshot directory ready at %s", screenshot_dir)

    # Initialize Neo4j connection
    await get_driver()
    logger.info("n1-service started on tier 3")

    yield

    # Shutdown
    await close_driver()
    logger.info("n1-service shut down")


app = FastAPI(
    title="Friendly Deep Enrichment Service",
    description="Tier 3 - n1 deep enrichment microservice for Friendly",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(enrich.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "deep-enrichment", "tier": 3}
