"""Focused tests for preserved incident clip assembly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-processor-test-secret")

from server.incident_processor import IncidentProcessor


UTC = timezone.utc


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeDatabase:
    def __init__(self, incident_row: tuple[Any, ...], segment_rows: list[tuple[Any, ...]]) -> None:
        self.incident_row = list(incident_row)
        self.segment_rows = segment_rows
        self.ready_update: tuple[Any, ...] | None = None
        self.failure_update: tuple[Any, ...] | None = None

    def connect(self) -> "_FakeDatabase":
        return self

    def __enter__(self) -> "_FakeDatabase":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select camera_id") and "from incident" in normalized:
            return _Result(tuple(self.incident_row))

        if normalized.startswith("select max(actual_end)"):
            latest = max((row[2] for row in self.segment_rows), default=None)
            return _Result((latest,))

        if normalized.startswith("update incident set processing_state = 'assembling'"):
            self.incident_row[2] = "assembling"
            return _Result(tuple(self.incident_row))

        if normalized.startswith("select file_path") and "from segment" in normalized:
            return _Result(rows=self.segment_rows)

        if normalized.startswith("update incident set actual_start"):
            self.ready_update = params
            (
                self.incident_row[3],
                self.incident_row[4],
                self.incident_row[5],
                self.incident_row[6],
                self.incident_row[7],
                self.incident_row[8],
            ) = params[:6]
            self.incident_row[2] = "ready"
            self.incident_row[9] = None
            return _Result()

        if normalized.startswith("update incident set processing_state = 'failed'"):
            self.failure_update = params
            self.incident_row[2] = "failed"
            self.incident_row[9] = params[0]
            return _Result()

        raise AssertionError(f"Unexpected query: {query}")


class IncidentProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep fixtures inside the worktree: this Windows environment does
        # not grant the test process permission to create under system temp.
        self.temp_dir = TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp_dir.name)
        self.media_root = self.root / "media"
        self.camera_root = self.media_root / "cameras" / "camera-demo"
        self.incidents_root = self.media_root / "incidents"
        self.camera_root.mkdir(parents=True)
        self.incident_id = "11111111-1111-1111-1111-111111111111"
        self.start = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)
        self.settings = SimpleNamespace(
            media_root=self.media_root,
            cameras_root=self.media_root / "cameras",
            incidents_root=self.incidents_root,
            ffmpeg_binary="ffmpeg",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _database(
        self,
        *,
        requested_end: datetime,
        file_paths: list[str],
        segment_end: int = 20,
    ) -> _FakeDatabase:
        segments = [
            (
                file_path,
                self.start + timedelta(seconds=index * 10),
                self.start + timedelta(seconds=min((index + 1) * 10, segment_end)),
            )
            for index, file_path in enumerate(file_paths)
        ]
        return _FakeDatabase(
            (
                "camera-demo",
                requested_end,
                "recording",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
            segments,
        )

    def _processor(self, database: _FakeDatabase, runner: Any) -> IncidentProcessor:
        return IncidentProcessor(
            database=database,
            runtime_settings=self.settings,
            command_runner=runner,
            server_root=self.root,
        )

    def test_assembles_preserved_segments_and_records_metadata(self) -> None:
        paths = [
            "media/cameras/camera-demo/segment-a.ts",
            "media/cameras/camera-demo/segment-b.ts",
        ]
        for index, path in enumerate(paths):
            target = self.root / path
            target.write_bytes(f"segment-{index}".encode())
        database = self._database(
            requested_end=self.start + timedelta(seconds=15),
            file_paths=paths,
        )
        commands: list[list[str]] = []

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            Path(command[-1]).write_bytes(b"assembled-mp4")
            return subprocess.CompletedProcess(command, 0, "", "")

        result = self._processor(database, runner).process(self.incident_id)
        output = self.incidents_root / self.incident_id / "clip.mp4"

        self.assertEqual(result.processing_state, "ready")
        self.assertEqual(result.actual_start, self.start)
        self.assertEqual(result.actual_end, self.start + timedelta(seconds=20))
        self.assertEqual(result.duration_seconds, 20.0)
        self.assertEqual(result.size_bytes, len(b"assembled-mp4"))
        self.assertEqual(result.sha256, hashlib.sha256(b"assembled-mp4").hexdigest())
        self.assertEqual(result.storage_path, f"media/incidents/{self.incident_id}/clip.mp4")
        self.assertTrue(output.is_file())
        self.assertEqual(database.incident_row[2], "ready")
        self.assertIn("-f", commands[0])
        self.assertIn("concat", commands[0])
        self.assertIn("-c", commands[0])
        self.assertIn("copy", commands[0])
        self.assertIn("+faststart", commands[0])
        self.assertFalse((output.parent / "segments.concat.txt").exists())

    def test_waits_until_post_trigger_window_is_preserved(self) -> None:
        path = "media/cameras/camera-demo/segment-a.ts"
        (self.root / path).write_bytes(b"segment")
        database = self._database(
            requested_end=self.start + timedelta(seconds=15),
            file_paths=[path],
            segment_end=10,
        )
        called = False

        def runner(*_: Any, **__: Any) -> None:
            nonlocal called
            called = True

        result = self._processor(database, runner).process(self.incident_id)

        self.assertEqual(result.processing_state, "recording")
        self.assertFalse(called)
        self.assertEqual(database.incident_row[2], "recording")

    def test_missing_segment_marks_incident_failed(self) -> None:
        # Two segments so the post-trigger window (15s) is covered and the
        # incident actually gets claimed for assembly; one of them is missing.
        present_path = "media/cameras/camera-demo/segment-a.ts"
        missing_path = "media/cameras/camera-demo/missing.ts"
        (self.root / present_path).write_bytes(b"segment")
        database = self._database(
            requested_end=self.start + timedelta(seconds=15),
            file_paths=[present_path, missing_path],
        )

        result = self._processor(database, lambda *_args, **_kwargs: None).process(
            self.incident_id
        )

        self.assertEqual(result.processing_state, "failed")
        self.assertIn("missing or empty", result.error or "")
        self.assertEqual(database.incident_row[2], "failed")

    def test_path_traversal_marks_incident_failed(self) -> None:
        # Two segments so the post-trigger window (15s) is covered and the
        # incident actually gets claimed for assembly; one of them escapes
        # the camera directory.
        present_path = "media/cameras/camera-demo/segment-a.ts"
        (self.root / present_path).write_bytes(b"segment")
        outside = self.root / "media" / "outside.ts"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"outside")
        database = self._database(
            requested_end=self.start + timedelta(seconds=15),
            file_paths=[present_path, "media/cameras/camera-demo/../../outside.ts"],
        )

        result = self._processor(database, lambda *_args, **_kwargs: None).process(
            self.incident_id
        )

        self.assertEqual(result.processing_state, "failed")
        self.assertIn("outside the camera media directory", result.error or "")
        self.assertTrue(outside.exists())

    def test_ffmpeg_failure_marks_incident_failed_and_removes_output(self) -> None:
        # Two segments so the post-trigger window (15s) is covered and the
        # incident actually gets claimed for assembly.
        paths = [
            "media/cameras/camera-demo/segment-a.ts",
            "media/cameras/camera-demo/segment-b.ts",
        ]
        for path in paths:
            (self.root / path).write_bytes(b"segment")
        database = self._database(
            requested_end=self.start + timedelta(seconds=15),
            file_paths=paths,
        )

        def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, "", "invalid input")

        result = self._processor(database, runner).process(self.incident_id)

        self.assertEqual(result.processing_state, "failed")
        self.assertIn("FFmpeg failed", result.error or "")
        self.assertFalse((self.incidents_root / self.incident_id / "clip.mp4").exists())
        self.assertFalse((self.incidents_root / self.incident_id / "segments.concat.txt").exists())


if __name__ == "__main__":
    unittest.main()
