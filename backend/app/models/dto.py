from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field


# ── Ingest DTOs ──


class IngestInstagramRequest(BaseModel):
    username: str
    max_posts: int = Field(
        default=10,
        validation_alias=AliasChoices("max_posts", "maxPosts"),
        le=25,
        ge=1,
    )
    include_reels: bool = Field(
        default=True,
        validation_alias=AliasChoices("include_reels", "includeReels"),
    )


class IngestVoiceRequest(BaseModel):
    user_id: str


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None


class IngestAccepted(BaseModel):
    job_id: str
    status: str = "queued"


# ── Task Record (Yutori async) ──


class TaskType(str, Enum):
    research = "research"
    scouting = "scouting"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskRecord(BaseModel):
    provider_task_id: str
    task_type: TaskType
    interest: str
    user_id: str
    status: TaskStatus = TaskStatus.pending
    attempts: int = 0
    last_error: str | None = None
    result_json: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# ── Graph DTOs ──


class UserNode(BaseModel):
    id: str
    username: str
    full_name: str | None = None
    bio: str | None = None
    profile_pic_url: str | None = None


class InterestEdge(BaseModel):
    hobby: str
    weight: float
    source: str
    evidence: str | None = None


class MatchResult(BaseModel):
    user: UserNode
    affinity: float
    shared_interests: list[str]
    icebreaker: str | None = None


class GraphData(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


# ── Icebreaker ──


class IcebreakerRequest(BaseModel):
    user_id: str
    target_user_id: str


class IcebreakerResponse(BaseModel):
    icebreaker: str
    shared_context: list[str]
