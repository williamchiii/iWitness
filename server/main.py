from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db
from .config import SERVER_ROOT, settings
from .api import router
from .incident_lifecycle_routes import router as incident_lifecycle_router
from .incident_playback_routes import router as incident_playback_router
from .incident_worker import IncidentWorker
from .recorder import CameraRecorder, RecorderConfig
from .retention import RetentionWorker
from .segment_tracker import SegmentTracker
from .supervisor import RecorderSupervisor


logger = logging.getLogger(__name__)


def _resolve_replay_input(input_url: str) -> str:
    """Resolve a relative replay path without changing live URLs."""

    source = Path(input_url)
    if source.is_absolute():
        return str(source)

    candidates = (
        SERVER_ROOT.parent / source,
        SERVER_ROOT / source,
        Path.cwd() / source,
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())

    # Let FFmpeg report the missing input using the most likely project path.
    return str((SERVER_ROOT.parent / source).resolve())


def _permitted_cameras() -> list[dict[str, Any]]:
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT id, source_type, input_url
            FROM camera
            WHERE permitted = TRUE
            ORDER BY id
            """
        ).fetchall()
    return [
        {
            "id": row[0],
            "source_type": row[1],
            "input_url": row[2],
        }
        for row in rows
    ]


def _set_recording(camera_id: str, recording: bool) -> None:
    with db.connect() as connection:
        connection.execute(
            "UPDATE camera SET recording = %s WHERE id = %s",
            (recording, camera_id),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start permitted camera recorders with the API and stop them on exit."""

    recorders: dict[str, CameraRecorder] = {}
    trackers: dict[str, SegmentTracker] = {}
    retention_workers: dict[str, RetentionWorker] = {}
    supervisors: dict[str, RecorderSupervisor] = {}
    incident_worker = IncidentWorker()
    try:
        for camera in _permitted_cameras():
            camera_id = camera["id"]
            input_url = camera["input_url"]
            if camera["source_type"] == "replay":
                input_url = _resolve_replay_input(input_url)

            recorder = CameraRecorder(
                RecorderConfig(
                    camera_id=camera_id,
                    input_url=input_url,
                    source_type=camera["source_type"],
                    output_root=settings.cameras_root,
                    segment_seconds=settings.segment_seconds,
                    ffmpeg_binary=settings.ffmpeg_binary,
                )
            )
            tracker = SegmentTracker(
                camera_id=camera_id,
                directory=recorder.output_directory,
                server_root=SERVER_ROOT,
                recorder=recorder,
            )
            retention_worker = RetentionWorker(
                camera_id=camera_id,
                server_root=SERVER_ROOT,
                media_root=settings.media_root,
                buffer_seconds=settings.buffer_seconds,
                grace_seconds=settings.playback_url_seconds,
            )

            # A failure starting any one of these must not stop the other
            # permitted cameras from being tried.
            try:
                recorder.start()
                tracker.start()
                retention_worker.start()
                supervisor = RecorderSupervisor(
                    camera_id=camera_id,
                    recorder=recorder,
                    on_recording_change=_set_recording,
                )
                supervisor.start()
            except Exception:
                logger.exception("Failed to start camera %s; skipping", camera_id)
                retention_worker.stop()
                tracker.stop()
                if recorder.is_running:
                    recorder.stop()
                _set_recording(camera_id, False)
                continue

            recorders[camera_id] = recorder
            trackers[camera_id] = tracker
            retention_workers[camera_id] = retention_worker
            supervisors[camera_id] = supervisor
            _set_recording(camera_id, True)
            logger.info("Started recorder for camera %s", camera_id)

        incident_worker.start()
        yield
    finally:
        incident_worker.stop()
        for supervisor in supervisors.values():
            supervisor.stop()
        for retention_worker in retention_workers.values():
            retention_worker.stop()
        for tracker in trackers.values():
            tracker.stop()
        for camera_id, recorder in recorders.items():
            recorder.stop()
            _set_recording(camera_id, False)
            logger.info("Stopped recorder for camera %s", camera_id)


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.include_router(incident_lifecycle_router)
app.include_router(incident_playback_router)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, _exc: RequestValidationError
) -> JSONResponse:
    """Return the contract's string detail without echoing request data."""

    return JSONResponse(status_code=400, content={"detail": "Malformed request"})


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Hide internal failures from clients and keep exception data out of logs."""

    logger.error("Unhandled request error (%s)", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health(connection: psycopg.Connection = Depends(db.get_db)) -> dict[str, str]:
    """Report server and database health for uptime checks."""

    connection.execute("select 1")
    return {"server": "healthy", "database": "healthy"}
