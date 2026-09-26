"""Tests for resolving FL511 cameras and recording them, without the network."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from server import fl511
from server.recorder import CameraRecorder, RecorderConfig

TOOLTIP = (
    '<div data-camera-id="5498" data-site-id="5499" '
    'data-videourl="https://dis-se15.divas.cloud:8200/chan-3703_h/index.m3u8"></div>'
)
TOKEN_REQUEST = '{"token":"abc","sourceId":"733","systemSourceId":"District 6"}'
TOKEN_QUERY = "?token=xyz"


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _fl511(responses: dict[str, object], requests: list | None = None):
    """A stand-in for urlopen that answers by URL prefix."""

    def urlopen(request, timeout):
        if requests is not None:
            requests.append(request)
        for prefix, answer in responses.items():
            if request.full_url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return _Response(str(answer).encode("utf-8"))
        raise AssertionError(f"unexpected request to {request.full_url}")

    return urlopen


def _answers(token_response: object = json.dumps(TOKEN_QUERY)) -> dict[str, object]:
    return {
        "https://fl511.com/tooltip/Cameras/5499": TOOLTIP,
        "https://fl511.com/Camera/GetVideoUrl?imageId=5498": TOKEN_REQUEST,
        fl511.TOKEN_SERVICE_URL: token_response,
    }


def _rate_limited(url: str) -> HTTPError:
    return HTTPError(url, 429, "Too Many Requests", {}, None)


class ResolveStreamUrlTests(unittest.TestCase):
    def test_returns_the_stream_url_with_a_fresh_token(self) -> None:
        requests: list = []
        with patch.object(fl511, "urlopen", _fl511(_answers(), requests)):
            url = fl511.resolve_stream_url(5499)

        self.assertEqual(
            url, "https://dis-se15.divas.cloud:8200/chan-3703_h/index.m3u8?token=xyz"
        )
        token_post = requests[-1]
        self.assertEqual(token_post.get_method(), "POST")
        self.assertEqual(token_post.data.decode("utf-8"), TOKEN_REQUEST)
        self.assertEqual(token_post.get_header("Origin"), "https://fl511.com")
        self.assertEqual(token_post.get_header("Referer"), "https://fl511.com/")
        self.assertTrue(all(r.get_header("User-agent") == fl511.USER_AGENT for r in requests))

    def test_camera_without_a_stream_is_an_error(self) -> None:
        answers = _answers()
        answers["https://fl511.com/tooltip/Cameras/5499"] = "<div>No video</div>"
        with patch.object(fl511, "urlopen", _fl511(answers)):
            with self.assertRaises(fl511.FL511Error):
                fl511.resolve_stream_url(5499)

    def test_token_service_answer_that_is_not_a_token_is_an_error(self) -> None:
        for answer in ("<html>maintenance</html>", json.dumps({"error": "no"}), '"no token"'):
            with self.subTest(answer=answer):
                with patch.object(fl511, "urlopen", _fl511(_answers(answer))):
                    with self.assertRaises(fl511.FL511Error):
                        fl511.resolve_stream_url(5499)

    def test_rate_limited_request_is_retried(self) -> None:
        calls = {"count": 0}
        succeed = _fl511(_answers())

        def urlopen(request, timeout):
            if "GetVideoUrl" in request.full_url and calls["count"] < 2:
                calls["count"] += 1
                raise _rate_limited(request.full_url)
            return succeed(request, timeout)

        with patch.object(fl511, "urlopen", urlopen), patch.object(fl511.time, "sleep") as sleep:
            url = fl511.resolve_stream_url(5499)

        self.assertTrue(url.endswith(TOKEN_QUERY))
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_rate_limit_that_does_not_clear_is_an_error(self) -> None:
        answers = _answers()
        answers["https://fl511.com/tooltip/Cameras/5499"] = _rate_limited("tooltip")
        with patch.object(fl511, "urlopen", _fl511(answers)), patch.object(fl511.time, "sleep") as sleep:
            with self.assertRaises(fl511.FL511Error):
                fl511.resolve_stream_url(5499)
        self.assertEqual(sleep.call_count, 3)

    def test_other_http_errors_are_not_retried(self) -> None:
        answers = _answers()
        answers["https://fl511.com/tooltip/Cameras/5499"] = HTTPError("tooltip", 404, "Not Found", {}, None)
        with patch.object(fl511, "urlopen", _fl511(answers)), patch.object(fl511.time, "sleep") as sleep:
            with self.assertRaises(fl511.FL511Error):
                fl511.resolve_stream_url(5499)
        sleep.assert_not_called()


class InputUrlTests(unittest.TestCase):
    def test_site_id(self) -> None:
        self.assertTrue(fl511.is_fl511_input("fl511:450"))
        self.assertFalse(fl511.is_fl511_input("server/replay/camera-demo.mp4"))
        self.assertEqual(fl511.site_id("fl511:450"), 450)
        with self.assertRaises(fl511.FL511Error):
            fl511.site_id("fl511:abc")


class RecorderInputTests(unittest.TestCase):
    def _start(self, config: RecorderConfig) -> list[str]:
        with patch("server.recorder.subprocess.Popen") as popen:
            CameraRecorder(config).start()
        return popen.call_args.args[0]

    def test_live_fl511_camera_gets_a_fresh_url_and_stream_options(self) -> None:
        stream = "https://dis-se15.divas.cloud:8200/chan-3703_h/index.m3u8?token=xyz"
        with tempfile.TemporaryDirectory() as root:
            config = RecorderConfig(
                camera_id="fl511-733",
                input_url="fl511:5499",
                source_type="live",
                output_root=Path(root),
            )
            with patch.object(fl511, "resolve_stream_url", return_value=stream) as resolve:
                command = self._start(config)

        resolve.assert_called_once_with(5499)
        before_input = command[: command.index("-i")]
        self.assertEqual(command[command.index("-i") + 1], stream)
        self.assertIn("-re", before_input)
        self.assertEqual(before_input[before_input.index("-live_start_index") + 1], "-1")
        self.assertEqual(before_input[before_input.index("-user_agent") + 1], fl511.USER_AGENT)
        self.assertIn("Referer: https://fl511.com/", before_input[before_input.index("-headers") + 1])
        self.assertNotIn("-stream_loop", before_input)

    def test_replay_file_is_used_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config = RecorderConfig(
                camera_id="camera-demo",
                input_url="/replay/camera-demo.mp4",
                source_type="replay",
                output_root=Path(root),
            )
            with patch.object(fl511, "resolve_stream_url") as resolve:
                command = self._start(config)

        resolve.assert_not_called()
        self.assertEqual(command[command.index("-i") + 1], "/replay/camera-demo.mp4")
        self.assertIn("-stream_loop", command)
        self.assertNotIn("-headers", command)


if __name__ == "__main__":
    unittest.main()
