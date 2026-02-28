import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.neo4j import get_session
from app.models.enrichment import (
    BrowseEnrichRequest,
    BrowseEnrichResponse,
    CommunityResult,
    EventResult,
    MeetupResult,
    ProfileEnrichRequest,
)
from app.services.browsing import YutoriBrowsingClient
from app.services.graph_writer import GraphWriter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enrich", tags=["enrichment"])


async def _enrich_single_interest(
    client: YutoriBrowsingClient,
    interest: str,
    location: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Run all browsing tasks for a single interest in parallel.

    Returns a dict with keys "events", "communities", "meetups" each
    containing a list of raw result dicts.
    """
    tasks: list[asyncio.Task[Any]] = []
    task_labels: list[str] = []

    # Always search events (use location or a broad fallback)
    search_location = location or "United States"
    tasks.append(
        asyncio.create_task(client.search_events(interest, search_location))
    )
    task_labels.append("events")

    # Always search communities (Reddit does not need location)
    tasks.append(asyncio.create_task(client.search_communities(interest)))
    task_labels.append("communities")

    # Only search meetups if we have a location
    if location:
        tasks.append(
            asyncio.create_task(client.search_meetups(interest, location))
        )
        task_labels.append("meetups")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: dict[str, list[dict[str, Any]]] = {
        "events": [],
        "communities": [],
        "meetups": [],
    }

    for label, result in zip(task_labels, results):
        if isinstance(result, Exception):
            logger.error(
                "Task %s for interest '%s' failed: %s",
                label,
                interest,
                result,
            )
            continue
        if isinstance(result, list):
            output[label] = result

    return output


@router.post("/browse", response_model=BrowseEnrichResponse)
async def browse_enrich(req: BrowseEnrichRequest) -> BrowseEnrichResponse:
    """Tier 2 browsing enrichment.

    For each interest (capped at 3), dispatches parallel Yutori browsing tasks
    to search Eventbrite, Reddit, and Meetup. Writes results to Neo4j and
    returns the aggregated enrichment data.
    """
    logger.info(
        "Browse enrich request: username=%s, interests=%s, location=%s",
        req.username,
        req.interests,
        req.location,
    )

    interests = req.interests[:3]
    if not interests:
        return BrowseEnrichResponse(username=req.username, status="no_interests")

    client = YutoriBrowsingClient()

    # Run enrichment for all interests in parallel
    interest_tasks = [
        _enrich_single_interest(client, interest, req.location)
        for interest in interests
    ]
    interest_results = await asyncio.gather(*interest_tasks, return_exceptions=True)

    # Aggregate results across all interests
    all_events: list[EventResult] = []
    all_communities: list[CommunityResult] = []
    all_meetups: list[MeetupResult] = []

    for interest, result in zip(interests, interest_results):
        if isinstance(result, Exception):
            logger.error(
                "Enrichment for interest '%s' failed: %s", interest, result
            )
            continue

        events_raw = result.get("events", [])
        communities_raw = result.get("communities", [])
        meetups_raw = result.get("meetups", [])

        # Parse into Pydantic models (skip malformed entries)
        for evt in events_raw:
            try:
                all_events.append(EventResult(**evt))
            except Exception:
                logger.warning("Skipping malformed event: %s", evt)

        for comm in communities_raw:
            try:
                all_communities.append(CommunityResult(**comm))
            except Exception:
                logger.warning("Skipping malformed community: %s", comm)

        for mt in meetups_raw:
            try:
                all_meetups.append(MeetupResult(**mt))
            except Exception:
                logger.warning("Skipping malformed meetup: %s", mt)

        # Write to Neo4j
        try:
            async with get_session() as session:
                writer = GraphWriter(session)
                counts = await writer.write_browse_results(
                    username=req.username,
                    interest=interest,
                    events=events_raw,
                    communities=communities_raw,
                    meetups=meetups_raw,
                )
                logger.info(
                    "Graph write for interest '%s': %s", interest, counts
                )
        except Exception:
            logger.exception(
                "Failed to write graph for interest '%s'", interest
            )

    # Deduplicate by URL
    seen_urls: set[str] = set()
    deduped_events: list[EventResult] = []
    for e in all_events:
        if e.url not in seen_urls:
            seen_urls.add(e.url)
            deduped_events.append(e)

    deduped_communities: list[CommunityResult] = []
    for c in all_communities:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            deduped_communities.append(c)

    deduped_meetups: list[MeetupResult] = []
    for m in all_meetups:
        if m.url not in seen_urls:
            seen_urls.add(m.url)
            deduped_meetups.append(m)

    logger.info(
        "Browse enrich complete for %s: %d events, %d communities, %d meetups",
        req.username,
        len(deduped_events),
        len(deduped_communities),
        len(deduped_meetups),
    )

    return BrowseEnrichResponse(
        username=req.username,
        events=deduped_events,
        communities=deduped_communities,
        meetups=deduped_meetups,
        status="completed",
    )


@router.post("/profile")
async def profile_enrich(req: ProfileEnrichRequest) -> dict[str, Any]:
    """Extract profile information from a public URL found in a user's bio.

    Dispatches a Yutori browsing task to navigate the URL and extract
    structured profile data (name, headline, interests, social links).
    """
    logger.info(
        "Profile enrich request: username=%s, url=%s", req.username, req.url
    )

    client = YutoriBrowsingClient()
    profile_data = await client.extract_profile(req.url)

    if profile_data is None:
        raise HTTPException(
            status_code=502,
            detail="Failed to extract profile data from the given URL",
        )

    return {
        "username": req.username,
        "source_url": req.url,
        "profile": profile_data,
        "status": "completed",
    }
