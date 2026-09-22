"""Pydantic models for the local HTTP API request/response bodies."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    mode: str = Field("smart", description="normal|smart|build|computer|browser|silent")
    session_id: str | None = None


class PlanRequest(BaseModel):
    command: str
    mode: str = "smart"


class TranscribeRequest(BaseModel):
    audio_base64: str | None = None
    audio_path: str | None = None
    language: str | None = None


class TranscribeResponse(BaseModel):
    text: str
    confidence: float | None = None
    provider: str


class TaskCreateRequest(BaseModel):
    command: str
    mode: str = "smart"


class CancelRequest(BaseModel):
    reason: str = "user_cancel"


class ConfirmRequest(BaseModel):
    approve: bool
    reason: str | None = None


class SettingsUpdateRequest(BaseModel):
    updates: dict[str, Any]


class MemoryCreateRequest(BaseModel):
    key: str
    value: str
    category: str = "general"


class WorkflowCreateRequest(BaseModel):
    name: str
    triggers: list[str] | None = None
    steps: list[dict]


class PlanStep(BaseModel):
    seq: int
    tool: str
    arguments: dict = Field(default_factory=dict)
    rationale: str = ""


class PlanResponse(BaseModel):
    goal: str
    steps: list[PlanStep]
    raw: dict | None = None


class StatusResponse(BaseModel):
    state: str
    active_task: str | None = None
    queued: int = 0
    uptime_seconds: float = 0
    version: str = "1.0.0"
    platform: str
    python: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict | None = None
