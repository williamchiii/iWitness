"""Tests for the Library's clip thumbnails: signed links, making and serving
the still, and removing it with the clip."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from fastapi import HTTPException

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-thumbnail-test-secret")

from server import incident_lifecycle_routes as lifecycle
from server import incident_playback_routes as playback
from server.auth import Principal

INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TRIP_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_USER = "44444444-4444-4444-4444-444444444444"
START = datetime(2026, 9, 26, 20, 0, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, row: object = None, rows: list | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> object:
        return self.row

    def fetchall(self) -> list:
        return self.rows


class _Connection:
    """Answers the first query with ``row`` (or ``rows``), the rest with nothing."""

    def __init__(self, row: object = None, rows: list | None = None) -> None:
        self.first = _Result(row, rows)
        self.queries: list[str] = []

    def execute(self, query: str, _params: object = None) -> _Result:
        self.queries.append(" ".join(query.split()).lower())
        return self.first if len(self.queries) == 1 else _Result()


def _incident_row(state: str) -> tuple:
    return (
        INCIDENT_ID, TRIP_ID, "fl511-760", "I-95 at NW 13th St", "live",
        START + timedelta(seconds=60), START, START + timedelta(seconds=75),
        START, START + timedelta(seconds=75), None, None,
        75.0, 1000, "ab" * 32, state, "claimed", None, 1, None,
    )


def _principal() -> Principal:
    return Principal(id=str(USER_ID), email="o@example.com", display_name=None, avatar_url=None, role="authenticated")


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


class SignedThumbnailUrlTests(unittest.TestCase):
    def test_link_is_relative_signed_and_stable_within_a_window(self) -> None:
        settings = playback.get_settings()
        first = playback.signed_thumbnail_url(INCIDENT_ID, str(USER_ID))
        second = playback.signed_thumbnail_url(INCIDENT_ID, str(USER_ID))

        self.assertTrue(first.startswith(f"/playback/incidents/{INCIDENT_ID}/thumbnail?"))
        self.assertEqual(first, second)
        query = _query(first)
        self.assertEqual(query["uid"], str(USER_ID))
        expires_in = int(query["exp"]) - time.time()
        window = settings.playback_url_seconds
        self.assertTrue(window <= expires_in <= 2 * window + 1, expires_in)
        # A link for one user doesn't verify for another.
        playback._verify_signature(
            f"incident|{INCIDENT_ID}|{USER_ID}|thumbnail", int(query["exp"]), query["sig"], settings
        )
        with self.assertRaises(HTTPException):
            playback._verify_signature(
                f"incident|{INCIDENT_ID}|{OTHER_USER}|thumbnail", int(query["exp"]), query["sig"], settings
            )

    def test_still_is_taken_at_the_press_within_the_clip(self) -> None:
        offset = playback._thumbnail_offset
        self.assertEqual(offset(START + timedelta(seconds=60), START, 75.0), 60.0)
        self.assertEqual(offset(START + timedelta(seconds=90), START, 75.0), 74.5)
        self.assertEqual(offset(START - timedelta(seconds=5), START, 75.0), 0.0)
        self.assertEqual(offset(None, None, 75.0), 37.5)


class ListThumbnailTests(unittest.TestCase):
    def test_only_ready_clips_get_a_thumbnail_link(self) -> None:
        connection = _Connection(rows=[_incident_row("ready"), _incident_row("assembling")])
        ready, assembling = lifecycle.list_incidents(principal=_principal(), connection=connection)

        self.assertTrue(ready.thumbnail_url.startswith(f"/playback/incidents/{INCIDENT_ID}/thumbnail?"))
        self.assertEqual(_query(ready.thumbnail_url)["uid"], str(USER_ID))
        self.assertIsNone(assembling.thumbnail_url)

    def test_detail_gets_a_thumbnail_link_when_ready(self) -> None:
        connection = _Connection(row=_incident_row("ready"))
        incident = lifecycle.get_incident(INCIDENT_ID, principal=_principal(), connection=connection)
        self.assertIsNotNone(incident.thumbnail_url)


class ServeThumbnailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = replace(playback.get_settings(), media_root=Path(self._tmp.name).resolve())
        self.directory = self.settings.incidents_root / str(INCIDENT_ID)
        self.directory.mkdir(parents=True)
        self.clip = self.directory / "clip.mp4"
        self.clip.write_bytes(b"not really an mp4")

    def _serve(self, row: tuple | None, user_id: str = str(USER_ID)):
        url = playback.signed_thumbnail_url(INCIDENT_ID, user_id, self.settings)
        query = _query(url)
        return playback.serve_incident_thumbnail(
            INCIDENT_ID,
            uid=query["uid"],
            exp=int(query["exp"]),
            sig=query["sig"],
            connection=_Connection(row=row),
            settings=self.settings,
        )

    def _row(self, state: str = "ready", owner: UUID | str = USER_ID) -> tuple:
        return (str(self.clip), owner, state, START + timedelta(seconds=60), START, 75.0)

    @staticmethod
    def _fake_ffmpeg(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        Path(command[-1]).write_bytes(b"\xff\xd8 jpeg")
        return subprocess.CompletedProcess(command, 0)

    def test_first_request_makes_the_still_at_the_press_then_reuses_it(self) -> None:
        with patch.object(playback.subprocess, "run", side_effect=self._fake_ffmpeg) as run:
            first = self._serve(self._row())
            second = self._serve(self._row())

        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-ss") + 1], "60.000")
        self.assertEqual(command[command.index("-i") + 1], str(self.clip))
        self.assertEqual(Path(first.path), self.directory / playback.THUMBNAIL_NAME)
        self.assertEqual(first.media_type, "image/jpeg")
        self.assertEqual(Path(second.path), Path(first.path))
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["clip.mp4", "thumbnail.jpg"])

    def test_forged_signature_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            playback.serve_incident_thumbnail(
                INCIDENT_ID, uid=str(USER_ID), exp=int(time.time()) + 60, sig="0" * 64,
                connection=_Connection(row=self._row()), settings=self.settings,
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_someone_elses_clip_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._serve(self._row(owner=OTHER_USER))
        self.assertEqual(raised.exception.status_code, 404)

    def test_clip_that_is_not_ready_has_no_thumbnail(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._serve(self._row(state="assembling"))
        self.assertEqual(raised.exception.status_code, 409)

    def test_ffmpeg_failure_is_an_error_and_leaves_no_partial_file(self) -> None:
        failure = subprocess.CalledProcessError(1, "ffmpeg")
        with patch.object(playback.subprocess, "run", side_effect=failure):
            with self.assertRaises(HTTPException) as raised:
                self._serve(self._row())
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual([p.name for p in self.directory.iterdir()], ["clip.mp4"])

    def test_deleting_the_incident_removes_its_thumbnail(self) -> None:
        thumbnail = self.directory / playback.THUMBNAIL_NAME
        thumbnail.write_bytes(b"\xff\xd8 jpeg")
        playback.delete_incident(
            INCIDENT_ID,
            principal=_principal(),
            connection=_Connection(row=(str(self.clip), "ready")),
            settings=self.settings,
        )
        self.assertFalse(self.clip.exists())
        self.assertFalse(thumbnail.exists())


if __name__ == "__main__":
    unittest.main()
