"""Regression checks for retention deletion and incident preservation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "retention-test-secret")

from server import media_cleanup, retention


class _Result:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _Connection:
    def __init__(self, segments: list[dict[str, object]], files: list[Path]) -> None:
        self.segments = segments
        self.files = files
        self.events: list[str] = []
        self.preserve_before_delete = False
        self.fail_delete = False
        self.pending: list[str] = []
        self.committed_with_file = False
        self._deleted_in_transaction = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.events.append("rollback" if exc_type else "commit")
        if self._deleted_in_transaction:
            self.committed_with_file = all(path.exists() for path in self.files)
            self._deleted_in_transaction = False

    def execute(self, query: str, params: tuple[object, ...]) -> _Result:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select file_path from pending_media_delete"):
            return _Result([(path,) for path in self.pending])
        if normalized.startswith("insert into pending_media_delete"):
            if params[0] not in self.pending:
                self.pending.append(params[0])
            return _Result([])
        if normalized.startswith("delete from pending_media_delete"):
            self.pending.remove(params[0])
            return _Result([])
        if normalized.startswith("select max(actual_end)"):
            return _Result([(max(row["end"] for row in self.segments),)])
        if normalized.startswith("select id, file_path"):
            self.events.append("select")
            cutoff = params[1]
            return _Result([
                (row["id"], row["path"])
                for row in self.segments
                if row["status"] == "temporary" and row["end"] <= cutoff
            ])
        if normalized.startswith("delete from segment"):
            self.events.append("delete")
            self.delete_query = normalized
            self.delete_ids = params[1]
            if self.fail_delete:
                raise RuntimeError("database failure")
            if self.preserve_before_delete:
                self.segments[0]["status"] = "preserved"
            removed = [
                row for row in self.segments
                if row["id"] in params[1] and row["status"] == "temporary"
            ]
            self.segments = [row for row in self.segments if row not in removed]
            self._deleted_in_transaction = bool(removed)
            return _Result([(row["path"],) for row in removed])
        raise AssertionError(f"Unexpected query: {query}")


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1] / "media" / ".test-retention" / str(uuid4())
        self.media_root = self.root / "media"
        self.camera_root = self.media_root / "cameras" / "camera-demo"
        self.camera_root.mkdir(parents=True)
        self.old = self.camera_root / "old.ts"
        self.old.write_bytes(b"video")
        self.latest = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _worker(self) -> retention.RetentionWorker:
        return retention.RetentionWorker("camera-demo", self.root, self.media_root, 60)

    def _database(self, *, unsafe: bool = False) -> _Connection:
        return _Connection([
            {
                "id": "old",
                "path": "outside.ts" if unsafe else "media/cameras/camera-demo/old.ts",
                "status": "temporary",
                "end": self.latest - timedelta(seconds=120),
            },
            {
                "id": "latest",
                "path": "media/cameras/camera-demo/latest.ts",
                "status": "temporary",
                "end": self.latest,
            },
        ], [self.old])

    def test_preserved_between_select_and_delete_keeps_file(self) -> None:
        database = self._database()
        database.preserve_before_delete = True
        with patch.object(retention.db, "connect", return_value=database):
            count = self._worker().cleanup_once()

        self.assertEqual(count, 0)
        self.assertTrue(self.old.exists())
        self.assertEqual([event for event in database.events if event in ("select", "delete")], ["select", "delete"])
        self.assertIn("status = 'temporary'", database.delete_query)
        self.assertIn("returning file_path", database.delete_query)
        self.assertEqual(database.segments[0]["status"], "preserved")

    def test_unlinks_only_after_delete_commits(self) -> None:
        database = self._database()
        with patch.object(retention.db, "connect", return_value=database):
            count = self._worker().cleanup_once()

        self.assertEqual(count, 1)
        self.assertEqual([event for event in database.events if event in ("select", "delete")], ["select", "delete"])
        self.assertTrue(database.committed_with_file)
        self.assertFalse(self.old.exists())
        self.assertEqual([row["id"] for row in database.segments], ["latest"])

    def test_delete_failure_rolls_back_without_unlinking(self) -> None:
        database = self._database()
        database.fail_delete = True
        with patch.object(retention.db, "connect", return_value=database):
            with self.assertRaisesRegex(RuntimeError, "database failure"):
                self._worker().cleanup_once()

        self.assertEqual([event for event in database.events if event in ("select", "delete", "rollback")], ["select", "delete", "rollback"])
        self.assertTrue(self.old.exists())

    def test_unsafe_candidate_is_skipped(self) -> None:
        database = self._database(unsafe=True)
        with patch.object(retention.db, "connect", return_value=database):
            with self.assertLogs(retention.logger, level="ERROR") as logs:
                count = self._worker().cleanup_once()

        self.assertEqual(count, 0)
        self.assertEqual([event for event in database.events if event in ("select", "delete")], ["select"])
        self.assertTrue(self.old.exists())
        self.assertIn("Skipping unsafe segment path outside.ts", "\n".join(logs.output))

    def test_unlink_error_is_logged_after_commit(self) -> None:
        database = self._database()
        with (
            patch.object(retention.db, "connect", return_value=database),
            patch.object(Path, "unlink", side_effect=OSError("disk error")),
            self.assertLogs(media_cleanup.logger, level="ERROR") as logs,
        ):
            count = self._worker().cleanup_once()

        self.assertEqual(count, 1)
        self.assertTrue(self.old.exists())
        self.assertEqual([event for event in database.events if event in ("select", "delete")], ["select", "delete"])
        self.assertEqual(database.pending, ["media/cameras/camera-demo/old.ts"])
        self.assertIn("Could not delete queued media file", "\n".join(logs.output))

        with patch.object(retention.db, "connect", return_value=database):
            self._worker().cleanup_once()
        self.assertFalse(self.old.exists())
        self.assertEqual(database.pending, [])


if __name__ == "__main__":
    unittest.main()
