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
