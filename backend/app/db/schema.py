from __future__ import annotations

import logging

from app.db.neo4j import get_session

logger = logging.getLogger(__name__)

SCHEMA_QUERIES = [
    # Constraints
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
    "CREATE CONSTRAINT hobby_name IF NOT EXISTS FOR (h:Hobby) REQUIRE h.name IS UNIQUE",
    "CREATE CONSTRAINT location_name IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE",
    "CREATE CONSTRAINT brand_name IF NOT EXISTS FOR (b:Brand) REQUIRE b.name IS UNIQUE",
    "CREATE CONSTRAINT activity_name IF NOT EXISTS FOR (a:Activity) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT task_record_id IF NOT EXISTS FOR (t:TaskRecord) REQUIRE t.provider_task_id IS UNIQUE",
    "CREATE CONSTRAINT ingest_job_id IF NOT EXISTS FOR (j:IngestJob) REQUIRE j.job_id IS UNIQUE",
    # Indexes
    "CREATE INDEX user_username IF NOT EXISTS FOR (u:User) ON (u.username)",
    "CREATE INDEX ingest_job_status IF NOT EXISTS FOR (j:IngestJob) ON (j.status)",
    "CREATE INDEX task_record_status IF NOT EXISTS FOR (t:TaskRecord) ON (t.status)",
]


async def init_schema() -> None:
    """Create constraints and indexes if they don't exist."""
    async with get_session() as session:
        for query in SCHEMA_QUERIES:
            try:
                await session.run(query)
            except Exception as e:
                # Constraint already exists — safe to ignore
                logger.debug("Schema query skipped: %s", e)
    logger.info("Neo4j schema initialized (%d queries)", len(SCHEMA_QUERIES))
