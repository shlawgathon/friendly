"""Pioneer GLiNER2 — zero-shot named entity recognition."""
from __future__ import annotations

import asyncio
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)

# Labels to extract for social graph
DEFAULT_LABELS = ["hobby", "location", "brand", "activity", "sport", "food", "music", "art"]

_extractor = None


def _get_extractor():
    global _extractor
    if _extractor is None:
        os.environ["PIONEER_API_KEY"] = settings.pioneer_api_key
        from gliner2 import GLiNER2
        _extractor = GLiNER2.from_api()
        logger.info("Pioneer GLiNER2 API client initialized")
    return _extractor


async def extract_entities(text: str, labels: list[str] | None = None) -> dict:
    """Extract entities from text using Pioneer's GLiNER2 zero-shot NER.

    Returns dict like: {"entities": {"hobby": ["rock climbing"], "location": ["Joshua Tree"]}}
    """
    if not text or not text.strip():
        return {"entities": {}}

    use_labels = labels or DEFAULT_LABELS
    extractor = _get_extractor()

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(extractor.extract_entities, text, use_labels),
            timeout=settings.api_timeout_seconds,
        )
        # Normalize: result may be {"entities": {...}} or list format
        if isinstance(result, dict) and "entities" in result:
            entities = result["entities"]
        else:
            entities = result

        # Count total extracted
        total = sum(len(v) if isinstance(v, list) else 1 for v in entities.values()) if isinstance(entities, dict) else 0
        logger.info("Pioneer extracted %d entities from %d chars", total, len(text))
        return {"entities": entities if isinstance(entities, dict) else {}}
    except asyncio.TimeoutError:
        logger.warning("Pioneer timeout on %d chars", len(text))
        return {"entities": {}}
    except Exception as e:
        logger.error("Pioneer error: %s", e)
        return {"entities": {}}
