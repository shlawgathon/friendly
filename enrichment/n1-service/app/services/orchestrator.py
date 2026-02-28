import logging

from app.models.enrichment import (
    DeepEnrichRequest,
    DeepEnrichResponse,
    DeepInsight,
    VibeCompareRequest,
    VibeCompareResponse,
    VibeFingerprint,
)
from app.services.browser_agent import BrowserAgent
from app.services.graph_writer import GraphWriter
from app.services.vision import VisionAnalyzer

logger = logging.getLogger(__name__)


class DeepEnrichmentOrchestrator:
    """Ties the browser agent, vision analyzer, and graph writer together
    to run the full Tier 3 deep enrichment pipeline."""

    def __init__(self) -> None:
        self._vision = VisionAnalyzer()
        self._graph = GraphWriter()

    async def run_deep_enrichment(
        self, request: DeepEnrichRequest
    ) -> DeepEnrichResponse:
        """Execute the full deep enrichment pipeline for one user.

        Pipeline steps:
        1. Launch headless browser and navigate IG profile (capture screenshots)
        2. Extract interests from screenshots via Reka vision
        3. Generate vibe fingerprint from representative screenshots
        4. Build DeepInsight objects from the captured data
        5. Write everything to Neo4j
        6. Return DeepEnrichResponse
        """
        logger.info(
            "Starting deep enrichment for %s (url=%s, highlights=%d, scroll=%d)",
            request.username,
            request.instagram_url,
            request.max_highlights,
            request.scroll_depth,
        )

        # Step 1: Browser navigation and screenshot capture
        screenshots: list[bytes] = []
        try:
            async with BrowserAgent() as agent:
                screenshots = await agent.navigate_and_capture(
                    url=request.instagram_url,
                    max_highlights=request.max_highlights,
                    scroll_depth=request.scroll_depth,
                )
        except Exception:
            logger.exception(
                "Browser agent failed for %s", request.username
            )

        if not screenshots:
            logger.warning(
                "No screenshots captured for %s, returning empty enrichment",
                request.username,
            )
            return DeepEnrichResponse(
                username=request.username,
                status="completed_no_data",
            )

        # Step 2: Extract interests from screenshots
        discovered_interests: list[str] = []
        try:
            discovered_interests = await self._vision.extract_interests(screenshots)
            logger.info(
                "Discovered %d interests for %s",
                len(discovered_interests),
                request.username,
            )
        except Exception:
            logger.exception(
                "Interest extraction failed for %s", request.username
            )

        # Combine with provided interests and deduplicate
        all_interests = _deduplicate_interests(
            request.interests + discovered_interests
        )

        # Step 3: Generate vibe fingerprint
        vibe = VibeFingerprint()
        try:
            vibe = await self._vision.generate_vibe_fingerprint(screenshots)
            logger.info(
                "Generated vibe for %s: mood=%s, energy=%.2f, tags=%s",
                request.username,
                vibe.mood,
                vibe.energy,
                vibe.aesthetic_tags,
            )
        except Exception:
            logger.exception(
                "Vibe fingerprinting failed for %s", request.username
            )

        # Step 4: Build DeepInsight objects
        insights = _build_insights(
            screenshots=screenshots,
            discovered_interests=discovered_interests,
            instagram_url=request.instagram_url,
            max_highlights=request.max_highlights,
        )

        # Step 5: Write to Neo4j
        try:
            await self._graph.write_deep_insights(request.username, insights)
            await self._graph.write_vibe_profile(request.username, vibe)
            await self._graph.write_discovered_interests(
                request.username, discovered_interests
            )
            logger.info("Graph writes completed for %s", request.username)
        except Exception:
            logger.exception(
                "Graph writing failed for %s", request.username
            )

        # Step 6: Return response
        return DeepEnrichResponse(
            username=request.username,
            insights=insights,
            vibe=vibe,
            discovered_interests=all_interests,
            status="completed",
        )

    async def run_vibe_comparison(
        self, request: VibeCompareRequest
    ) -> VibeCompareResponse:
        """Compare the vibes of two Instagram profiles.

        1. Check Neo4j for existing VibeProfiles
        2. Run deep enrichment for any missing profiles
        3. Compute similarity
        4. Write SIMILAR_VIBE relationship
        5. Return comparison response
        """
        logger.info(
            "Starting vibe comparison: %s vs %s",
            request.username_a,
            request.username_b,
        )

        # Step 1-2: Get or create VibeProfiles for both users
        vibe_a = await self._get_or_create_vibe(
            username=request.username_a,
            instagram_url=request.instagram_url_a,
        )
        vibe_b = await self._get_or_create_vibe(
            username=request.username_b,
            instagram_url=request.instagram_url_b,
        )

        # Step 3: Compute similarity
        score, shared_aesthetics, shared_themes = VisionAnalyzer.compute_similarity(
            vibe_a, vibe_b
        )

        # Step 4: Write SIMILAR_VIBE relationship
        try:
            await self._graph.write_similar_vibe(
                username_a=request.username_a,
                username_b=request.username_b,
                score=score,
                shared_aesthetics=shared_aesthetics,
                shared_themes=shared_themes,
            )
        except Exception:
            logger.exception(
                "Failed to write SIMILAR_VIBE for %s <-> %s",
                request.username_a,
                request.username_b,
            )

        # Step 5: Return response
        return VibeCompareResponse(
            username_a=request.username_a,
            username_b=request.username_b,
            similarity_score=round(score, 4),
            shared_aesthetics=shared_aesthetics,
            shared_themes=shared_themes,
            vibe_a=vibe_a,
            vibe_b=vibe_b,
            status="completed",
        )

    async def _get_or_create_vibe(
        self, username: str, instagram_url: str
    ) -> VibeFingerprint:
        """Fetch an existing VibeProfile from Neo4j, or run deep enrichment to create one."""
        # Try to read existing
        existing = await self._graph.get_vibe_profile(username)
        if existing is not None:
            logger.info("Using existing VibeProfile for %s", username)
            return VibeFingerprint(**existing)

        # Run deep enrichment to generate the vibe
        logger.info(
            "No existing VibeProfile for %s, running deep enrichment", username
        )
        enrich_request = DeepEnrichRequest(
            username=username,
            instagram_url=instagram_url,
            max_highlights=2,
            scroll_depth=10,
        )
        result = await self.run_deep_enrichment(enrich_request)
        return result.vibe


def _build_insights(
    screenshots: list[bytes],
    discovered_interests: list[str],
    instagram_url: str,
    max_highlights: int,
) -> list[DeepInsight]:
    """Build DeepInsight objects from captured data.

    We categorize screenshots as either highlight captures or deep_post captures
    based on their position in the list. The first screenshot after any modal
    dismissals is the profile header. The next max_highlights screenshots are
    from highlights, and the rest are from post scrolling.
    """
    insights: list[DeepInsight] = []

    if not screenshots:
        return insights

    # The first screenshot is the profile header (skip for insights)
    # Next up to max_highlights are highlight content
    # Remaining are post scroll batches

    highlight_start = 1  # After profile header
    highlight_end = min(highlight_start + max_highlights, len(screenshots))
    post_start = highlight_end

    # Highlight insights
    for i in range(highlight_start, highlight_end):
        insight_index = i - highlight_start + 1
        insights.append(
            DeepInsight(
                type="highlight",
                content=f"Highlight #{insight_index} content from profile",
                source_url=instagram_url,
                interests_found=discovered_interests[:5],
            )
        )

    # Post scroll insights (group into batches)
    if post_start < len(screenshots):
        post_count = len(screenshots) - post_start
        insights.append(
            DeepInsight(
                type="deep_post",
                content=f"Deep scroll analysis of {post_count} post batches from profile grid",
                source_url=instagram_url,
                interests_found=discovered_interests,
            )
        )

    return insights


def _deduplicate_interests(interests: list[str]) -> list[str]:
    """Deduplicate interests case-insensitively while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for interest in interests:
        normalized = interest.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(interest.strip())
    return result
