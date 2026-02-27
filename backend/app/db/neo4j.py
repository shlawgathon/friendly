from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await _driver.verify_connectivity()
        logger.info("Neo4j connected: %s", settings.neo4j_uri)
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    driver = await get_driver()
    async with driver.session() as session:
        yield session
