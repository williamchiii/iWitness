"""Track completed FFmpeg segments in PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import threading

try:
    from . import db
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    import db


logger = logging.getLogger(__name__)


@dataclass
class _Observation:
    size: int
    modified_ns: int
    stable_polls: int = 0


class SegmentTracker:
    """Insert a row after an output segment is complete and stable."""

    def __init__(
        self,
        camera_id: str,
        directory: Path,
        server_root: Path,
        segment_seconds: int,
        poll_seconds: float = 1.0,
        required_stable_polls: int = 2,
    ) -> None:
        if segment_seconds <= 0:
            raise ValueError("segment_seconds must be greater than zero")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")
        if required_stable_polls < 1:
            raise ValueError("required_stable_polls must be at least one")

        self.camera_id = camera_id
        self.directory = directory
        self.server_root = server_root
        self.segment_seconds = segment_seconds
        self.poll_seconds = poll_seconds
        self.required_stable_polls = required_stable_polls
        self._known_paths: set[str] = set()
        self._observations: dict[str, _Observation] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError(f"segment tracker for {self.camera_id!r} is already running")

        self.directory.mkdir(parents=True, exist_ok=True)
        self._known_paths = self._existing_segment_paths()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"segment-tracker-{self.camera_id}",
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
                self.scan_once()
            except Exception:
                logger.exception("Segment scan failed for camera %s", self.camera_id)
            self._stop_event.wait(self.poll_seconds)

    def scan_once(self) -> int:
        """Scan once and return the number of newly inserted segments."""

        inserted = 0
        for path in sorted(self.directory.glob("*.ts")):
            relative_path = self._relative_path(path)
            if relative_path in self._known_paths:
                continue

            try:
                stat = path.stat()
            except FileNotFoundError:
                continue

            if stat.st_size == 0:
                self._observations.pop(relative_path, None)
                continue

            observation = self._observations.get(relative_path)
            if observation is None or (
                observation.size != stat.st_size
                or observation.modified_ns != stat.st_mtime_ns
            ):
                self._observations[relative_path] = _Observation(
                    size=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                )
                continue

            observation.stable_polls += 1
            if observation.stable_polls < self.required_stable_polls:
                continue

            if self._insert_segment(relative_path, stat.st_mtime):
                inserted += 1
            self._known_paths.add(relative_path)
            self._observations.pop(relative_path, None)

        return inserted

    def _insert_segment(self, relative_path: str, modified_timestamp: float) -> bool:
        actual_end = datetime.fromtimestamp(modified_timestamp, tz=timezone.utc)
        actual_start = actual_end - timedelta(seconds=self.segment_seconds)

        with db.connect() as connection:
            result = connection.execute(
                """
                INSERT INTO segment (
                    camera_id,
                    file_path,
                    actual_start,
                    actual_end,
                    status
                )
                VALUES (%s, %s, %s, %s, 'temporary')
                ON CONFLICT (file_path) DO NOTHING
                RETURNING id
                """,
                (self.camera_id, relative_path, actual_start, actual_end),
            )
            inserted = result.fetchone() is not None

        if inserted:
            logger.info("Tracked segment %s", relative_path)
        else:
            logger.debug("Segment already tracked: %s", relative_path)
        return inserted

    def _existing_segment_paths(self) -> set[str]:
        with db.connect() as connection:
            rows = connection.execute(
                "SELECT file_path FROM segment WHERE camera_id = %s",
                (self.camera_id,),
            ).fetchall()
        return {row[0] for row in rows}

    def _relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.server_root.resolve()).as_posix()
