"""Verify database dependencies can be overridden for real API requests."""

from __future__ import annotations

import asyncio
import json
import os
import unittest

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "dependency-test-secret")

try:
    from server import db, main
except ModuleNotFoundError:
    import db
    import main


class _Connection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, query: str) -> "_Connection":
        self.queries.append(query)
        return self

    def fetchall(self) -> list[tuple]:
        return [("camera-demo", "Demo", "I-95", "replay", True)]


def _get(path: str) -> tuple[int, object]:
    async def run() -> tuple[int, object]:
        messages: list[dict] = []
        received = False

        async def receive() -> dict:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        await main.app(scope, receive, send)
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return messages[0]["status"], json.loads(body)

    return asyncio.run(run())


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
