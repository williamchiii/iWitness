"""Check the public error envelope through the ASGI app."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "exception-handler-test-secret")

try:
    from server import main
    from server.tests.asgi_test_client import send_request
except ModuleNotFoundError:
    import main
    from tests.asgi_test_client import send_request


def _request(method: str, path: str) -> tuple[int, dict[str, str], str]:
    """Send one HTTP request and decode its body as text."""

    status, headers, body = send_request(main.app, method, path)
    return status, headers, body.decode("utf-8")


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
