"""Job status route."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.models.dto import JobResponse
from app.services import graph

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _parse_json_field(val) -> dict | None:
    """Safely parse a JSON-encoded field from Neo4j."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(val)}


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    """Poll a job's current status and progress."""
    job = await graph.get_ingest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        job_id=job_id,
        status=job.get("status", "queued"),
        progress=_parse_json_field(job.get("progress")),
        result=_parse_json_field(job.get("result")),
        error=job.get("error"),
        created_at=str(job.get("created_at", "")),
    )
