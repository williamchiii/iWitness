"""Watch one camera's FFmpeg process and restart it if it dies."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

try:
    from .recorder import CameraRecorder
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    from recorder import CameraRecorder


logger = logging.getLogger(__name__)


class RecorderSupervisor:
    """Restart a camera's recorder if FFmpeg exits unexpectedly."""

    def __init__(
        self,
        camera_id: str,
        recorder: CameraRecorder,
        on_recording_change: Callable[[str, bool], None],
        poll_seconds: float = 3.0,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 60.0,
        healthy_after_seconds: float = 30.0,
    ) -> None:
        self.camera_id = camera_id
        self.recorder = recorder
        self.on_recording_change = on_recording_change
        self.poll_seconds = poll_seconds
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.healthy_after_seconds = healthy_after_seconds
        self._consecutive_failures = 0
        self._started_at = time.monotonic()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError(f"supervisor for {self.camera_id!r} is already running")

        self._started_at = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"recorder-supervisor-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            if self.recorder.is_running:
                if time.monotonic() - self._started_at >= self.healthy_after_seconds:
                    self._consecutive_failures = 0
                continue
            self._handle_crash()

    def _handle_crash(self) -> None:
        """Log the crash, mark the camera down, and try to restart it."""

        exit_code = self.recorder.process.returncode if self.recorder.process else None
        tail = self.recorder.tail_log()
        logger.error(
            "Recorder for camera %s exited unexpectedly (exit code %s)%s",
            self.camera_id,
            exit_code,
            f"; last FFmpeg output:\n{tail}" if tail else "",
        )
        self.on_recording_change(self.camera_id, False)

        backoff = min(
            self.base_backoff_seconds * (2**self._consecutive_failures),
            self.max_backoff_seconds,
        )
        self._consecutive_failures += 1
        if self._stop_event.wait(backoff):
            return

        try:
            self.recorder.start()
        except Exception:
            logger.exception("Failed to restart recorder for camera %s", self.camera_id)
            return

        self._started_at = time.monotonic()
        self.on_recording_change(self.camera_id, True)
        logger.info("Restarted recorder for camera %s", self.camera_id)
