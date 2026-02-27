"""Yutori webhook route — receives async task completions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.workers.yutori_poller import handle_yutori_completion
from app.services import graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/yutori")
async def yutori_webhook(request: Request):
    """Receive Yutori task completion callbacks. Idempotent."""
    payload = await request.json()
    logger.info("Yutori webhook received: %s", {k: v for k, v in payload.items() if k != "result"})

    # Extract task_id from different Yutori payload formats
    task_id = payload.get("task_id") or payload.get("id")
    if not task_id:
        logger.warning("Yutori webhook missing task_id: %s", payload.keys())
        return {"status": "ignored", "reason": "no task_id"}

    # Look up the task record to get user_id and interest
    from app.db.neo4j import get_session
    async with get_session() as session:
        result = await session.run(
            "MATCH (t:TaskRecord {provider_task_id: $ptid}) RETURN t",
            ptid=task_id,
        )
        record = await result.single()

    if not record:
        logger.warning("Yutori webhook for unknown task: %s", task_id)
        return {"status": "ignored", "reason": "unknown task"}

    task = dict(record["t"])
    was_new = await handle_yutori_completion(
        provider_task_id=task_id,
        result=payload,
        interest=task.get("interest", ""),
        user_id=task.get("user_id", ""),
    )

    return {"status": "processed" if was_new else "duplicate"}
