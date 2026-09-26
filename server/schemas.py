"""Pydantic models for the public backend API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


SourceType = Literal["live", "replay"]
TripState = Literal["active", "ended"]


class CameraResponse(BaseModel):
    id: str
    name: str
    location: str
    source_type: SourceType
    recording: bool


class StartTripRequest(BaseModel):
    camera_id: str


class TripResponse(BaseModel):
    id: str
    camera_id: str
    started_at: datetime
    ended_at: datetime | None
    state: TripState


class StartTripResponse(BaseModel):
    trip: TripResponse
    trip_token: str


class BufferInfoResponse(BaseModel):
    camera_id: str
    playlist_url: str
    earliest: datetime | None
    latest: datetime | None
