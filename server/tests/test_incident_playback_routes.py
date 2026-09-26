"""Focused tests for private incident playback and deletion."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import Response

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-playback-test-secret")

from server import incident_playback_routes as routes
from server.auth import Principal


INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = "22222222-2222-2222-2222-222222222222"


class _Result:
    def __init__(self, row: object = None) -> None:
        self.row = row

    def fetchone(self) -> object:
        return self.row

    def fetchall(self) -> list[tuple[UUID]]:
        return [(UUID("33333333-3333-3333-3333-333333333333"),)]


class _Connection:
    def __init__(self, row: object, signed_row: object | None = None) -> None:
        self.row = row
        self.signed_row = signed_row if signed_row is not None else row
        self.statements: list[str] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, _params: object = None) -> _Result:
        normalized = " ".join(query.split()).lower()
        self.statements.append(normalized)
        if normalized.startswith("select storage_path"):
            return _Result(self.row if "video_version" in normalized else self.signed_row)
        return _Result()


class _Database:
    def __init__(self, row: object, signed_row: object | None = None) -> None:
        self.connection = _Connection(row, signed_row)

    def connect(self) -> _Connection:
        return self.connection


def _request(path: str) -> object:
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 8000),
            "client": ("testclient", 50000),
            "headers": [],
            "query_string": b"",
        }
    )


def _principal() -> Principal:
    return Principal(
        id=USER_ID,
        email="owner@example.com",
        display_name="Owner",
        avatar_url=None,
        role="authenticated",
    )


@contextmanager
def _workspace_directory() -> object:
    """Use the workspace because this Windows environment restricts Temp."""

    base = Path(__file__).resolve().parents[1] / "media" / ".test-playback"
    directory = base / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class IncidentPlaybackRouteTests(unittest.TestCase):
    def test_playback_rejects_incident_until_ready(self) -> None:
        database = _Database(("media/incidents/incident/clip.mp4", "recording", 1))
        with patch.object(routes, "db", database):
            with self.assertRaises(HTTPException) as raised:
                routes.get_incident_playback(
                    INCIDENT_ID,
                    _request("/incidents/playback"),
                    _principal(),
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_playback_issues_signed_stream_and_download_urls(self) -> None:
        with _workspace_directory() as root:
            incident_directory = root / "media" / "incidents" / str(INCIDENT_ID)
            incident_directory.mkdir(parents=True)
            clip = incident_directory / "clip.mp4"
            clip.write_bytes(b"private clip")
            database = _Database(
                (str(clip), "ready", 3),
                (str(clip), USER_ID, "ready"),
            )
            runtime = SimpleNamespace(
                incidents_root=root / "media" / "incidents",
                playback_signing_secret="incident-playback-test-secret",
                playback_url_seconds=300,
            )
            with (
                patch.object(routes, "db", database),
                patch.object(routes, "settings", runtime),
                patch.object(routes, "SERVER_ROOT", root),
            ):
                response = routes.get_incident_playback(
                    INCIDENT_ID,
                    _request("/incidents/playback"),
                    _principal(),
                )

                stream_query = parse_qs(urlparse(response.playback_url).query)
                stream = routes.serve_incident_clip(
                    INCIDENT_ID,
                    uid=stream_query["uid"][0],
                    exp=int(stream_query["exp"][0]),
                    sig=stream_query["sig"][0],
                    download=False,
                )

            self.assertEqual(response.video_version, 3)
            self.assertEqual(Path(stream.path), clip)
            self.assertIn("download=1", response.download_url)

    def test_delete_removes_owned_clip_and_returns_no_content(self) -> None:
        with _workspace_directory() as root:
            incident_directory = root / "media" / "incidents" / str(INCIDENT_ID)
            incident_directory.mkdir(parents=True)
            clip = incident_directory / "clip.mp4"
            clip.write_bytes(b"private clip")
            database = _Database((str(clip), "ready"))
            runtime = SimpleNamespace(incidents_root=root / "media" / "incidents")
            with (
                patch.object(routes, "db", database),
                patch.object(routes, "settings", runtime),
                patch.object(routes, "SERVER_ROOT", root),
            ):
                response = routes.delete_incident(INCIDENT_ID, _principal())

            self.assertIsInstance(response, Response)
            self.assertEqual(response.status_code, 204)
            self.assertFalse(clip.exists())
            self.assertTrue(
                any(statement.startswith("update segment") for statement in database.connection.statements)
            )
            self.assertTrue(
                any(statement.startswith("delete from incident") for statement in database.connection.statements)
            )

    def test_other_owner_receives_not_found(self) -> None:
        database = _Database(None)
        with patch.object(routes, "db", database):
            with self.assertRaises(HTTPException) as raised:
                routes.delete_incident(INCIDENT_ID, _principal())
        self.assertEqual(raised.exception.status_code, 404)

    def test_delete_rejects_clip_while_assembling(self) -> None:
        database = _Database((None, "assembling"))
        with patch.object(routes, "db", database):
            with self.assertRaises(HTTPException) as raised:
                routes.delete_incident(INCIDENT_ID, _principal())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(
            any(
                statement.startswith("delete from incident")
                for statement in database.connection.statements
            )
        )


if __name__ == "__main__":
    unittest.main()
