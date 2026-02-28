"""Pioneer GLiNER2 — zero-shot named entity recognition via HTTP API."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Labels to extract for social graph
DEFAULT_LABELS = ["hobby", "location", "brand", "activity", "sport", "food", "music", "art"]

_BASE_URL = "https://api.pioneer.ai"


async def extract_entities(text: str, labels: list[str] | None = None, threshold: float = 0.5) -> dict:
    """Extract entities from text using Pioneer's GLiNER2 zero-shot NER.

    Calls POST https://api.pioneer.ai/gliner-2
    Returns dict like: {"entities": {"hobby": ["rock climbing"], "location": ["Joshua Tree"]}}
    """
    if not text or not text.strip():
        return {"entities": {}}

    use_labels = labels or DEFAULT_LABELS

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            resp = await client.post(
                f"{_BASE_URL}/gliner-2",
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": settings.pioneer_api_key,
                },
                json={
                    "task": "extract_entities",
                    "text": text,
                    "schema": use_labels,
                    "threshold": threshold,
                },
            )
            resp.raise_for_status()
            result = resp.json()

        # Normalize response
        if isinstance(result, dict) and "entities" in result:
            entities = result["entities"]
        else:
            entities = result

        # Count total extracted
        total = sum(len(v) if isinstance(v, list) else 1 for v in entities.values()) if isinstance(entities, dict) else 0
        logger.info("Pioneer extracted %d entities from %d chars", total, len(text))
        return {"entities": entities if isinstance(entities, dict) else {}}

    except httpx.TimeoutException:
        logger.warning("Pioneer timeout on %d chars", len(text))
        return {"entities": {}}
    except Exception as e:
        logger.error("Pioneer error: %s", e)
        return {"entities": {}}
