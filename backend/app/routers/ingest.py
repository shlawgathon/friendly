"""Ingest routes — Instagram and voice ingestion (202 Accepted + job_id)."""
from __future__ import annotations

import asyncio
import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form, Query

from app.models.dto import IngestInstagramRequest, IngestAccepted
from app.services import graph, pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/instagram", response_model=IngestAccepted, status_code=202)
async def ingest_instagram(
    req: IngestInstagramRequest,
    bg: BackgroundTasks,
    force: bool = Query(False, description="Bypass cooldown and re-ingest"),
):
    """Start async Instagram ingestion pipeline. Returns 202 + job_id."""
    # Cooldown check (skip if force=True)
    if not force and await graph.check_cooldown(req.username):
        raise HTTPException(
            status_code=429,
            detail=f"Ingest for '{req.username}' recently completed. "
                   f"Add ?force=true to re-sync, or wait a few minutes.",
        )

    job_id = str(uuid.uuid4())
    user_id = f"ig:{req.username}"

    await graph.create_ingest_job(job_id, req.username, user_id)
    bg.add_task(
        pipeline.run_instagram_ingest,
        job_id=job_id,
        username=req.username,
        user_id=user_id,
        max_posts=req.max_posts,
        include_reels=req.include_reels,
    )

    return IngestAccepted(job_id=job_id)


@router.post("/voice", response_model=IngestAccepted, status_code=202)
async def ingest_voice(
    bg: BackgroundTasks,
    audio: UploadFile = File(...),
    user_id: str = Form(...),
):
    """Start async voice ingestion pipeline."""
    job_id = str(uuid.uuid4())
    audio_data = await audio.read()

    await graph.create_ingest_job(job_id, f"voice:{user_id}", user_id)
    bg.add_task(
        pipeline.run_voice_ingest,
        job_id=job_id,
        user_id=user_id,
        audio_data=audio_data,
        filename=audio.filename or "recording.webm",
    )

    return IngestAccepted(job_id=job_id)
