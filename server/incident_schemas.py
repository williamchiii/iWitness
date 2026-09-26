"""Pydantic models for incident capture responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .schemas import SourceType


ProcessingState = Literal[
    "recording",
    "assembling",
    "uploading",
    "ready",
    "failed",
]
ClaimState = Literal["unclaimed", "claimed", "expired"]


class IncidentResponse(BaseModel):
    """Incident metadata returned to the browser."""

    id: str
    trip_id: str
    camera_id: str
    camera_name: str
    source_type: SourceType
    trigger_at: datetime
    requested_start: datetime
    requested_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    source_start: datetime | None
    source_end: datetime | None
    duration_seconds: float | None
    size_bytes: int | None
    sha256: str | None
    processing_state: ProcessingState
    claim_state: ClaimState
    expires_at: datetime | None
    video_version: int
    error: str | None
    # Signed link to a still from the clip; set only for the owner, once ready.
    thumbnail_url: str | None = None
