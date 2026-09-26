"""Poll recording incidents and assemble them when their window is complete."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
from typing import Any

from . import db
from .config import SERVER_ROOT, settings
from .incident_processor import IncidentProcessor


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RecordingIncident:
    id: str
    camera_id: str
    requested_start: datetime
    requested_end: datetime


class IncidentWorker:
    """Preserve and assemble recording incidents in the background.

    Incident work is deliberately handled one incident at a time. A failure
    for one row is logged and the next row is still processed during the same
    poll. ``IncidentProcessor`` performs its own conditional assembly claim,
    so repeated polls cannot run FFmpeg concurrently for the same incident.
    """

    def __init__(
        self,
        *,
        database: Any = db,
        processor: Any | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")

        self.database = database
        self.processor = (
            processor if processor is not None else IncidentProcessor(database=database)
        )
        self.poll_seconds = poll_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError("incident worker is already running")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="incident-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def run_once(self) -> int:
        """Process one poll and return the number of incidents submitted."""

        try:
            self._expire_abandoned()
        except Exception:
            logger.exception("Incident expiry poll failed")
        incidents = self._recording_incidents()
        submitted = 0
        for incident in incidents:
            try:
                ready = self._preserve_segments(incident)
                if not ready:
                    continue

                submitted += 1
                self.processor.process(incident.id)
            except Exception:
                logger.exception("Incident worker failed for incident %s", incident.id)
        return submitted

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                # This includes a database outage while loading the incident
                # list. The worker stays alive and retries on the next poll.
                logger.exception("Incident worker poll failed")
            self._stop_event.wait(self.poll_seconds)

    def _recording_incidents(self) -> list[_RecordingIncident]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, camera_id, requested_start, requested_end
                FROM incident
                WHERE processing_state = 'recording'
                  AND claim_state <> 'expired'
                ORDER BY requested_end ASC, id ASC
                """
            ).fetchall()

        return [
            _RecordingIncident(
                id=str(row[0]),
                camera_id=str(row[1]),
                requested_start=_as_utc(row[2]),
                requested_end=_as_utc(row[3]),
            )
            for row in rows
        ]

    def _preserve_segments(self, incident: _RecordingIncident) -> bool:
        """Preserve overlapping temporary rows and report post-window readiness."""

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE segment
                SET status = 'preserved', incident_id = %s
                WHERE camera_id = %s
                  AND status = 'temporary'
                  AND actual_start < %s
                  AND actual_end > %s
                """,
                (
                    incident.id,
                    incident.camera_id,
                    incident.requested_end,
                    incident.requested_start,
                ),
            )
            connection.execute(
                """
                INSERT INTO incident_segment (incident_id, segment_id)
                SELECT %s, s.id
                FROM segment AS s
                WHERE s.camera_id = %s
                  AND s.status = 'preserved'
                  AND s.actual_start < %s
                  AND s.actual_end > %s
                ON CONFLICT DO NOTHING
                """,
                (
                    incident.id,
                    incident.camera_id,
                    incident.requested_end,
                    incident.requested_start,
                ),
            )
            row = connection.execute(
                """
                SELECT max(s.actual_end)
                FROM segment AS s
                JOIN incident_segment AS link ON link.segment_id = s.id
                WHERE link.incident_id = %s
                  AND s.camera_id = %s
                  AND s.status = 'preserved'
                """,
                (incident.id, incident.camera_id),
            ).fetchone()

        latest_end = row[0] if row else None
        return latest_end is not None and _as_utc(latest_end) >= incident.requested_end

    def _expire_abandoned(self) -> None:
        """Expire unclaimed incidents and remove video no other incident needs."""

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM incident
                WHERE claim_state = 'unclaimed' AND expires_at <= now()
                """
            ).fetchall()
        for (incident_id,) in rows:
            try:
                self._expire_one(incident_id)
            except Exception:
                logger.exception("Incident expiry failed for incident %s", incident_id)

    def _expire_one(self, incident_id: str) -> None:
        files_to_remove: list[Path] = []
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT storage_path FROM incident
                WHERE id = %s AND claim_state = 'unclaimed' AND expires_at <= now()
                FOR UPDATE SKIP LOCKED
                """,
                (incident_id,),
            ).fetchone()
            if row is None:
                return
            storage_path = row[0]
            files_to_remove.extend(self._expired_clip_paths(str(incident_id), storage_path))
            # Lock the segment rows before removing their database records. A
            # new incident cannot acquire a link to one while it is deleted.
            exclusive = connection.execute(
                """
                SELECT s.id, s.file_path, s.camera_id
                FROM segment AS s
                JOIN incident_segment AS link ON link.segment_id = s.id
                WHERE link.incident_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM incident_segment AS other
                      WHERE other.segment_id = s.id
                        AND other.incident_id <> %s
                  )
                FOR UPDATE OF s
                """,
                (incident_id, incident_id),
            ).fetchall()
            for segment_id, file_path, camera_id in exclusive:
                # The candidate list may have been read before this row lock
                # became available. Recheck links while the lock is held.
                shared = connection.execute(
                    """
                    SELECT 1 FROM incident_segment
                    WHERE segment_id = %s AND incident_id <> %s
                    LIMIT 1
                    """,
                    (segment_id, incident_id),
                ).fetchone()
                if shared is not None:
                    continue
                segment_path = self._segment_path(str(file_path), str(camera_id))
                deleted = connection.execute(
                    """
                    DELETE FROM segment
                    WHERE id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM incident_segment
                          WHERE segment_id = %s AND incident_id <> %s
                      )
                    RETURNING id
                    """,
                    (segment_id, segment_id, incident_id),
                ).fetchone()
                if deleted is not None:
                    files_to_remove.append(segment_path)
            connection.execute(
                """
                UPDATE incident
                SET claim_state = 'expired', storage_path = NULL
                WHERE id = %s AND claim_state = 'unclaimed'
                """,
                (incident_id,),
            )
            removed = connection.execute(
                """
                DELETE FROM incident_segment
                WHERE incident_id = %s
                RETURNING segment_id
                """,
                (incident_id,),
            ).fetchall()
            if removed:
                connection.execute(
                    """
                    UPDATE segment AS s
                    SET incident_id = (
                            SELECT link.incident_id
                            FROM incident_segment AS link
                            WHERE link.segment_id = s.id
                            ORDER BY link.incident_id LIMIT 1
                        ),
                        status = CASE WHEN EXISTS (
                            SELECT 1 FROM incident_segment AS link
                            WHERE link.segment_id = s.id
                        ) THEN 'preserved' ELSE 'temporary' END
                    WHERE s.id = ANY(%s)
                    """,
                    ([row[0] for row in removed],),
                )
        for path in files_to_remove:
            path.unlink(missing_ok=True)

    @staticmethod
    def _segment_path(file_path: str, camera_id: str) -> Path:
        if not camera_id or Path(camera_id).name != camera_id:
            raise ValueError(f"Unsafe camera ID: {camera_id}")
        root = (settings.cameras_root / camera_id).resolve()
        candidate = (SERVER_ROOT / file_path).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Unsafe expired segment path: {file_path}")
        return candidate

    @staticmethod
    def _expired_clip_paths(incident_id: str, storage_path: str | None) -> list[Path]:
        if not incident_id or Path(incident_id).name != incident_id:
            raise ValueError(f"Unsafe incident ID: {incident_id}")
        root = (settings.incidents_root / incident_id).resolve()
        candidate = (
            SERVER_ROOT / Path(storage_path)
            if storage_path
            else root / "clip.mp4"
        ).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Unsafe expired clip path: {storage_path}")
        return [candidate, root / "clip.tmp.mp4", root / "segments.concat.txt"]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
