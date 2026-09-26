"""Track completed FFmpeg segments in PostgreSQL."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from pathlib import Path
import threading

from . import db
from .recorder import CameraRecorder


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ListedSegment:
    filename: str
    start_seconds: float
    end_seconds: float


class SegmentTracker:
    """Insert a row for each segment FFmpeg reports as complete."""

    def __init__(
        self,
        camera_id: str,
        directory: Path,
        server_root: Path,
        recorder: CameraRecorder,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")

        self.camera_id = camera_id
        self.directory = directory
        self.server_root = server_root
        self.recorder = recorder
        self.poll_seconds = poll_seconds
        self._known_paths: set[str] = set()
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
        """Insert any newly completed segments and return how many."""

        started_at = self.recorder.started_at
        if started_at is None:
            return 0

        inserted = 0
        for listed in self._read_segment_list():
            path = self.directory / listed.filename
            relative_path = self._relative_path(path)
            if relative_path in self._known_paths:
                continue

            try:
                if not path.is_file() or path.stat().st_size == 0:
                    continue
            except FileNotFoundError:
                continue

            actual_start = started_at + timedelta(seconds=listed.start_seconds)
            actual_end = started_at + timedelta(seconds=listed.end_seconds)

            if self._insert_segment(relative_path, actual_start, actual_end):
                inserted += 1
            self._known_paths.add(relative_path)

        return inserted

    def _read_segment_list(self) -> list[_ListedSegment]:
        """Parse FFmpeg's segment list: one ``filename,start,end`` row each.

        Times are the muxer's own account of what it wrote (elapsed seconds
        since the recorder started), not an assumed fixed duration — this
        is what lets actual_start/actual_end reflect real recorded time
        even when a segment runs long or short (e.g. for keyframe
        alignment). The file is rewritten from scratch by each new FFmpeg
        run, so a row here is always for the *current* recorder run.
        """

        try:
            with self.recorder.segment_list_path.open("r", newline="") as list_file:
                rows = list(csv.reader(list_file))
        except FileNotFoundError:
            return []

        segments: list[_ListedSegment] = []
        for row in rows:
            if len(row) != 3:
                # A row FFmpeg is still mid-write on; it will be complete
                # (and read again) on the next poll.
                continue
            filename, start_str, end_str = row
            try:
                segments.append(_ListedSegment(filename, float(start_str), float(end_str)))
            except ValueError:
                continue
        return segments

    def _insert_segment(
        self, relative_path: str, actual_start: datetime, actual_end: datetime
    ) -> bool:
        # source_start / source_end are intentionally left null: neither a
        # replayed local file nor a generic live camera feed gives FFmpeg an
        # independent, trustworthy clock of its own to record here. If a
        # specific source ever exposes one, populate it separately —
        # never by copying actual_start/actual_end.
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
