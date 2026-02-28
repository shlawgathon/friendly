"""Discovery routes — matches and graph data."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.dto import GraphData
from app.services import graph

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/matches")
async def get_matches(user_id: str, limit: int = 10):
    """Find users with shared interests, ranked by affinity."""
    matches = await graph.find_matches(user_id, limit=limit)
    return {"matches": matches, "count": len(matches)}


@router.get("/graph", response_model=GraphData)
async def get_graph(user_id: str, extra_ids: list[str] = Query(default=[])):
    """Get force-directed graph data for visualization."""
    all_ids = [user_id] + [eid for eid in extra_ids if eid != user_id]
    data = await graph.get_graph_data(user_id, all_ids)
    return data


@router.get("/interests")
async def get_interests(user_id: str):
    """Get all extracted interests for a user."""
    interests = await graph.get_user_interests(user_id)
    return {"interests": interests, "count": len(interests)}


@router.get("/session")
async def get_session(user_id: str):
    """Restore user session from Neo4j — returns user node + all ingested accounts."""
    from app.db.neo4j import get_session as get_db_session

    async with get_db_session() as session:
        # Get the primary user
        r = await session.run(
            "MATCH (u:User {id: $uid}) RETURN u.username AS username, u.full_name AS name",
            uid=user_id,
        )
        user_rec = await r.single()
        if not user_rec:
            return {"user_id": user_id, "exists": False, "accounts": []}

        # Find all completed ingest jobs linked to this user's username pattern
        username = user_rec["username"]
        r2 = await session.run(
            """
            MATCH (j:IngestJob)
            WHERE j.status IN ['completed', 'tier1_done', 'enriching']
            AND j.user_id <> $uid
            WITH j.username AS uname, j.user_id AS uid,
                 max(j.created_at) AS last_sync
            RETURN uname, uid, toString(last_sync) AS synced_at
            ORDER BY last_sync DESC
            """,
            uid=user_id,
        )
        accounts = []
        seen = set()
        async for rec in r2:
            uname = rec["uname"]
            if uname and uname not in seen:
                seen.add(uname)
                accounts.append({
                    "username": uname,
                    "syncedAt": rec["synced_at"] or "",
                    "jobId": "",
                    "status": "completed",
                })

        return {
            "user_id": user_id,
            "exists": True,
            "username": username,
            "accounts": accounts,
        }

