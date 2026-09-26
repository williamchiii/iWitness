"""Start and manage one FFmpeg camera recorder process.

The recorder writes short MPEG-TS segments into the camera's media directory.
Database rows and retention cleanup are deliberately handled by higher-level
services so this module has one responsibility: managing FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Literal

try:
    from .config import settings
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    from config import settings


SourceType = Literal["live", "replay"]


@dataclass(frozen=True)
class RecorderConfig:
    """Configuration for one camera recorder."""

    camera_id: str
    input_url: str | Path
    output_root: Path | None = None
    source_type: SourceType = "replay"
    segment_seconds: int | None = None
    video_codec: str = "libx264"
    preset: str = "veryfast"
    ffmpeg_binary: str | None = None

    def __post_init__(self) -> None:
        if not self.camera_id:
            raise ValueError("camera_id must not be empty")
        if self.segment_seconds is not None and self.segment_seconds <= 0:
            raise ValueError("segment_seconds must be greater than zero")


class CameraRecorder:
    """Manage the FFmpeg process for one camera."""

    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._run_id = time.time_ns()

    @property
    def output_directory(self) -> Path:
        """Return the directory where this camera's segments are written."""

        output_root = self.config.output_root or settings.cameras_root
        return output_root / self.config.camera_id

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """Return the active FFmpeg process, if one has been started."""

        return self._process

    @property
    def is_running(self) -> bool:
        """Whether FFmpeg is currently running."""

        return self._process is not None and self._process.poll() is None

    def command(self) -> list[str]:
        """Build the FFmpeg command without starting a process."""

        segment_seconds = self.config.segment_seconds or settings.segment_seconds
        command = [
            self.config.ffmpeg_binary or settings.ffmpeg_binary,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-y",
        ]

        if self.config.source_type == "replay":
            # Replay a local file at normal speed and loop it for the demo.
            command.extend(["-re", "-stream_loop", "-1"])

        command.extend(
            [
                "-i",
                str(self.config.input_url),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                self.config.video_codec,
                "-preset",
                self.config.preset,
                "-pix_fmt",
                "yuv420p",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{segment_seconds})",
                "-f",
                "segment",
                "-segment_time",
                str(segment_seconds),
                "-segment_format",
                "mpegts",
                "-reset_timestamps",
                "1",
                str(self.output_directory / f"segment-{self._run_id}-%06d.ts"),
            ]
        )
        return command

    def start(self) -> subprocess.Popen[bytes]:
        """Create the output directory and start FFmpeg.

        The command is passed as an argument list with ``shell=False`` so the
        input URL and output paths are not interpreted by a shell.
        """

        if self.is_running:
            raise RuntimeError(f"recorder for {self.config.camera_id!r} is already running")

        self.output_directory.mkdir(parents=True, exist_ok=True)
        self._run_id = time.time_ns()

        try:
            self._process = subprocess.Popen(
                self.command(),
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"FFmpeg executable not found: {self.config.ffmpeg_binary!r}"
            ) from exc

        return self._process

    def stop(self, timeout_seconds: float = 10.0) -> None:
        """Stop FFmpeg and force-kill it if it does not exit in time."""

        process = self._process
        if process is None or process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def __enter__(self) -> "CameraRecorder":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
