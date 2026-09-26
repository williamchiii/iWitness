"""Focused tests for incident preservation and worker isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from typing import Any

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-worker-test-secret")

try:
    from server.incident_worker import IncidentWorker
except ModuleNotFoundError:
    from incident_worker import IncidentWorker


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
    def __init__(
        self,
        incidents: list[tuple[Any, ...]],
        latest_by_incident: dict[str, Any],
        expired: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.incidents = incidents
        self.latest_by_incident = latest_by_incident
        self.expired = expired or []
        self.preserve_calls: list[tuple[Any, ...]] = []
        self.association_calls: list[tuple[Any, ...]] = []
        self.expiry_calls: list[str] = []

    def connect(self) -> "_FakeDatabase":
        return self

    def __enter__(self) -> "_FakeDatabase":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select id, storage_path"):
            return _Result(rows=self.expired)
        if normalized.startswith("select id, camera_id"):
            return _Result(rows=self.incidents)
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
            return _Result(rows=[("segment-shared",)])
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

    def test_expiry_releases_segments_before_retention(self) -> None:
        database = _FakeDatabase([], {}, expired=[("incident-expired", None)])

        submitted = IncidentWorker(database=database, processor=_Processor()).run_once()

        self.assertEqual(submitted, 0)
        self.assertEqual(database.expiry_calls, ["expire", "unlink"])
        self.assertEqual(database.preserve_calls, [(["segment-shared"],)])


if __name__ == "__main__":
    unittest.main()
