import logging

from fastapi import APIRouter, HTTPException

from app.models.enrichment import (
    DeepEnrichRequest,
    DeepEnrichResponse,
    VibeCompareRequest,
    VibeCompareResponse,
)
from app.services.orchestrator import DeepEnrichmentOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enrich", tags=["enrichment"])

_orchestrator = DeepEnrichmentOrchestrator()


@router.post("/deep", response_model=DeepEnrichResponse)
async def deep_enrich(request: DeepEnrichRequest) -> DeepEnrichResponse:
    """Run full Tier 3 deep enrichment on an Instagram profile.

    Pipeline: browser navigation -> screenshot capture -> Reka vision analysis
    -> vibe fingerprinting -> Neo4j graph writing.
    """
    logger.info(
        "POST /api/enrich/deep — username=%s, url=%s, highlights=%d, scroll=%d",
        request.username,
        request.instagram_url,
        request.max_highlights,
        request.scroll_depth,
    )

    try:
        result = await _orchestrator.run_deep_enrichment(request)
        logger.info(
            "Deep enrichment completed for %s: %d insights, %d interests, vibe_mood=%s",
            request.username,
            len(result.insights),
            len(result.discovered_interests),
            result.vibe.mood,
        )
        return result

    except Exception as exc:
        logger.exception("Deep enrichment failed for %s", request.username)
        raise HTTPException(
            status_code=500,
            detail=f"Deep enrichment failed: {exc}",
        ) from exc


@router.post("/vibe-compare", response_model=VibeCompareResponse)
async def vibe_compare(request: VibeCompareRequest) -> VibeCompareResponse:
    """Compare the vibe fingerprints of two Instagram profiles.

    Runs deep enrichment for any profile missing a VibeProfile, then
    computes similarity and writes SIMILAR_VIBE relationships to Neo4j.
    """
    logger.info(
        "POST /api/enrich/vibe-compare — %s vs %s",
        request.username_a,
        request.username_b,
    )

    if request.username_a == request.username_b:
        raise HTTPException(
            status_code=400,
            detail="Cannot compare a user to themselves",
        )

    try:
        result = await _orchestrator.run_vibe_comparison(request)
        logger.info(
            "Vibe comparison completed: %s vs %s — score=%.3f, shared_aesthetics=%s",
            request.username_a,
            request.username_b,
            result.similarity_score,
            result.shared_aesthetics,
        )
        return result

    except Exception as exc:
        logger.exception(
            "Vibe comparison failed for %s vs %s",
            request.username_a,
            request.username_b,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Vibe comparison failed: {exc}",
        ) from exc
