from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI

try:
    from . import db
    from .config import SERVER_ROOT, settings
    from .api import router
    from .recorder import CameraRecorder, RecorderConfig
    from .retention import RetentionWorker
    from .segment_tracker import SegmentTracker
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    import db
    from config import SERVER_ROOT, settings
    from recorder import CameraRecorder, RecorderConfig
    from api import router
    from retention import RetentionWorker
    from segment_tracker import SegmentTracker


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

            try:
                recorder.start()
            except Exception:
                logger.exception("Failed to start recorder for camera %s", camera_id)
                _set_recording(camera_id, False)
                continue

            recorders[camera_id] = recorder
            _set_recording(camera_id, True)
            tracker = SegmentTracker(
                camera_id=camera_id,
                directory=recorder.output_directory,
                server_root=SERVER_ROOT,
                segment_seconds=settings.segment_seconds,
            )
            tracker.start()
            trackers[camera_id] = tracker
            retention_worker = RetentionWorker(
                camera_id=camera_id,
                server_root=SERVER_ROOT,
                media_root=settings.media_root,
                buffer_seconds=settings.buffer_seconds,
            )
            retention_worker.start()
            retention_workers[camera_id] = retention_worker
            logger.info("Started recorder for camera %s", camera_id)

        yield
    finally:
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

@app.post("/health")
def health():
    with db.connect() as conn:
        conn.execute("select 1")
    return {"server": "healthy", "database": "healthy"}
