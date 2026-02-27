"""Reka multimodal analysis — image captioning and icebreaker generation."""
from __future__ import annotations

import asyncio
import logging

from reka.client import Reka

from app.config import settings

logger = logging.getLogger(__name__)

_client: Reka | None = None
_semaphore: asyncio.Semaphore | None = None


def _get_client() -> Reka:
    global _client
    if _client is None:
        _client = Reka(api_key=settings.reka_api_key)
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_parallel_reka_calls)
    return _semaphore


async def analyze_image(image_url: str, caption: str = "") -> str:
    """Analyze an image URL and return a description of activities/interests."""
    sem = _get_semaphore()
    async with sem:
        client = _get_client()

        context = f" This image is from a post captioned: '{caption[:100]}'." if caption else ""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat.create,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": image_url},
                                {
                                    "type": "text",
                                    "text": (
                                        f"What hobby or activity is the person in this photo DOING?{context} "
                                        "Only describe what you are CERTAIN about. "
                                        "ONLY name a brand if you can clearly READ the brand name/logo TEXT in the image. "
                                        "Do NOT guess brands from the shape or style of objects. "
                                        "Be concise: 1-2 sentences max. If unclear, say 'unclear'."
                                    ),
                                },
                            ],
                        }
                    ],
                    model="reka-flash",
                ),
                timeout=settings.api_timeout_seconds,
            )
            text = response.responses[0].message.content
            logger.info("Reka analyzed image: %.80s...", text)
            return text
        except asyncio.TimeoutError:
            logger.warning("Reka timeout for image: %s", image_url[:80])
            raise
        except Exception as e:
            logger.error("Reka error: %s", e)
            raise


async def generate_icebreaker(user_interests: list[str], target_interests: list[str], shared: list[str]) -> str:
    """Generate a conversation icebreaker based on shared interests."""
    client = _get_client()
    prompt = (
        f"Two people share these interests: {', '.join(shared)}. "
        f"Person A is also into: {', '.join(user_interests[:5])}. "
        f"Person B is also into: {', '.join(target_interests[:5])}. "
        f"Generate a single, natural conversation starter that references their shared "
        f"interests. Make it feel personal and specific, not generic. "
        f"Just the icebreaker text, no quotes or labels."
    )
    response = await asyncio.to_thread(
        client.chat.create,
        messages=[{"role": "user", "content": prompt}],
        model="reka-flash",
    )
    return response.responses[0].message.content


async def extract_interests(text: str) -> dict:
    """Use Reka to extract structured interests/entities from combined text.

    Returns dict like: {"entities": {"hobby": ["rock climbing"], "location": ["Joshua Tree"]}}
    """
    import json as _json

    if not text or not text.strip():
        return {"entities": {}}

    client = _get_client()
    prompt = (
        "Analyze this Instagram user's content and list their MAIN hobbies and interests.\n\n"
        "STRICT RULES:\n"
        "- Extract high-level hobbies only (e.g. 'motorcycle' NOT 'riding', 'inspection', 'maintenance')\n"
        "- ONE word per interest when possible (e.g. 'motorcycle' not 'motorcycle riding')\n"
        "- ONLY include brands that are EXPLICITLY mentioned by name in the text — do NOT guess brands\n"
        "- If the text says 'Yamaha R7' include 'yamaha'. If it just says 'sport motorcycle' do NOT guess a brand\n"
        "- NO generic verbs/actions (riding, sitting, wearing, inspecting = SKIP)\n"
        "- NO generic activities (customization, modification, tuning, maintenance = SKIP)\n"
        "- NO visual descriptions (carbon fiber, chrome, leather = SKIP)\n"
        "- NO duplicates — if 3 photos show motorcycles, output 'motorcycle' ONCE\n"
        "- Max 3 interests total — only the MOST prominent ones\n\n"
        "Categories: hobby, brand\n\n"
        f"Content:\n{text[:3000]}\n\n"
        "Return ONLY a JSON object, no markdown:"
    )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.create,
                messages=[{"role": "user", "content": prompt}],
                model="reka-flash",
            ),
            timeout=settings.api_timeout_seconds,
        )
        raw = response.responses[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        entities = _json.loads(raw)
        total = sum(len(v) if isinstance(v, list) else 1 for v in entities.values())
        logger.info("Reka extracted %d entities from %d chars", total, len(text))
        return {"entities": entities}
    except _json.JSONDecodeError as e:
        logger.warning("Reka interest extraction returned non-JSON: %.100s", raw)
        return {"entities": {}}
    except asyncio.TimeoutError:
        logger.warning("Reka interest extraction timeout")
        return {"entities": {}}
    except Exception as e:
        logger.error("Reka interest extraction error: %s", e)
        return {"entities": {}}

