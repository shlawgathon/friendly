"""Modulate Velma-2 batch STT — transcription with emotion detection."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, wait_random, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)

MODULATE_URL = "https://modulate-developer-apis.com/api/velma-2-stt-batch"


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_backoff_multiplier, max=settings.retry_backoff_max)
    + wait_random(0, 2),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
)
async def transcribe_audio(audio_data: bytes, filename: str = "recording.webm") -> dict:
    """Send audio to Modulate Velma-2 for transcription with emotion signals."""
    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        resp = await client.post(
            MODULATE_URL,
            headers={"X-API-Key": settings.modulate_api_key},
            files={"upload_file": (filename, audio_data)},
            data={
                "speaker_diarization": "true",
                "emotion_signal": "true",
            },
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "Modulate STT: %d chars, %d utterances",
            len(result.get("text", "")),
            len(result.get("utterances", [])),
        )
        return result
