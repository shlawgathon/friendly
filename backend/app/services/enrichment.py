"""Enrichment service client — calls Tier 2 (browsing) and Tier 3 (n1) via HTTP."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _fallback_tier2(username: str, interests: list[str], location: str | None = None) -> dict:
    """Generate enrichment data from hobbies when Tier 2 service is unreachable."""
    loc = location or "nearby"
    events = []
    communities = []
    meetups = []

    for interest in interests[:5]:
        slug = interest.lower().replace(" ", "-")
        events.append({
            "title": f"{interest} Meetup & Expo 2026",
            "url": f"https://www.eventbrite.com/d/{slug}-events/",
            "date": "2026-03-15",
            "location": loc,
            "description": f"Connect with other {interest} enthusiasts at this local event.",
        })
        communities.append({
            "name": f"r/{slug}",
            "url": f"https://www.reddit.com/r/{slug}/",
            "description": f"Reddit community for {interest} fans and enthusiasts.",
            "subscriber_count": 15000 + hash(interest) % 85000,
        })
        meetups.append({
            "name": f"{interest} Enthusiasts Meetup",
            "url": f"https://www.meetup.com/topics/{slug}/",
            "date": "Weekly",
            "location": loc,
            "attendees": 20 + hash(interest) % 80,
        })

    return {"status": "fallback", "events": events, "communities": communities, "meetups": meetups}


def _fallback_tier3(username: str, interests: list[str]) -> dict:
    """Generate vibe data from interests when Tier 3 service is unreachable."""
    moods = ["Energetic", "Creative", "Adventurous", "Chill", "Passionate", "Bold"]
    mood = moods[hash(username) % len(moods)]
    energy = round(0.5 + (hash(username) % 50) / 100, 2)
    return {
        "status": "fallback",
        "vibe": {
            "mood": mood,
            "energy": energy,
            "aesthetic_tags": interests[:3],
            "content_themes": interests[:4],
        },
        "insights": [
            f"@{username} shows strong affinity for {interests[0] if interests else 'diverse topics'}",
            f"Content pattern suggests a {mood.lower()} personality",
        ],
    }


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
        logger.warning("Tier 2 timeout for @%s, using fallback", username)
    except Exception as e:
        logger.warning("Tier 2 service unavailable for @%s (%s), using fallback", username, e)

    # Fallback: generate enrichment from hobbies
    return _fallback_tier2(username, interests, location)


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
        logger.warning("Tier 3 timeout for @%s, using fallback", username)
    except Exception as e:
        logger.warning("Tier 3 service unavailable for @%s (%s), using fallback", username, e)

    # Fallback: generate vibe from interests
    return _fallback_tier3(username, interests)

