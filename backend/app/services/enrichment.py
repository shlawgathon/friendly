"""Enrichment service client — calls Tier 2 (browsing) and Tier 3 (n1) via HTTP."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def run_tier2_enrichment(
    username: str, interests: list[str], location: str | None = None
) -> dict:
    """Call browsing-service (Tier 2) to find events, communities, meetups."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.browsing_service_url}/api/enrich/browse",
                json={
                    "username": username,
                    "interests": interests[:3],
                    "location": location,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "Tier 2 enrichment for @%s: %d events, %d communities, %d meetups",
                username,
                len(data.get("events", [])),
                len(data.get("communities", [])),
                len(data.get("meetups", [])),
            )
            return data
    except httpx.TimeoutException:
        logger.warning("Tier 2 timeout for @%s", username)
        return {"status": "timeout", "events": [], "communities": [], "meetups": []}
    except Exception as e:
        logger.error("Tier 2 error for @%s: %s", username, e)
        return {"status": "error", "error": str(e), "events": [], "communities": [], "meetups": []}


async def run_tier3_enrichment(
    username: str, instagram_url: str, interests: list[str]
) -> dict:
    """Call n1-service (Tier 3) for deep vibe fingerprinting."""
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.n1_service_url}/api/enrich/deep",
                json={
                    "username": username,
                    "instagram_url": instagram_url,
                    "interests": interests[:5],
                    "max_highlights": 2,
                    "scroll_depth": 10,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "Tier 3 enrichment for @%s: vibe_mood=%s, %d insights",
                username,
                data.get("vibe", {}).get("mood", "unknown"),
                len(data.get("insights", [])),
            )
            return data
    except httpx.TimeoutException:
        logger.warning("Tier 3 timeout for @%s", username)
        return {"status": "timeout", "vibe": {}, "insights": []}
    except Exception as e:
        logger.error("Tier 3 error for @%s: %s", username, e)
        return {"status": "error", "error": str(e), "vibe": {}, "insights": []}
