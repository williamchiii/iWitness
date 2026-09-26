"""Focused tests for incident preservation and worker isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import unittest
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-worker-test-secret")

import server.incident_worker as worker_module
from server.incident_worker import IncidentWorker


UTC = timezone.utc


@contextmanager
def _workspace_directory():
    base = Path(__file__).resolve().parents[1] / "media" / ".test-expiry"
    directory = base / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeDatabase:
    def __init__(
        self,
        incidents: list[tuple[Any, ...]],
        latest_by_incident: dict[str, Any],
        expired: list[tuple[Any, ...]] | None = None,
        exclusive: list[tuple[Any, ...]] | None = None,
        shared: list[str] | None = None,
        newly_shared: list[str] | None = None,
        fail_commit_for: str | None = None,
        delete_segment_returns: bool = True,
    ) -> None:
        self.incidents = incidents
        self.latest_by_incident = latest_by_incident
        self.expired = expired or []
        self.exclusive = exclusive or []
        self.shared = shared or []
        self.newly_shared = newly_shared or []
        self.preserve_calls: list[tuple[Any, ...]] = []
        self.association_calls: list[tuple[Any, ...]] = []
        self.expiry_calls: list[str] = []
        self.expiry_query: str | None = None
        self.recording_query: str | None = None
        self.linked_query: str | None = None
        self.fail_commit_for = fail_commit_for
        self.delete_segment_returns = delete_segment_returns
        self._locked_incident: str | None = None
        self.pending_paths: list[str] = []
        self._staged_paths: list[str] = []

    def connect(self) -> "_FakeDatabase":
        return self

    def __enter__(self) -> "_FakeDatabase":
        return self

    def __exit__(self, *_: object) -> None:
        if self.fail_commit_for is not None and self._locked_incident == self.fail_commit_for:
            self._locked_incident = None
            self._staged_paths.clear()
            raise RuntimeError("simulated transaction failure")
        self.pending_paths.extend(self._staged_paths)
        self._staged_paths.clear()
        self._locked_incident = None
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select file_path from pending_media_delete"):
            return _Result(rows=[(path,) for path in self.pending_paths])
        if normalized.startswith("insert into pending_media_delete"):
            self._staged_paths.append(params[0])
            return _Result()
        if normalized.startswith("delete from pending_media_delete"):
            self.pending_paths.remove(params[0])
            return _Result()
        if normalized.startswith("select id from incident"):
            self.expiry_query = normalized
            return _Result(rows=[(row[0],) for row in self.expired])
        if normalized.startswith("select storage_path from incident"):
            self._locked_incident = str(params[0])
            return _Result(row=next(((row[1],) for row in self.expired if row[0] == params[0]), None))
        if normalized.startswith("select s.id, s.file_path"):
            self.linked_query = normalized
            self.expiry_calls.append("select exclusive")
            return _Result(rows=self.exclusive)
        if normalized.startswith("select 1 from incident_segment"):
            self.expiry_calls.append("recheck")
            return _Result(row=(1,) if params[0] in self.newly_shared else None)
        if normalized.startswith("delete from segment"):
            self.expiry_calls.append("delete segment")
            return _Result(row=(params[0],) if self.delete_segment_returns else None)
        if normalized.startswith("select id, camera_id"):
            self.recording_query = normalized
            now = datetime.now(UTC)
            return _Result(rows=[
                row[:4] for row in self.incidents
                if len(row) == 4 or row[4] != "unclaimed"
                or row[5] is None or row[5] > now
            ])
        if normalized.startswith("update segment"):
            self.preserve_calls.append(params)
            return _Result()
        if normalized.startswith("insert into incident_segment"):
            self.association_calls.append(params)
            return _Result()
        if normalized.startswith("update incident"):
            self.expiry_calls.append("expire")
            return _Result()
        if normalized.startswith("delete from incident_segment"):
            self.expiry_calls.append("unlink")
            return _Result(rows=[(segment_id,) for segment_id in self.shared])
        if normalized.startswith("select max(s.actual_end)"):
            incident_id = str(params[0])
            return _Result((self.latest_by_incident.get(incident_id),))
        raise AssertionError(f"Unexpected query: {query}")


class _Processor:
    def __init__(self, failing_ids: set[str] | None = None) -> None:
        self.failing_ids = failing_ids or set()
        self.processed: list[str] = []

    def process(self, incident_id: str) -> None:
        self.processed.append(incident_id)
        if incident_id in self.failing_ids:
            raise RuntimeError("simulated FFmpeg failure")


class IncidentWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)
        self.incidents = [
            (
                "incident-ready",
                "camera-demo",
                self.start,
                self.start + timedelta(seconds=20),
            ),
            (
                "incident-waiting",
                "camera-demo",
                self.start,
                self.start + timedelta(seconds=30),
            ),
        ]

    def test_preserves_overlapping_segments_and_processes_ready_incidents(self) -> None:
        database = _FakeDatabase(
            self.incidents,
            {
                "incident-ready": self.start + timedelta(seconds=20),
                "incident-waiting": self.start + timedelta(seconds=10),
            },
        )
        processor = _Processor()

        submitted = IncidentWorker(database=database, processor=processor).run_once()

        self.assertEqual(submitted, 1)
        self.assertEqual(processor.processed, ["incident-ready"])
        self.assertEqual(
            database.preserve_calls,
            [
                (
                    "incident-ready",
                    "camera-demo",
                    self.start + timedelta(seconds=20),
                    self.start,
                ),
                (
                    "incident-waiting",
                    "camera-demo",
                    self.start + timedelta(seconds=30),
                    self.start,
                ),
            ],
        )
        self.assertEqual(len(database.association_calls), 2)
        self.assertEqual(database.association_calls[0][0], "incident-ready")

    def test_processor_error_does_not_stop_later_incident(self) -> None:
        database = _FakeDatabase(
            self.incidents,
            {
                "incident-ready": self.start + timedelta(seconds=20),
                "incident-waiting": self.start + timedelta(seconds=30),
            },
        )
        processor = _Processor(failing_ids={"incident-ready"})

        with self.assertLogs(level="ERROR") as logs:
            submitted = IncidentWorker(database=database, processor=processor).run_once()

        self.assertEqual(submitted, 2)
        self.assertEqual(
            processor.processed,
            ["incident-ready", "incident-waiting"],
        )
        self.assertIn("incident-ready", "\n".join(logs.output))

    def test_expiry_deletes_exclusive_files_and_keeps_overlapping_segment(self) -> None:
        with _workspace_directory() as root:
            camera = root / "media" / "cameras" / "camera-demo"
            incident = root / "media" / "incidents" / "incident-expired"
            camera.mkdir(parents=True)
            incident.mkdir(parents=True)
            exclusive_file = camera / "exclusive.ts"
            shared_file = camera / "shared.ts"
            clip = incident / "clip.mp4"
            partial_clip = incident / "clip.tmp.mp4"
            manifest = incident / "segments.concat.txt"
            for path in (exclusive_file, shared_file, clip, partial_clip, manifest):
                path.write_bytes(b"video")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", "media/incidents/incident-expired/clip.mp4")],
                exclusive=[("segment-exclusive", "media/cameras/camera-demo/exclusive.ts", "camera-demo")],
                shared=["segment-shared"],
            )
            settings = SimpleNamespace(cameras_root=root / "media" / "cameras", incidents_root=root / "media" / "incidents")
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                submitted = IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertEqual(submitted, 0)
            self.assertFalse(exclusive_file.exists())
            self.assertFalse(clip.exists())
            self.assertFalse(partial_clip.exists())
            self.assertFalse(manifest.exists())
            self.assertTrue(shared_file.exists())
            self.assertEqual(database.expiry_calls, ["select exclusive", "recheck", "delete segment", "expire", "unlink"])
            self.assertEqual(database.preserve_calls, [(["segment-shared"],)])

    def test_expiry_rejects_segment_path_outside_camera(self) -> None:
        with _workspace_directory() as root:
            unrelated = root / "unrelated.ts"
            unrelated.write_bytes(b"keep")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", None)],
                exclusive=[("segment-exclusive", "unrelated.ts", "camera-demo")],
            )
            settings = SimpleNamespace(cameras_root=root / "media" / "cameras", incidents_root=root / "media" / "incidents")
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                with self.assertLogs(level="ERROR") as logs:
                    IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertTrue(unrelated.exists())
            self.assertEqual(database.expiry_calls, ["select exclusive", "recheck"])
            self.assertIn("Unsafe expired segment path", "\n".join(logs.output))

    def test_bad_storage_path_does_not_stop_later_expiry_or_assembly(self) -> None:
        with _workspace_directory() as root:
            unrelated = root / "unrelated.mp4"
            unrelated.write_bytes(b"keep")
            incident_dir = root / "media" / "incidents" / "incident-good"
            incident_dir.mkdir(parents=True)
            good_clip = incident_dir / "clip.mp4"
            good_clip.write_bytes(b"video")
            database = _FakeDatabase(
                [self.incidents[0]],
                {"incident-ready": self.start + timedelta(seconds=20)},
                expired=[("incident-bad", "unrelated.mp4"), ("incident-good", "media/incidents/incident-good/clip.mp4")],
            )
            processor = _Processor()
            settings = SimpleNamespace(cameras_root=root / "media" / "cameras", incidents_root=root / "media" / "incidents")
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                with self.assertLogs(level="ERROR") as logs:
                    submitted = IncidentWorker(database=database, processor=processor).run_once()

            self.assertEqual(submitted, 1)
            self.assertEqual(processor.processed, ["incident-ready"])
            self.assertTrue(unrelated.exists())
            self.assertFalse(good_clip.exists())
            self.assertIn("Unsafe expired clip path", "\n".join(logs.output))

    def test_expiry_query_failure_does_not_stop_assembly(self) -> None:
        class FailingExpiryDatabase(_FakeDatabase):
            def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
                if "select id from incident" in " ".join(query.split()).lower():
                    raise RuntimeError("simulated expiry query failure")
                return super().execute(query, params)

        database = FailingExpiryDatabase(
            [
                (*self.incidents[0], "unclaimed", datetime.now(UTC) - timedelta(minutes=1)),
                ("incident-claimed", "camera-demo", self.start,
                 self.start + timedelta(seconds=20), "claimed", None),
            ],
            {
                "incident-ready": self.start + timedelta(seconds=20),
                "incident-claimed": self.start + timedelta(seconds=20),
            },
        )
        processor = _Processor()
        with self.assertLogs(level="ERROR") as logs:
            submitted = IncidentWorker(database=database, processor=processor).run_once()

        self.assertEqual(submitted, 1)
        self.assertEqual(processor.processed, ["incident-claimed"])
        self.assertIn("simulated expiry query failure", "\n".join(logs.output))
        self.assertIn("expires_at > now()", database.recording_query)

    def test_commit_failure_preserves_segment_and_clip_files(self) -> None:
        with _workspace_directory() as root:
            camera = root / "media" / "cameras" / "camera-demo"
            incident = root / "media" / "incidents" / "incident-expired"
            camera.mkdir(parents=True)
            incident.mkdir(parents=True)
            segment = camera / "segment.ts"
            clip = incident / "clip.mp4"
            for path in (segment, clip):
                path.write_bytes(b"video")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", "media/incidents/incident-expired/clip.mp4")],
                exclusive=[("segment-one", "media/cameras/camera-demo/segment.ts", "camera-demo")],
                fail_commit_for="incident-expired",
            )
            settings = SimpleNamespace(cameras_root=root / "media" / "cameras", incidents_root=root / "media" / "incidents")
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                with self.assertLogs(level="ERROR") as logs:
                    IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertTrue(segment.exists())
            self.assertTrue(clip.exists())
            self.assertIn("simulated transaction failure", "\n".join(logs.output))

    def test_failed_clip_unlink_is_retried_on_next_poll(self) -> None:
        with _workspace_directory() as root:
            incident = root / "media" / "incidents" / "incident-expired"
            incident.mkdir(parents=True)
            clip = incident / "clip.mp4"
            clip.write_bytes(b"video")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", "media/incidents/incident-expired/clip.mp4")],
            )
            settings = SimpleNamespace(
                cameras_root=root / "media" / "cameras",
                incidents_root=root / "media" / "incidents",
            )
            worker = IncidentWorker(database=database, processor=_Processor())
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                with patch.object(Path, "unlink", side_effect=OSError("temporary disk failure")):
                    with self.assertLogs(level="ERROR"):
                        worker.run_once()
                self.assertTrue(clip.exists())
                self.assertIn("media/incidents/incident-expired/clip.mp4", database.pending_paths)

                database.expired = []
                worker.run_once()

            self.assertFalse(clip.exists())
            self.assertEqual(database.pending_paths, [])

    def test_guarded_delete_that_skips_segment_keeps_its_file(self) -> None:
        with _workspace_directory() as root:
            camera = root / "media" / "cameras" / "camera-demo"
            camera.mkdir(parents=True)
            segment = camera / "segment.ts"
            segment.write_bytes(b"video")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", None)],
                exclusive=[("segment-one", "media/cameras/camera-demo/segment.ts", "camera-demo")],
                delete_segment_returns=False,
            )
            settings = SimpleNamespace(
                cameras_root=root / "media" / "cameras",
                incidents_root=root / "media" / "incidents",
            )
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertTrue(segment.exists())

    def test_expiry_rechecks_shared_link_after_locking_segment(self) -> None:
        with _workspace_directory() as root:
            camera = root / "media" / "cameras" / "camera-demo"
            camera.mkdir(parents=True)
            segment_file = camera / "newly-shared.ts"
            segment_file.write_bytes(b"video")
            database = _FakeDatabase(
                [], {}, expired=[("incident-expired", None)],
                exclusive=[("segment-newly-shared", "media/cameras/camera-demo/newly-shared.ts", "camera-demo")],
                shared=["segment-newly-shared"],
                newly_shared=["segment-newly-shared"],
            )
            settings = SimpleNamespace(cameras_root=root / "media" / "cameras", incidents_root=root / "media" / "incidents")
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertTrue(segment_file.exists())
            self.assertNotIn("delete segment", database.expiry_calls)

    def test_shared_segment_is_recomputed_across_two_expiries(self) -> None:
        class SharedExpiryDatabase(_FakeDatabase):
            def __init__(self) -> None:
                super().__init__(
                    [], {}, expired=[("incident-a", None), ("incident-b", None)],
                )
                self.links = {"incident-a", "incident-b"}
                self.owner = "incident-a"
                self.owner_after_first: str | None = None
                self.segment_exists = True

            def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
                normalized = " ".join(query.split()).lower()
                if normalized.startswith("select s.id, s.file_path"):
                    self.linked_query = normalized
                    return _Result(rows=[
                        ("segment-shared", "media/cameras/camera-demo/shared.ts", "camera-demo")
                    ] if self.segment_exists and params[0] in self.links else [])
                if normalized.startswith("select 1 from incident_segment"):
                    return _Result(row=(1,) if self.links - {params[1]} else None)
                if normalized.startswith("delete from segment"):
                    self.segment_exists = False
                    return _Result(row=(params[0],))
                if normalized.startswith("delete from incident_segment"):
                    self.links.remove(params[0])
                    return _Result(rows=[("segment-shared",)])
                if normalized.startswith("update segment as s"):
                    if self.segment_exists:
                        self.owner = min(self.links) if self.links else None
                        if self.owner_after_first is None:
                            self.owner_after_first = self.owner
                    return _Result()
                return super().execute(query, params)

        with _workspace_directory() as root:
            camera = root / "media" / "cameras" / "camera-demo"
            camera.mkdir(parents=True)
            segment_file = camera / "shared.ts"
            segment_file.write_bytes(b"video")
            database = SharedExpiryDatabase()
            settings = SimpleNamespace(
                cameras_root=root / "media" / "cameras",
                incidents_root=root / "media" / "incidents",
            )
            with patch.object(worker_module, "SERVER_ROOT", root), patch.object(worker_module, "settings", settings):
                IncidentWorker(database=database, processor=_Processor()).run_once()

            self.assertIn("order by s.id for update of s", database.linked_query)
            self.assertNotIn("not exists", database.linked_query)
            self.assertEqual(database.owner_after_first, "incident-b")
            self.assertFalse(database.segment_exists)
            self.assertFalse(segment_file.exists())

    def test_expiry_recovers_assembling_incident_after_restart(self) -> None:
        database = _FakeDatabase([], {}, expired=[("incident-stale", None)])

        IncidentWorker(database=database, processor=_Processor()).run_once()

        # The expiry query must include rows left in assembling by a crash.
        self.assertNotIn("processing_state", database.expiry_query)
        self.assertIn("expire", database.expiry_calls)


if __name__ == "__main__":
    unittest.main()
