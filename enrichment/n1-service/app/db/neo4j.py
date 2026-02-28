import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    """Return the singleton async Neo4j driver, creating it if necessary."""
    global _driver
    if _driver is None:
        if not settings.neo4j_uri:
            raise RuntimeError(
                "NEO4J_URI is not set. Configure it in .env "
                "(e.g. neo4j+s://<id>.databases.neo4j.io for AuraDB, "
                "or neo4j://localhost:7687 for local Docker)"
            )
        logger.info("Connecting to Neo4j at %s", settings.neo4j_uri)
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await _driver.verify_connectivity()
        logger.info("Neo4j connection verified")
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver and release resources."""
    global _driver
    if _driver is not None:
        logger.info("Closing Neo4j driver")
        await _driver.close()
        _driver = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async Neo4j session from the singleton driver."""
    driver = await get_driver()
    session = driver.session()
    try:
        yield session
    finally:
        await session.close()
