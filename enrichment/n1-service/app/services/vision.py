import base64
import json
import logging
from typing import Any

import reka

from app.config import settings
from app.models.enrichment import VibeFingerprint

logger = logging.getLogger(__name__)

REKA_MODEL = "reka-flash"

INTEREST_EXTRACTION_PROMPT = (
    "Analyze this image from an Instagram profile. "
    "Describe the activities, hobbies, and interests visible in this image. "
    'Return your answer as JSON only: {"interests": ["interest1", "interest2", ...]}. '
    "Focus on concrete, specific interests (e.g. 'rock climbing', 'watercolor painting', "
    "'coffee brewing') rather than vague terms. Return at most 10 interests."
)

VIBE_FINGERPRINT_PROMPT = (
    "Analyze these images from an Instagram profile. Determine the overall aesthetic "
    "style and vibe of this person's content. Return JSON only with these fields:\n"
    "- aesthetic_tags: list of style descriptors (e.g. 'minimalist', 'outdoor', "
    "'warm tones', 'vintage', 'urban', 'cozy', 'high contrast')\n"
    "- color_palette: list of dominant color families (e.g. 'earth tones', 'blues', "
    "'pastels', 'monochrome', 'warm neutrals')\n"
    "- mood: a single word describing the overall mood (e.g. 'adventurous', "
    "'peaceful', 'energetic', 'nostalgic', 'playful')\n"
    "- energy: a float from 0.0 (calm, serene) to 1.0 (energetic, dynamic)\n"
    "- content_themes: list of recurring topics/themes (e.g. 'travel', 'food', "
    "'fitness', 'nature', 'art', 'fashion', 'music')\n\n"
    "Return valid JSON only, nothing else."
)


class VisionAnalyzer:
    """Reka-powered screenshot analysis and vibe fingerprinting."""

    def __init__(self) -> None:
        self._client = reka.Reka(api_key=settings.reka_api_key)

    async def extract_interests(self, screenshots: list[bytes]) -> list[str]:
        """Analyze screenshots and extract a deduplicated list of interests."""
        all_interests: list[str] = []

        for i, screenshot_bytes in enumerate(screenshots):
            try:
                b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                interests = self._extract_interests_from_single(b64)
                all_interests.extend(interests)
                logger.info(
                    "Extracted %d interests from screenshot %d/%d",
                    len(interests),
                    i + 1,
                    len(screenshots),
                )
            except Exception:
                logger.exception(
                    "Failed to extract interests from screenshot %d", i + 1
                )

        # Deduplicate while preserving order, case-insensitive
        seen: set[str] = set()
        deduplicated: list[str] = []
        for interest in all_interests:
            normalized = interest.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduplicated.append(interest.strip())

        logger.info("Total unique interests extracted: %d", len(deduplicated))
        return deduplicated

    def _extract_interests_from_single(self, screenshot_b64: str) -> list[str]:
        """Call Reka to extract interests from a single base64 screenshot."""
        response = self._client.chat.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": f"data:image/png;base64,{screenshot_b64}",
                        },
                        {"type": "text", "text": INTEREST_EXTRACTION_PROMPT},
                    ],
                }
            ],
            model=REKA_MODEL,
        )

        text = response.responses[0].message.content
        parsed = _parse_json_response(text)

        if isinstance(parsed, dict) and "interests" in parsed:
            interests = parsed["interests"]
            if isinstance(interests, list):
                return [str(item) for item in interests if item]
        return []

    async def generate_vibe_fingerprint(
        self, screenshots: list[bytes]
    ) -> VibeFingerprint:
        """Analyze representative screenshots to generate a vibe fingerprint."""
        # Pick up to 5 representative screenshots (evenly spaced if more)
        representative = _select_representative(screenshots, max_count=5)

        if not representative:
            logger.warning("No screenshots available for vibe fingerprinting")
            return VibeFingerprint()

        # Build multi-image message content
        content: list[dict[str, Any]] = []
        for screenshot_bytes in representative:
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{b64}",
                }
            )
        content.append({"type": "text", "text": VIBE_FINGERPRINT_PROMPT})

        try:
            response = self._client.chat.create(
                messages=[{"role": "user", "content": content}],
                model=REKA_MODEL,
            )

            text = response.responses[0].message.content
            parsed = _parse_json_response(text)

            if isinstance(parsed, dict):
                return VibeFingerprint(
                    aesthetic_tags=_safe_str_list(parsed.get("aesthetic_tags", [])),
                    color_palette=_safe_str_list(parsed.get("color_palette", [])),
                    mood=str(parsed.get("mood", "")),
                    energy=_clamp_float(parsed.get("energy", 0.5)),
                    content_themes=_safe_str_list(parsed.get("content_themes", [])),
                )
            else:
                logger.warning("Vibe fingerprint response was not a dict: %s", type(parsed))
                return VibeFingerprint()

        except Exception:
            logger.exception("Failed to generate vibe fingerprint")
            return VibeFingerprint()

    @staticmethod
    def compute_similarity(
        vibe_a: VibeFingerprint, vibe_b: VibeFingerprint
    ) -> tuple[float, list[str], list[str]]:
        """Compute similarity between two vibe fingerprints.

        Returns:
            tuple of (score, shared_aesthetics, shared_themes)
            score is between 0.0 and 1.0.
        """
        # Normalize tags to lowercase for comparison
        a_tags = {t.lower().strip() for t in vibe_a.aesthetic_tags}
        b_tags = {t.lower().strip() for t in vibe_b.aesthetic_tags}
        a_themes = {t.lower().strip() for t in vibe_a.content_themes}
        b_themes = {t.lower().strip() for t in vibe_b.content_themes}

        # Tag overlap
        shared_tag_set = a_tags & b_tags
        tag_overlap = len(shared_tag_set) / max(len(a_tags), len(b_tags), 1)

        # Theme overlap
        shared_theme_set = a_themes & b_themes
        theme_overlap = len(shared_theme_set) / max(len(a_themes), len(b_themes), 1)

        # Energy closeness (1.0 = identical energy, 0.0 = opposite)
        energy_closeness = 1.0 - abs(vibe_a.energy - vibe_b.energy)

        # Mood match (binary: 1.0 if same, 0.0 if different)
        mood_match = (
            1.0
            if vibe_a.mood.lower().strip() == vibe_b.mood.lower().strip()
            and vibe_a.mood.strip() != ""
            else 0.0
        )

        # Weighted score
        score = (
            tag_overlap * 0.3
            + theme_overlap * 0.3
            + energy_closeness * 0.2
            + mood_match * 0.2
        )

        # Return the original-case versions of shared items
        shared_aesthetics = sorted(shared_tag_set)
        shared_themes = sorted(shared_theme_set)

        logger.info(
            "Vibe similarity: score=%.3f (tags=%.2f, themes=%.2f, energy=%.2f, mood=%.2f) "
            "shared_aesthetics=%s, shared_themes=%s",
            score,
            tag_overlap,
            theme_overlap,
            energy_closeness,
            mood_match,
            shared_aesthetics,
            shared_themes,
        )

        return score, shared_aesthetics, shared_themes


def _select_representative(
    screenshots: list[bytes], max_count: int = 5
) -> list[bytes]:
    """Select up to max_count evenly-spaced screenshots from the list."""
    if len(screenshots) <= max_count:
        return screenshots
    step = len(screenshots) / max_count
    indices = [int(i * step) for i in range(max_count)]
    return [screenshots[i] for i in indices]


def _parse_json_response(text: str) -> Any:
    """Parse JSON from an LLM response, handling markdown code blocks."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object or array in the text
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start_idx = text.find(start_char)
            end_idx = text.rfind(end_char)
            if start_idx != -1 and end_idx > start_idx:
                try:
                    return json.loads(text[start_idx : end_idx + 1])
                except json.JSONDecodeError:
                    continue
        logger.warning("Could not parse JSON from response: %s", text[:200])
        return {}


def _safe_str_list(val: Any) -> list[str]:
    """Convert a value to a list of strings safely."""
    if isinstance(val, list):
        return [str(item).strip() for item in val if item]
    return []


def _clamp_float(val: Any) -> float:
    """Clamp a value to a float between 0.0 and 1.0."""
    try:
        f = float(val)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return 0.5
