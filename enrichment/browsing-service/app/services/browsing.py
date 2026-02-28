import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

YUTORI_BASE_URL = "https://api.yutori.com/v1"


class YutoriBrowsingClient:
    """Client for the Yutori Browsing API — dispatches cloud browser agents."""

    def __init__(self) -> None:
        self._api_key = settings.yutori_api_key
        self._base_url = YUTORI_BASE_URL

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    # ── Core task methods ────────────────────────────────────────

    async def create_task(self, task: str, output_schema: dict[str, Any]) -> str:
        """Create a Yutori browsing task and return its task ID."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/browsing/tasks",
                headers=self._headers(),
                json={"task": task, "output_schema": output_schema},
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data["id"]
            logger.info("Created browsing task %s", task_id)
            return task_id

    async def poll_task(
        self,
        task_id: str,
        timeout: float = 120,
        interval: float = 3,
    ) -> dict[str, Any] | None:
        """Poll a Yutori browsing task until completed or timeout."""
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < timeout:
                resp = await client.get(
                    f"{self._base_url}/browsing/tasks/{task_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "unknown")

                if status == "completed":
                    logger.info("Task %s completed", task_id)
                    return data.get("output")
                elif status == "failed":
                    logger.error(
                        "Task %s failed: %s",
                        task_id,
                        data.get("error", "unknown error"),
                    )
                    return None

                await asyncio.sleep(interval)
                elapsed += interval

        logger.warning("Task %s timed out after %.0fs", task_id, timeout)
        return None

    async def run_task(
        self,
        task: str,
        output_schema: dict[str, Any],
    ) -> dict[str, Any] | list[Any] | None:
        """Create a browsing task, poll until done, and return the output."""
        try:
            task_id = await self.create_task(task, output_schema)
            return await self.poll_task(task_id)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Yutori API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except httpx.RequestError as exc:
            logger.error("Yutori request failed: %s", exc)
            return None

    # ── Convenience methods ──────────────────────────────────────

    async def search_events(self, interest: str, location: str) -> list[dict[str, Any]]:
        """Search Eventbrite for upcoming events matching an interest near a location."""
        task_prompt = (
            f"Go to eventbrite.com and search for '{interest}' events near "
            f"'{location}'. Return the top 3 results as JSON with title, date, "
            f"location, url, description."
        )
        output_schema: dict[str, Any] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "date", "url"],
            },
        }

        logger.info("Searching events: interest=%s, location=%s", interest, location)
        result = await self.run_task(task_prompt, output_schema)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return result["items"]
        return []

    async def search_communities(self, interest: str) -> list[dict[str, Any]]:
        """Search Reddit for active communities about an interest."""
        task_prompt = (
            f"Go to reddit.com and search for subreddits about '{interest}'. "
            f"Return the top 3 active communities as JSON with name, "
            f"subscriber_count, description, url."
        )
        output_schema: dict[str, Any] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "subscriber_count": {"type": "integer"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name", "url"],
            },
        }

        logger.info("Searching communities: interest=%s", interest)
        result = await self.run_task(task_prompt, output_schema)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return result["items"]
        return []

    async def search_meetups(self, interest: str, location: str) -> list[dict[str, Any]]:
        """Search Meetup for local groups matching an interest near a location."""
        task_prompt = (
            f"Go to meetup.com and search for '{interest}' groups near "
            f"'{location}'. Return the top 3 groups as JSON with name, date, "
            f"location, url, attendees."
        )
        output_schema: dict[str, Any] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "date": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                    "attendees": {"type": "integer"},
                },
                "required": ["name", "url"],
            },
        }

        logger.info(
            "Searching meetups: interest=%s, location=%s", interest, location
        )
        result = await self.run_task(task_prompt, output_schema)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return result["items"]
        return []

    async def extract_profile(self, url: str) -> dict[str, Any] | None:
        """Extract profile information from a public profile URL."""
        task_prompt = (
            f"Go to {url} and extract the person's name, headline, interests, "
            f"and any social links. Return as JSON."
        )
        output_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "headline": {"type": "string"},
                "interests": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "social_links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "platform": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["name"],
        }

        logger.info("Extracting profile from %s", url)
        result = await self.run_task(task_prompt, output_schema)
        if isinstance(result, dict):
            return result
        return None
