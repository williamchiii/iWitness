"""Backend configuration loaded from ``server/.env``."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


SERVER_ROOT = Path(__file__).resolve().parent
load_dotenv(SERVER_ROOT / ".env")


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return parsed


def _required_str(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def _path_from_env(name: str, default: str) -> Path:
    configured = Path(os.getenv(name, default))
    if configured.is_absolute():
        return configured
    return SERVER_ROOT / configured


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by the backend modules."""

    database_url: str | None
    media_root: Path
    ffmpeg_binary: str
    playback_signing_secret: str
    playback_url_seconds: int
    segment_seconds: int
    buffer_seconds: int
    pre_trigger_seconds: int
    post_trigger_seconds: int
    unclaimed_incident_seconds: int

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables (and server/.env)."""

        return cls(
            database_url=os.getenv("DATABASE_URL"),
            media_root=_path_from_env("MEDIA_ROOT", "media"),
            ffmpeg_binary=os.getenv("FFMPEG_BINARY", "ffmpeg"),
            # Every process restart must reuse the same secret, or every
            # playback URL already handed out becomes invalid with no
            # warning. There is no safe default, so this is required.
            playback_signing_secret=_required_str("PLAYBACK_SIGNING_SECRET"),
            playback_url_seconds=_positive_int("PLAYBACK_URL_SECONDS", 300),
            segment_seconds=_positive_int("SEGMENT_SECONDS", 10),
            buffer_seconds=_positive_int("BUFFER_SECONDS", 300),
            pre_trigger_seconds=_positive_int("PRE_TRIGGER_SECONDS", 60),
            post_trigger_seconds=_positive_int("POST_TRIGGER_SECONDS", 15),
            unclaimed_incident_seconds=_positive_int(
                "UNCLAIMED_INCIDENT_SECONDS", 900
            ),
        )

    @property
    def cameras_root(self) -> Path:
        return self.media_root / "cameras"

    @property
    def incidents_root(self) -> Path:
        return self.media_root / "incidents"


settings = Settings.from_environment()


def get_settings() -> Settings:
    """FastAPI dependency for the process-wide settings singleton."""

    return settings
