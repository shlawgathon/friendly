"""Instagram scraper — HTTP client for Atlas Pipeline scraper-standalone."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Shared async client (connection pooling)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.scraper_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.scraper_api_key}",
            },
            timeout=httpx.Timeout(90.0, connect=10.0),
        )
    return _client


async def scrape_instagram(
    username: str, max_posts: int = 10, include_reels: bool = True
) -> dict:
    """Scrape Instagram profile and posts via scraper-standalone.

    Calls POST /scrape/instagram on the Atlas Pipeline scraper-standalone service.
    Returns {"profile": {...}, "posts": [...], "reels": [...]}.
    """
    capped_max = min(max_posts, settings.max_posts_hard_limit)
    client = _get_client()

    try:
        resp = await client.post(
            "/scrape/instagram",
            json={
                "username": username,
                "maxPosts": capped_max,
                "includeReels": include_reels,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # Normalize field names to match what pipeline.py expects
        profile = data.get("profile", {})
        posts = data.get("posts", [])
        reels = data.get("reels", [])

        # Map scraper-standalone profile fields → legacy field names used by pipeline.py
        normalized_profile = {
            "username": profile.get("username", username),
            "fullName": profile.get("fullName", profile.get("full_name", "")),
            "biography": profile.get("biography", profile.get("bio", "")),
            "profilePicUrl": profile.get("profilePicUrl", profile.get("profilePicUrlHd", "")),
            "externalUrl": profile.get("externalUrl", profile.get("external_url", "")),
            "isPrivate": profile.get("isPrivate", False),
            "followers": profile.get("followerCount", profile.get("followers", 0)),
            "followees": profile.get("followingCount", profile.get("followees", 0)),
        }

        logger.info(
            "Scraped @%s via scraper-standalone: %d posts, %d reels, private=%s",
            username, len(posts), len(reels), normalized_profile["isPrivate"],
        )

        return {
            "profile": normalized_profile,
            "posts": posts,
            "reels": reels,
        }

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text
        if status == 401:
            logger.error("Scraper auth failed (check SCRAPER_API_KEY)")
            raise RuntimeError("Scraper authentication failed") from e
        if status == 400:
            logger.error("Bad scraper request for @%s: %s", username, body)
            raise ValueError(f"Bad scraper request: {body}") from e
        logger.error("Scraper HTTP %d for @%s: %s", status, username, body)
        raise
    except httpx.TimeoutException:
        logger.error("Scraper timeout for @%s", username)
        raise
    except Exception as e:
        logger.error("Scraper error for @%s: %s", username, e)
        raise
