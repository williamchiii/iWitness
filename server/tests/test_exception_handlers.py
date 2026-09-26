"""Check the public error envelope through the ASGI app."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "exception-handler-test-secret")

try:
    from server import main
except ModuleNotFoundError:
    import main


def _request(method: str, path: str) -> tuple[int, dict[str, str], str]:
    """Send one HTTP request without an optional test-client dependency."""

    async def run() -> tuple[int, dict[str, str], str]:
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
            await main.app(scope, receive, send)
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
        ).decode("utf-8")
        return start["status"], headers, body

    return asyncio.run(run())


class ExceptionHandlerTests(unittest.TestCase):
    def test_unexpected_database_failure_has_safe_json_detail(self) -> None:
        secret = "database-password-should-stay-private"
        with (
            patch.object(main.db, "connect", side_effect=RuntimeError(secret)),
            patch.object(main.logger, "error") as log_error,
        ):
            status, headers, body = _request("GET", "/health")

        self.assertEqual(status, 500)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(json.loads(body), {"detail": "Internal server error"})
        self.assertNotIn(secret, body)
        self.assertNotIn("Traceback", body)
        self.assertEqual(log_error.call_args.args[1], "RuntimeError")
        self.assertNotIn(secret, str(log_error.call_args))

    def test_http_exception_keeps_status_detail_and_default_handler(self) -> None:
        with patch.dict(main.app.dependency_overrides, {main.db.get_db: object}):
            status, _, body = _request(
                "POST",
                "/trips/11111111-1111-1111-1111-111111111111/end"
            )

        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"detail": "Trip token required"})

    def test_validation_uses_contract_error_envelope(self) -> None:
        with patch.dict(main.app.dependency_overrides, {main.db.get_db: object}):
            status, _, body = _request("POST", "/trips/not-a-uuid/end")

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"detail": "Malformed request"})


if __name__ == "__main__":
    unittest.main()
