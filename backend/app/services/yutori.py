"""Yutori Research + Scouting — submit-only async tasks."""
from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, wait_random, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.yutori.com/v1"
HEADERS = {
    "X-API-Key": "",  # set at call time
    "Content-Type": "application/json",
}


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.yutori_api_key, "Content-Type": "application/json"}


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_backoff_multiplier, max=settings.retry_backoff_max)
    + wait_random(0, 2),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
)
async def submit_research_task(
    interest: str,
    webhook_url: str | None = None,
) -> dict:
    """Submit a one-time deep research task for an interest.

    Returns: {"task_id": "...", "status": "queued", "view_url": "..."}
    """
    body: dict = {
        "query": (
            f"What are the latest communities, events, meetups, trends, "
            f"and popular content related to '{interest}'? "
            f"Include specific names, locations, and online communities."
        ),
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Name of community/event/trend"},
                    "summary": {"type": "string", "description": "Brief description"},
                    "category": {"type": "string", "description": "community|event|trend|content"},
                    "source_url": {"type": "string", "description": "URL for more details"},
                },
            },
        },
        "user_timezone": "America/Los_Angeles",
    }
    if webhook_url:
        body["webhook_url"] = webhook_url

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        resp = await client.post(f"{BASE_URL}/research/tasks", headers=_headers(), json=body)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Yutori Research submitted for '%s': task_id=%s", interest, result.get("task_id"))
        return result


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_backoff_multiplier, max=settings.retry_backoff_max)
    + wait_random(0, 2),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
)
async def submit_scouting_task(
    interest: str,
    output_interval: int = 86400,
    webhook_url: str | None = None,
) -> dict:
    """Submit a recurring scouting task to monitor an interest.

    Returns: {"id": "...", "query": "...", "next_run_timestamp": "..."}
    """
    body: dict = {
        "query": (
            f"Monitor for new events, meetups, trending content, "
            f"community discussions, and notable developments related to '{interest}'."
        ),
        "output_interval": max(output_interval, 1800),  # min 30 minutes
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string", "description": "News headline"},
                    "summary": {"type": "string", "description": "Brief summary"},
                    "source_url": {"type": "string", "description": "URL for more details"},
                },
            },
        },
        "user_timezone": "America/Los_Angeles",
        "skip_email": True,
    }
    if webhook_url:
        body["webhook_url"] = webhook_url
        body["webhook_format"] = "scout"

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        resp = await client.post(f"{BASE_URL}/scouting/tasks", headers=_headers(), json=body)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Yutori Scouting submitted for '%s': id=%s", interest, result.get("id"))
        return result


async def get_research_task_status(task_id: str) -> dict:
    """Poll a research task's status."""
    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        resp = await client.get(f"{BASE_URL}/research/tasks/{task_id}", headers=_headers())
        resp.raise_for_status()
        return resp.json()
