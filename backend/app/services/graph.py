"""Neo4j graph queries — user creation, interest insertion, matching."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.config import settings
from app.db.neo4j import get_session

logger = logging.getLogger(__name__)


async def create_user(user_id: str, username: str, full_name: str | None = None,
                      bio: str | None = None, profile_pic_url: str | None = None) -> None:
    """Create or update a User node."""
    async with get_session() as session:
        await session.run(
            """
            MERGE (u:User {id: $id})
            SET u.username = $username,
                u.full_name = $full_name,
                u.bio = $bio,
                u.profile_pic_url = $profile_pic_url,
                u.updated_at = datetime()
            """,
            id=user_id, username=username, full_name=full_name,
            bio=bio, profile_pic_url=profile_pic_url,
        )


async def add_interest(user_id: str, hobby_name: str, weight: float = 0.5,
                       source: str = "visual", evidence: str | None = None) -> None:
    """Link user to a hobby with weight and source."""
    async with get_session() as session:
        await session.run(
            """
            MERGE (u:User {id: $uid})
            MERGE (h:Hobby {name: $hobby})
            MERGE (u)-[r:INTERESTED_IN]->(h)
            SET r.weight = CASE WHEN r.weight IS NULL THEN $weight
                               ELSE CASE WHEN $weight > r.weight THEN $weight ELSE r.weight END
                          END,
                r.source = $source,
                r.evidence = COALESCE($evidence, r.evidence),
                r.updated_at = datetime()
            """,
            uid=user_id, hobby=hobby_name.lower().strip(),
            weight=weight, source=source, evidence=evidence,
        )


async def add_location(user_id: str, location_name: str, source: str = "visual") -> None:
    async with get_session() as session:
        await session.run(
            """
            MERGE (u:User {id: $uid})
            MERGE (l:Location {name: $loc})
            MERGE (u)-[r:VISITED]->(l)
            SET r.source = $source, r.updated_at = datetime()
            """,
            uid=user_id, loc=location_name.lower().strip(), source=source,
        )


async def add_brand(user_id: str, brand_name: str, source: str = "visual") -> None:
    async with get_session() as session:
        await session.run(
            """
            MERGE (u:User {id: $uid})
            MERGE (b:Brand {name: $brand})
            MERGE (u)-[r:FOLLOWS]->(b)
            SET r.source = $source, r.updated_at = datetime()
            """,
            uid=user_id, brand=brand_name.lower().strip(), source=source,
        )


async def add_entities_from_extraction(user_id: str, entities: dict, source: str = "visual") -> int:
    """Process extraction result and write to graph. Returns count of entities added."""
    # Normalize plural keys → singular (Reka may return 'hobbies', 'brands', etc.)
    PLURAL_MAP = {
        "hobbies": "hobby", "activities": "activity", "sports": "sport",
        "locations": "location", "brands": "brand", "foods": "food",
        "musics": "music", "arts": "art",
    }
    normalized: dict = {}
    for label, values in entities.items():
        key = PLURAL_MAP.get(label.lower(), label.lower())
        normalized[key] = values

    count = 0
    for label, values in normalized.items():
        if not isinstance(values, list):
            values = [values]
        for val in values:
            if not val or not isinstance(val, str) or len(val.strip()) < 2:
                continue
            val = val.strip()
            if label in ("hobby", "activity", "sport", "music", "art", "food"):
                await add_interest(user_id, val, weight=0.6, source=source, evidence=f"Extracted as {label}")
                count += 1
            elif label == "location":
                await add_location(user_id, val, source=source)
                count += 1
            elif label == "brand":
                await add_brand(user_id, val, source=source)
                count += 1
    return count


async def get_user_interests(user_id: str) -> list[dict]:
    """Get all interests for a user, sorted by weight."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (u:User {id: $uid})-[r:INTERESTED_IN]->(h:Hobby)
            RETURN h.name AS hobby, r.weight AS weight, r.source AS source, r.evidence AS evidence
            ORDER BY r.weight DESC
            """,
            uid=user_id,
        )
        return [dict(record) async for record in result]


async def find_matches(user_id: str, limit: int = 10) -> list[dict]:
    """Find other users with overlapping interests, ranked by shared interest count × weight."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (me:User {id: $uid})-[r1:INTERESTED_IN]->(h:Hobby)<-[r2:INTERESTED_IN]-(other:User)
            WHERE other.id <> $uid
            WITH other, collect(DISTINCT h.name) AS shared,
                 sum(r1.weight * r2.weight) AS affinity
            RETURN other.id AS user_id, other.username AS username,
                   other.full_name AS full_name, other.profile_pic_url AS pic,
                   shared, affinity
            ORDER BY affinity DESC
            LIMIT $limit
            """,
            uid=user_id, limit=limit,
        )
        return [dict(record) async for record in result]


async def get_graph_data(user_id: str) -> dict:
    """Get full graph data for force-directed visualization."""
    async with get_session() as session:
        # Nodes: user + their interests + brands + matched users
        result = await session.run(
            """
            MATCH (me:User {id: $uid})
            OPTIONAL MATCH (me)-[r:INTERESTED_IN]->(h:Hobby)
            OPTIONAL MATCH (me)-[rf:FOLLOWS]->(b:Brand)
            OPTIONAL MATCH (h)<-[r2:INTERESTED_IN]-(other:User)
            WHERE other.id <> $uid
            WITH me,
                 collect(DISTINCT {id: h.name, label: h.name, type: 'hobby', weight: r.weight}) AS hobbies,
                 collect(DISTINCT {id: b.name, label: b.name, type: 'brand'}) AS brands,
                 collect(DISTINCT {id: other.id, label: other.username, type: 'user', pic: other.profile_pic_url}) AS others
            RETURN {id: me.id, label: me.username, type: 'self', pic: me.profile_pic_url} AS self_node,
                   hobbies, brands, others
            """,
            uid=user_id,
        )
        record = await result.single()
        if not record:
            return {"nodes": [], "edges": []}

        nodes = [record["self_node"]]
        edges = []

        for h in record["hobbies"]:
            if h["id"]:
                nodes.append(h)
                edges.append({"source": user_id, "target": h["id"], "type": "INTERESTED_IN", "weight": h.get("weight", 0.5)})

        for b in record["brands"]:
            if b["id"]:
                nodes.append(b)
                edges.append({"source": user_id, "target": b["id"], "type": "FOLLOWS", "weight": 0.4})

        for o in record["others"]:
            if o["id"]:
                nodes.append(o)

        # Deduplicate
        seen = set()
        unique_nodes = []
        for n in nodes:
            if n["id"] not in seen:
                seen.add(n["id"])
                unique_nodes.append(n)

        # Edges between other users and hobbies
        result2 = await session.run(
            """
            MATCH (me:User {id: $uid})-[:INTERESTED_IN]->(h:Hobby)<-[r:INTERESTED_IN]-(other:User)
            WHERE other.id <> $uid
            RETURN other.id AS user_id, h.name AS hobby, r.weight AS weight
            """,
            uid=user_id,
        )
        async for rec in result2:
            edges.append({
                "source": rec["user_id"], "target": rec["hobby"],
                "type": "INTERESTED_IN", "weight": rec.get("weight", 0.5),
            })

        return {"nodes": unique_nodes, "edges": edges}


# ── Job / Task tracking ──


async def create_ingest_job(job_id: str, username: str, user_id: str) -> None:
    async with get_session() as session:
        await session.run(
            """
            CREATE (j:IngestJob {
                job_id: $job_id, username: $username, user_id: $user_id,
                status: 'queued', created_at: datetime(), failed_steps: []
            })
            """,
            job_id=job_id, username=username, user_id=user_id,
        )


async def update_ingest_job(job_id: str, status: str, progress: dict | None = None,
                            result: dict | None = None, error: str | None = None) -> None:
    import json as _json
    async with get_session() as session:
        await session.run(
            """
            MATCH (j:IngestJob {job_id: $job_id})
            SET j.status = $status,
                j.progress = $progress,
                j.result = $result,
                j.error = $error,
                j.updated_at = datetime()
            """,
            job_id=job_id, status=status,
            progress=_json.dumps(progress) if progress else None,
            result=_json.dumps(result) if result else None,
            error=error,
        )


async def get_ingest_job(job_id: str) -> dict | None:
    async with get_session() as session:
        result = await session.run(
            "MATCH (j:IngestJob {job_id: $job_id}) RETURN j",
            job_id=job_id,
        )
        record = await result.single()
        return dict(record["j"]) if record else None


async def check_cooldown(username: str) -> bool:
    """Return True if this username was ingested within the cooldown period."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (j:IngestJob {username: $username})
            WHERE j.status IN ['queued', 'processing', 'completed']
            AND j.created_at > datetime() - duration({minutes: $mins})
            RETURN count(j) AS cnt
            """,
            username=username, mins=settings.ingest_cooldown_minutes,
        )
        record = await result.single()
        return record["cnt"] > 0 if record else False


# ── Task Records (Yutori) ──


async def create_task_record(provider_task_id: str, task_type: str,
                             interest: str, user_id: str) -> None:
    async with get_session() as session:
        await session.run(
            """
            CREATE (t:TaskRecord {
                provider_task_id: $ptid, task_type: $tt, interest: $interest,
                user_id: $uid, status: 'pending', attempts: 0,
                created_at: datetime()
            })
            """,
            ptid=provider_task_id, tt=task_type, interest=interest, uid=user_id,
        )


async def complete_task_record(provider_task_id: str, result_json: str) -> bool:
    """Mark a task as completed. Returns False if already completed (idempotent)."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (t:TaskRecord {provider_task_id: $ptid})
            WHERE t.status <> 'completed'
            SET t.status = 'completed', t.result_json = $rj,
                t.completed_at = datetime(), t.attempts = t.attempts + 1
            RETURN t.provider_task_id AS id
            """,
            ptid=provider_task_id, rj=result_json,
        )
        record = await result.single()
        return record is not None


async def get_pending_tasks(older_than_minutes: int = 10) -> list[dict]:
    """Get tasks that are still pending/running beyond the threshold."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (t:TaskRecord)
            WHERE t.status IN ['pending', 'running']
            AND t.created_at < datetime() - duration({minutes: $mins})
            RETURN t.provider_task_id AS provider_task_id,
                   t.task_type AS task_type,
                   t.interest AS interest,
                   t.user_id AS user_id,
                   t.attempts AS attempts
            """,
            mins=older_than_minutes,
        )
        return [dict(record) async for record in result]
