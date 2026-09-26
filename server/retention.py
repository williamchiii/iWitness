"""Delete temporary segments outside a camera's configured buffer window."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
import threading

from . import db


logger = logging.getLogger(__name__)


class RetentionWorker:
    """Maintain the temporary segment window for one camera."""

    def __init__(
        self,
        camera_id: str,
        server_root: Path,
        media_root: Path,
        buffer_seconds: int,
        poll_seconds: float = 5.0,
        grace_seconds: int = 0,
    ) -> None:
        if buffer_seconds <= 0:
            raise ValueError("buffer_seconds must be greater than zero")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")
        if grace_seconds < 0:
            raise ValueError("grace_seconds must not be negative")

        self.camera_id = camera_id
        self.server_root = server_root.resolve()
        self.media_root = media_root.resolve()
        self.buffer_seconds = buffer_seconds
        self.poll_seconds = poll_seconds
        # A playlist can still be handing out signed URLs for a segment
        # after it falls outside buffer_seconds; keep it on disk a bit
        # longer than that so those URLs don't start 404ing mid-scrub.
        self.grace_seconds = grace_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError(f"retention worker for {self.camera_id!r} is already running")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"retention-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.cleanup_once()
            except Exception:
                logger.exception("Retention cleanup failed for camera %s", self.camera_id)
            self._stop_event.wait(self.poll_seconds)

    def cleanup_once(self) -> int:
        """Delete expired temporary segments and return the deleted count."""

        # One connection for the whole cycle instead of one per query (and,
        # previously, one more per deleted segment) — this runs every
        # poll_seconds for every camera, so that adds up over a multi-hour
        # recording.
        with db.connect() as connection:
            latest_row = connection.execute(
                """
                SELECT max(actual_end)
                FROM segment
                WHERE camera_id = %s
                """,
                (self.camera_id,),
            ).fetchone()

            latest_end = latest_row[0] if latest_row else None
            if latest_end is None:
                return 0

            cutoff = latest_end - timedelta(seconds=self.buffer_seconds + self.grace_seconds)
            rows = connection.execute(
                """
                SELECT id, file_path
                FROM segment
                WHERE camera_id = %s
                  AND status = 'temporary'
                  AND actual_end <= %s
                ORDER BY actual_end ASC
                """,
                (self.camera_id, cutoff),
            ).fetchall()

            deletable_ids = []
            for segment_id, file_path in rows:
                path = self._safe_media_path(file_path)
                if path is None:
                    logger.error("Skipping unsafe segment path %s", file_path)
                    continue

                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not delete segment file %s", path)
                    continue

                deletable_ids.append(segment_id)

            if not deletable_ids:
                return 0

            # A single batched delete instead of one round trip per file.
            removed_paths = connection.execute(
                """
                DELETE FROM segment
                WHERE camera_id = %s
                  AND status = 'temporary'
                  AND id = ANY(%s)
                RETURNING file_path
                """,
                (self.camera_id, deletable_ids),
            ).fetchall()

        for (file_path,) in removed_paths:
            logger.info("Removed expired segment %s", file_path)

        return len(removed_paths)

    def _safe_media_path(self, file_path: str) -> Path | None:
        candidate = (self.server_root / file_path).resolve()
        try:
            candidate.relative_to(self.media_root)
        except ValueError:
            return None
        return candidate
