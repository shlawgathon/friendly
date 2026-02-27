"""Icebreaker chat route — Reka-powered conversation starters."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.dto import IcebreakerRequest, IcebreakerResponse
from app.services import graph, reka

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/icebreaker", response_model=IcebreakerResponse)
async def generate_icebreaker(req: IcebreakerRequest):
    """Generate a context-aware icebreaker between two users."""
    user_interests = await graph.get_user_interests(req.user_id)
    target_interests = await graph.get_user_interests(req.target_user_id)

    if not user_interests or not target_interests:
        raise HTTPException(status_code=404, detail="One or both users have no interests yet")

    user_hobbies = [i["hobby"] for i in user_interests]
    target_hobbies = [i["hobby"] for i in target_interests]
    shared = list(set(user_hobbies) & set(target_hobbies))

    if not shared:
        raise HTTPException(status_code=404, detail="No shared interests found")

    icebreaker = await reka.generate_icebreaker(user_hobbies, target_hobbies, shared)

    return IcebreakerResponse(icebreaker=icebreaker, shared_context=shared)
