"""Minimal ASGI client shared by tests that exercise main.app directly."""

from __future__ import annotations

import asyncio
from typing import Any


def send_request(app: Any, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    """Send one HTTP request without an optional test-client dependency."""

    async def run() -> tuple[int, dict[str, str], bytes]:
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
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        try:
            await app(scope, receive, send)
        except Exception:
            # Starlette sends a 500 response, then reraises the original error.
            if not messages or messages[0]["status"] != 500:
                raise

        start = messages[0]
        headers = {
            name.decode("latin-1"): value.decode("latin-1")
            for name, value in start["headers"]
        }
        body = b"".join(
            message.get("body", b"") for message in messages[1:]
            if message["type"] == "http.response.body"
        )
        return start["status"], headers, body

    return asyncio.run(run())
