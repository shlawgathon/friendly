"""Yutori polling worker — checks pending tasks every 5 minutes."""
from __future__ import annotations

import asyncio
import json
import logging

from app.services import graph, yutori, pioneer

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
STALE_THRESHOLD_MINUTES = 10


async def start_poller() -> None:
    """Background loop that polls Yutori for stale pending tasks."""
    logger.info("Yutori poller started (interval=%ds, threshold=%dm)",
                POLL_INTERVAL_SECONDS, STALE_THRESHOLD_MINUTES)
    while True:
        try:
            await _poll_once()
        except Exception as e:
            logger.error("Poller error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _poll_once() -> None:
    pending = await graph.get_pending_tasks(older_than_minutes=STALE_THRESHOLD_MINUTES)
    if not pending:
        return

    logger.info("Polling %d stale Yutori tasks", len(pending))
    for task in pending:
        try:
            if task["task_type"] == "research":
                status_data = await yutori.get_research_task_status(task["provider_task_id"])
                if status_data.get("status") in ("succeeded", "completed"):
                    await handle_yutori_completion(
                        provider_task_id=task["provider_task_id"],
                        result=status_data,
                        interest=task["interest"],
                        user_id=task["user_id"],
                    )
        except Exception as e:
            logger.warning("Poll failed for task %s: %s", task["provider_task_id"], e)


async def handle_yutori_completion(
    provider_task_id: str,
    result: dict,
    interest: str,
    user_id: str,
) -> bool:
    """Process a completed Yutori task. Returns True if newly completed (not duplicate)."""
    result_json = json.dumps(result)

    # Idempotent: if already completed, skip
    was_new = await graph.complete_task_record(provider_task_id, result_json)
    if not was_new:
        logger.info("Task %s already completed, skipping (idempotent)", provider_task_id)
        return False

    # Extract entities from the research results
    structured = result.get("structured_result") or result.get("result", "")
    if isinstance(structured, list):
        text_parts = [item.get("summary", "") + " " + item.get("title", "") for item in structured if isinstance(item, dict)]
        text = " ".join(text_parts)
    elif isinstance(structured, str):
        text = structured
    else:
        text = str(structured)

    if text.strip():
        extraction = await pioneer.extract_entities(text)
        entities = extraction.get("entities", {})
        count = await graph.add_entities_from_extraction(user_id, entities, source="research")
        logger.info("Yutori enrichment for '%s': %d entities added", interest, count)

    return True
