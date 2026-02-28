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
            MERGE (u)-[r:KNOWS]->(b)
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


async def get_graph_data(user_id: str, all_ids: list[str] | None = None) -> dict:
    """Get full graph data for force-directed visualization.

    If all_ids is provided, includes interests/brands for ALL listed users
    (the primary user + synced friend accounts).
    """
    if not all_ids:
        all_ids = [user_id]

    nodes: list[dict] = []
    edges: list[dict] = []

    async with get_session() as session:
        # Fetch all users and their interests + brands
        result = await session.run(
            """
            UNWIND $ids AS uid
            MATCH (u:User {id: uid})
            OPTIONAL MATCH (u)-[r:INTERESTED_IN]->(h:Hobby)
            OPTIONAL MATCH (u)-[rf:KNOWS]->(b:Brand)
            RETURN u.id AS uid, u.username AS username, u.profile_pic_url AS pic,
                   collect(DISTINCT {id: h.name, label: h.name, type: 'hobby', weight: r.weight}) AS hobbies,
                   collect(DISTINCT {id: b.name, label: b.name, type: 'brand'}) AS brands
            """,
            ids=all_ids,
        )

        async for rec in result:
            uid = rec["uid"]
            node_type = "self" if uid == user_id else "user"
            nodes.append({"id": uid, "label": rec["username"], "type": node_type, "pic": rec["pic"]})

            for h in rec["hobbies"]:
                if h["id"]:
                    nodes.append(h)
                    edges.append({"source": uid, "target": h["id"], "type": "INTERESTED_IN", "weight": h.get("weight", 0.5)})

            for b in rec["brands"]:
                if b["id"]:
                    nodes.append(b)
                    edges.append({"source": uid, "target": b["id"], "type": "KNOWS", "weight": 0.4})

        # Find OTHER users (not in all_ids) who share hobbies with any of the queried users
        result2 = await session.run(
            """
            UNWIND $ids AS uid
            MATCH (me:User {id: uid})-[:INTERESTED_IN]->(h:Hobby)<-[r:INTERESTED_IN]-(other:User)
            WHERE NOT other.id IN $ids
            RETURN DISTINCT other.id AS uid, other.username AS username, other.profile_pic_url AS pic,
                   collect(DISTINCT {hobby: h.name, weight: r.weight}) AS shared
            """,
            ids=all_ids,
        )
        async for rec in result2:
            nodes.append({"id": rec["uid"], "label": rec["username"], "type": "user", "pic": rec["pic"]})
            for s in rec["shared"]:
                edges.append({"source": rec["uid"], "target": s["hobby"], "type": "INTERESTED_IN", "weight": s.get("weight", 0.5)})

        # Find OTHER users who share brands
        result3 = await session.run(
            """
            UNWIND $ids AS uid
            MATCH (me:User {id: uid})-[:KNOWS]->(b:Brand)<-[r:KNOWS]-(other:User)
            WHERE NOT other.id IN $ids
            RETURN DISTINCT other.id AS uid, other.username AS username, other.profile_pic_url AS pic,
                   collect(DISTINCT b.name) AS shared_brands
            """,
            ids=all_ids,
        )
        async for rec in result3:
            nodes.append({"id": rec["uid"], "label": rec["username"], "type": "user", "pic": rec["pic"]})
            for brand in rec["shared_brands"]:
                edges.append({"source": rec["uid"], "target": brand, "type": "KNOWS", "weight": 0.4})

        # ── Enrichment nodes branching from Hobbies ──
        result4 = await session.run(
            """
            UNWIND $ids AS uid
            MATCH (u:User {id: uid})-[:INTERESTED_IN]->(h:Hobby)
            OPTIONAL MATCH (h)-[:HAS_EVENT]->(e:Event)
            OPTIONAL MATCH (h)-[:HAS_COMMUNITY]->(c:Community)
            OPTIONAL MATCH (h)-[:HAS_MEETUP]->(m:Meetup)
            WITH h,
                 collect(DISTINCT {id: e.url, label: e.title, type: 'event', date: e.date, location: e.location, desc: e.description}) AS events,
                 collect(DISTINCT {id: c.url, label: c.name, type: 'community', subs: c.subscriber_count, desc: c.description}) AS comms,
                 collect(DISTINCT {id: m.url, label: m.name, type: 'meetup', date: m.date, location: m.location, attendees: m.attendees}) AS meetups
            RETURN h.name AS hobby, events, comms, meetups
            """,
            ids=all_ids,
        )
        async for rec in result4:
            hobby_id = rec["hobby"]
            for e in rec["events"]:
                if e["id"]:
                    nodes.append(e)
                    edges.append({"source": hobby_id, "target": e["id"], "type": "HAS_EVENT", "weight": 0.3})
            for c in rec["comms"]:
                if c["id"]:
                    nodes.append(c)
                    edges.append({"source": hobby_id, "target": c["id"], "type": "HAS_COMMUNITY", "weight": 0.3})
            for m in rec["meetups"]:
                if m["id"]:
                    nodes.append(m)
                    edges.append({"source": hobby_id, "target": m["id"], "type": "HAS_MEETUP", "weight": 0.3})

        # Deduplicate nodes
        seen = set()
        unique_nodes = []
        for n in nodes:
            if n["id"] and n["id"] not in seen:
                seen.add(n["id"])
                unique_nodes.append(n)

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


# ── Enrichment Storage ──


async def store_enrichment_results(job_id: str, tier: str, results: dict) -> None:
    """Store enrichment results as graph nodes branching from Hobby nodes."""
    import json as _json

    # Always persist the raw JSON on the job node for the frontend timeline
    async with get_session() as session:
        prop_name = f"enrichment_{tier}"
        await session.run(
            f"""
            MATCH (j:IngestJob {{job_id: $job_id}})
            SET j.{prop_name} = $data, j.updated_at = datetime()
            """,
            job_id=job_id, data=_json.dumps(results),
        )

    if tier == "tier2":
        await _write_tier2_nodes(job_id, results)
    elif tier == "tier3":
        await _write_tier3_nodes(job_id, results)


async def _write_tier2_nodes(job_id: str, results: dict) -> None:
    """Write Event, Community, Meetup nodes branching from Hobby nodes."""
    if not results or results.get("status") in ("error", "timeout"):
        return

    async with get_session() as session:
        # Get the user_id from the job so we can find their hobbies
        r = await session.run(
            "MATCH (j:IngestJob {job_id: $jid}) RETURN j.user_id AS uid",
            jid=job_id,
        )
        rec = await r.single()
        if not rec:
            return
        user_id = rec["uid"]

        # Get user's hobbies to match enrichment results to topics
        r2 = await session.run(
            "MATCH (u:User {id: $uid})-[:INTERESTED_IN]->(h:Hobby) RETURN h.name AS name",
            uid=user_id,
        )
        hobby_names = [rec["name"] async for rec in r2]

        # Helper: find best matching hobby for a title/description
        def _match_hobby(text: str) -> str | None:
            text_lower = (text or "").lower()
            for h in hobby_names:
                if h.lower() in text_lower:
                    return h
            # Default to first hobby if no direct match
            return hobby_names[0] if hobby_names else None

        # Write events
        for evt in results.get("events", []):
            hobby = _match_hobby(f"{evt.get('title', '')} {evt.get('description', '')}")
            if not hobby:
                continue
            await session.run(
                """
                MERGE (e:Event {url: $url})
                SET e.title = $title, e.date = $date,
                    e.location = $location, e.description = $desc
                WITH e
                MATCH (h:Hobby {name: $hobby})
                MERGE (h)-[:HAS_EVENT]->(e)
                """,
                url=evt.get("url", ""),
                title=evt.get("title", ""),
                date=evt.get("date", ""),
                location=evt.get("location", ""),
                desc=evt.get("description", ""),
                hobby=hobby,
            )

        # Write communities
        for comm in results.get("communities", []):
            hobby = _match_hobby(f"{comm.get('name', '')} {comm.get('description', '')}")
            if not hobby:
                continue
            await session.run(
                """
                MERGE (c:Community {url: $url})
                SET c.name = $name, c.description = $desc,
                    c.subscriber_count = $subs
                WITH c
                MATCH (h:Hobby {name: $hobby})
                MERGE (h)-[:HAS_COMMUNITY]->(c)
                """,
                url=comm.get("url", ""),
                name=comm.get("name", ""),
                desc=comm.get("description", ""),
                subs=comm.get("subscriber_count", 0),
                hobby=hobby,
            )

        # Write meetups
        for mt in results.get("meetups", []):
            hobby = _match_hobby(f"{mt.get('name', '')} {mt.get('location', '')}")
            if not hobby:
                continue
            await session.run(
                """
                MERGE (m:Meetup {url: $url})
                SET m.name = $name, m.date = $date,
                    m.location = $location, m.attendees = $attendees
                WITH m
                MATCH (h:Hobby {name: $hobby})
                MERGE (h)-[:HAS_MEETUP]->(m)
                """,
                url=mt.get("url", ""),
                name=mt.get("name", ""),
                date=mt.get("date", ""),
                location=mt.get("location", ""),
                attendees=mt.get("attendees", 0),
                hobby=hobby,
            )


async def _write_tier3_nodes(job_id: str, results: dict) -> None:
    """Write Vibe node linked to the user."""
    if not results or results.get("status") in ("error", "timeout"):
        return
    vibe = results.get("vibe", {})
    if not vibe or not vibe.get("mood"):
        return

    async with get_session() as session:
        r = await session.run(
            "MATCH (j:IngestJob {job_id: $jid}) RETURN j.user_id AS uid",
            jid=job_id,
        )
        rec = await r.single()
        if not rec:
            return

        import json as _json
        await session.run(
            """
            MATCH (u:User {id: $uid})
            MERGE (v:Vibe {user_id: $uid})
            SET v.mood = $mood, v.energy = $energy,
                v.aesthetic_tags = $tags, v.themes = $themes
            MERGE (u)-[:HAS_VIBE]->(v)
            """,
            uid=rec["uid"],
            mood=vibe.get("mood", ""),
            energy=vibe.get("energy", 0.5),
            tags=_json.dumps(vibe.get("aesthetic_tags", [])),
            themes=_json.dumps(vibe.get("content_themes", [])),
        )


async def get_enrichment_results(job_id: str) -> dict:
    """Retrieve enrichment results for a job."""
    import json as _json
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (j:IngestJob {job_id: $job_id})
            RETURN j.enrichment_tier2 AS tier2,
                   j.enrichment_tier3 AS tier3,
                   j.status AS status,
                   j.result AS result
            """,
            job_id=job_id,
        )
        record = await result.single()
        if not record:
            return {}

        def _parse(val):
            if not val:
                return None
            try:
                return _json.loads(val) if isinstance(val, str) else val
            except (TypeError, _json.JSONDecodeError):
                return None

        return {
            "status": record["status"],
            "result": _parse(record["result"]),
            "tier2": _parse(record["tier2"]),
            "tier3": _parse(record["tier3"]),
        }

