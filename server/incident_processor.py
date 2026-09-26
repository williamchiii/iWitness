"""Assemble preserved incident segments into a playable MP4 clip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable, Literal

try:
    from . import db
    from .config import SERVER_ROOT, settings
except ImportError:
    # Supports ``python -m incident_processor`` and ``uvicorn main:app`` from
    # the server directory.
    import db
    from config import SERVER_ROOT, settings


logger = logging.getLogger(__name__)

ProcessingState = Literal[
    "recording", "assembling", "uploading", "ready", "failed"
]
CommandRunner = Callable[..., Any]


class IncidentProcessingError(RuntimeError):
    """An expected incident assembly failure that can be stored in the DB."""


@dataclass(frozen=True)
class IncidentProcessingResult:
    """The assembly metadata returned by :meth:`IncidentProcessor.process`."""

    incident_id: str
    processing_state: ProcessingState
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    storage_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _Incident:
    camera_id: str
    requested_end: datetime
    processing_state: str
    actual_start: datetime | None
    actual_end: datetime | None
    duration_seconds: float | None
    size_bytes: int | None
    sha256: str | None
    storage_path: str | None
    error: str | None


@dataclass(frozen=True)
class _Segment:
    file_path: str
    actual_start: datetime
    actual_end: datetime


class IncidentProcessor:
    """Turn preserved segments for one incident into ``clip.mp4``.

    The processor is intentionally independent of FastAPI. The incident
    endpoint or a background worker can call :meth:`process` after the
    post-trigger window has been recorded. The database object and command
    runner are injectable so the failure paths can be tested without a live
    PostgreSQL database or FFmpeg process.
    """

    def __init__(
        self,
        *,
        database: Any = db,
        runtime_settings: Any = settings,
        command_runner: CommandRunner = subprocess.run,
        server_root: Path = SERVER_ROOT,
    ) -> None:
        self.database = database
        self.settings = runtime_settings
        self.command_runner = command_runner
        self.server_root = Path(server_root).resolve()

    def process(self, incident_id: str) -> IncidentProcessingResult:
        """Assemble an incident when its post-trigger window is available.

        If the latest preserved segment ends before ``requested_end``, the
        incident remains in ``recording`` and the current status is returned.
        A second worker that finds the incident already assembling also gets
        the current status instead of running FFmpeg concurrently.
        """

        incident_key = str(incident_id)
        incident, claimed = self._claim_for_assembly(incident_key)
        if not claimed:
            return self._result_from_incident(incident_key, incident)

        manifest_path: Path | None = None
        temporary_output: Path | None = None
        output_path: Path | None = None
        published = False

        try:
            segments = self._preserved_segments(incident_key, incident.camera_id)
            if not segments:
                raise IncidentProcessingError(
                    "No preserved segments are available for this incident"
                )

            for segment in segments:
                self._validate_segment_path(segment.file_path, incident.camera_id)

            actual_start = min(segment.actual_start for segment in segments)
            actual_end = max(segment.actual_end for segment in segments)
            if actual_end < actual_start:
                raise IncidentProcessingError("Preserved segment times are invalid")

            output_directory = self._incident_output_directory(incident_key)
            output_directory.mkdir(parents=True, exist_ok=True)
            output_path = output_directory / "clip.mp4"
            temporary_output = output_directory / "clip.tmp.mp4"
            manifest_path = output_directory / "segments.concat.txt"

            _remove_file(output_path)
            _remove_file(temporary_output)
            self._write_concat_manifest(
                manifest_path,
                [
                    self._validate_segment_path(segment.file_path, incident.camera_id)
                    for segment in segments
                ],
            )

            completed = self._run_ffmpeg(manifest_path, temporary_output)
            if completed.returncode != 0:
                stderr = str(getattr(completed, "stderr", "") or "").strip()
                detail = stderr[-1000:] if stderr else "FFmpeg returned a non-zero exit code"
                raise IncidentProcessingError(f"FFmpeg failed: {detail}")

            if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                raise IncidentProcessingError("FFmpeg did not produce a non-empty clip")

            temporary_output.replace(output_path)
            size_bytes, sha256 = _file_metadata(output_path)
            duration_seconds = max(0.0, (actual_end - actual_start).total_seconds())
            storage_path = self._storage_path(output_path)

            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE incident
                    SET actual_start = %s,
                        actual_end = %s,
                        duration_seconds = %s,
                        size_bytes = %s,
                        sha256 = %s,
                        storage_path = %s,
                        processing_state = 'ready',
                        error = NULL
                    WHERE id = %s
                    """,
                    (
                        actual_start,
                        actual_end,
                        duration_seconds,
                        size_bytes,
                        sha256,
                        storage_path,
                        incident_key,
                    ),
                )

            published = True
            logger.info("Assembled incident %s into %s", incident_key, output_path)
            return IncidentProcessingResult(
                incident_id=incident_key,
                processing_state="ready",
                actual_start=actual_start,
                actual_end=actual_end,
                duration_seconds=duration_seconds,
                size_bytes=size_bytes,
                sha256=sha256,
                storage_path=storage_path,
            )
        except IncidentProcessingError as exc:
            error = _bounded_error(str(exc))
            self._mark_failed(incident_key, error)
            return IncidentProcessingResult(
                incident_id=incident_key,
                processing_state="failed",
                error=error,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            error = _bounded_error(f"Incident assembly failed: {exc}")
            self._mark_failed(incident_key, error)
            return IncidentProcessingResult(
                incident_id=incident_key,
                processing_state="failed",
                error=error,
            )
        finally:
            if manifest_path is not None:
                _remove_file(manifest_path)
            if temporary_output is not None:
                _remove_file(temporary_output)
            if not published and output_path is not None:
                _remove_file(output_path)

    def _claim_for_assembly(self, incident_id: str) -> tuple[_Incident, bool]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT camera_id,
                       requested_end,
                       processing_state,
                       actual_start,
                       actual_end,
                       duration_seconds,
                       size_bytes,
                       sha256,
                       storage_path,
                       error
                FROM incident
                WHERE id = %s
                FOR UPDATE
                """,
                (incident_id,),
            ).fetchone()
            if row is None:
                raise IncidentProcessingError("Incident not found")

            incident = _incident_from_row(row)
            if incident.processing_state != "recording":
                return incident, False

            latest = connection.execute(
                """
                SELECT max(actual_end)
                FROM segment AS s
                JOIN incident_segment AS link ON link.segment_id = s.id
                WHERE link.incident_id = %s
                  AND s.camera_id = %s
                  AND s.status = 'preserved'
                """,
                (incident_id, incident.camera_id),
            ).fetchone()
            latest_end = latest[0] if latest else None
            if latest_end is None or _as_utc(latest_end) < incident.requested_end:
                return incident, False

            claimed = connection.execute(
                """
                UPDATE incident
                SET processing_state = 'assembling', error = NULL
                WHERE id = %s AND processing_state = 'recording'
                RETURNING camera_id,
                          requested_end,
                          processing_state,
                          actual_start,
                          actual_end,
                          duration_seconds,
                          size_bytes,
                          sha256,
                          storage_path,
                          error
                """,
                (incident_id,),
            ).fetchone()
            if claimed is not None:
                return _incident_from_row(claimed), True

        # The row changed between the read and the conditional update. Return
        # the current status so another worker can finish the job.
        return self._load_incident(incident_id), False

    def _load_incident(self, incident_id: str) -> _Incident:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT camera_id,
                       requested_end,
                       processing_state,
                       actual_start,
                       actual_end,
                       duration_seconds,
                       size_bytes,
                       sha256,
                       storage_path,
                       error
                FROM incident
                WHERE id = %s
                """,
                (incident_id,),
            ).fetchone()
        if row is None:
            raise IncidentProcessingError("Incident not found")
        return _incident_from_row(row)

    def _preserved_segments(self, incident_id: str, camera_id: str) -> list[_Segment]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT file_path, actual_start, actual_end
                FROM segment AS s
                JOIN incident_segment AS link ON link.segment_id = s.id
                WHERE link.incident_id = %s
                  AND s.camera_id = %s
                  AND s.status = 'preserved'
                ORDER BY s.actual_start ASC, s.actual_end ASC, s.id ASC
                """,
                (incident_id, camera_id),
            ).fetchall()
        return [
            _Segment(
                file_path=str(row[0]),
                actual_start=_as_utc(row[1]),
                actual_end=_as_utc(row[2]),
            )
            for row in rows
        ]

    def _validate_segment_path(self, file_path: str, camera_id: str) -> Path:
        """Resolve a segment only if it stays inside its camera directory."""

        if not camera_id or Path(camera_id).name != camera_id:
            raise IncidentProcessingError("Camera ID is not a safe path component")
        camera_directory = (self.settings.cameras_root / camera_id).resolve()
        candidate = (self.server_root / file_path).resolve()
        try:
            candidate.relative_to(camera_directory)
        except ValueError as exc:
            raise IncidentProcessingError(
                f"Segment path is outside the camera media directory: {file_path}"
            ) from exc

        try:
            if not candidate.is_file() or candidate.stat().st_size == 0:
                raise IncidentProcessingError(f"Segment file is missing or empty: {file_path}")
        except FileNotFoundError as exc:
            raise IncidentProcessingError(f"Segment file is missing: {file_path}") from exc
        return candidate

    def _incident_output_directory(self, incident_id: str) -> Path:
        """Return a validated directory under the configured incidents root."""

        if not incident_id or Path(incident_id).name != incident_id:
            raise IncidentProcessingError("Incident ID is not a safe path component")
        directory = (self.settings.incidents_root / incident_id).resolve()
        try:
            directory.relative_to(self.settings.incidents_root.resolve())
        except ValueError as exc:
            raise IncidentProcessingError("Incident output path is unsafe") from exc
        return directory

    def _write_concat_manifest(self, manifest_path: Path, paths: list[Path]) -> None:
        lines = [f"file '{_concat_path(path)}'" for path in paths]
        manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run_ffmpeg(self, manifest_path: Path, output_path: Path) -> Any:
        command = [
            self.settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        try:
            return self.command_runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise IncidentProcessingError(
                f"FFmpeg executable not found: {self.settings.ffmpeg_binary}"
            ) from exc

    def _mark_failed(self, incident_id: str, error: str) -> None:
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE incident
                    SET processing_state = 'failed',
                        error = %s
                    WHERE id = %s
                    """,
                    (error, incident_id),
                )
        except Exception:
            logger.exception("Could not mark incident %s as failed", incident_id)

    def _storage_path(self, output_path: Path) -> str:
        try:
            return output_path.resolve().relative_to(self.server_root).as_posix()
        except ValueError:
            return output_path.resolve().as_posix()

    @staticmethod
    def _result_from_incident(incident_id: str, incident: _Incident) -> IncidentProcessingResult:
        state = incident.processing_state
        if state not in {"recording", "assembling", "uploading", "ready", "failed"}:
            state = "recording"
        return IncidentProcessingResult(
            incident_id=incident_id,
            processing_state=state,  # type: ignore[arg-type]
            actual_start=incident.actual_start,
            actual_end=incident.actual_end,
            duration_seconds=incident.duration_seconds,
            size_bytes=incident.size_bytes,
            sha256=incident.sha256,
            storage_path=incident.storage_path,
            error=incident.error,
        )


def process_incident(
    incident_id: str,
    *,
    database: Any = db,
    runtime_settings: Any = settings,
    command_runner: CommandRunner = subprocess.run,
    server_root: Path = SERVER_ROOT,
) -> IncidentProcessingResult:
    """Process one incident using the application's configured services."""

    return IncidentProcessor(
        database=database,
        runtime_settings=runtime_settings,
        command_runner=command_runner,
        server_root=server_root,
    ).process(incident_id)


def _incident_from_row(row: tuple[Any, ...]) -> _Incident:
    return _Incident(
        camera_id=str(row[0]),
        requested_end=_as_utc(row[1]),
        processing_state=str(row[2]),
        actual_start=_as_utc(row[3]) if row[3] is not None else None,
        actual_end=_as_utc(row[4]) if row[4] is not None else None,
        duration_seconds=float(row[5]) if row[5] is not None else None,
        size_bytes=int(row[6]) if row[6] is not None else None,
        sha256=str(row[7]) if row[7] is not None else None,
        storage_path=str(row[8]) if row[8] is not None else None,
        error=str(row[9]) if row[9] is not None else None,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _file_metadata(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as clip:
        for block in iter(lambda: clip.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _concat_path(path: Path) -> str:
    """Format a path for FFmpeg's concat demuxer manifest."""

    # POSIX separators work for FFmpeg on Windows and avoid treating a
    # backslash as an escape in the concat file. Keep the quote escaping
    # explicit because filenames come from database metadata.
    value = path.as_posix().replace("'", "'\\''")
    return value


def _bounded_error(message: str, limit: int = 1000) -> str:
    message = message.strip() or "Incident assembly failed"
    return message[-limit:]


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary incident file %s", path)
