"""Verify database dependencies can be overridden for real API requests."""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "dependency-test-secret")

try:
    from server import db, main
    from server.tests.asgi_test_client import send_request
except ModuleNotFoundError:
    import db
    import main
    from tests.asgi_test_client import send_request


class _Connection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, query: str) -> "_Connection":
        self.queries.append(query)
        return self

    def fetchall(self) -> list[tuple]:
        return [("camera-demo", "Demo", "I-95", "replay", True)]


def _get(path: str) -> tuple[int, object]:
    """Send one GET request and decode its body as JSON."""

    status, _, body = send_request(main.app, "GET", path)
    return status, json.loads(body)


class DependencyTests(unittest.TestCase):
    def test_health_and_camera_routes_accept_database_override(self) -> None:
        connection = _Connection()
        main.app.dependency_overrides[db.get_db] = lambda: connection
        try:
            health_status, health_body = _get("/health")
            camera_status, cameras = _get("/cameras")
        finally:
            main.app.dependency_overrides.clear()

        self.assertEqual((health_status, health_body), (200, {"server": "healthy", "database": "healthy"}))
        self.assertEqual(camera_status, 200)
        self.assertEqual(cameras[0]["id"], "camera-demo")
        self.assertEqual(len(connection.queries), 2)


if __name__ == "__main__":
    unittest.main()
