"""Switch the five I-95 cameras between their live FL511 feeds and saved
recordings of them, and save those recordings.

The judged demo must work without an unstable external feed. Save a few
minutes of each camera ahead of time, then switch to them if the network
is unreliable. Saved footage goes through the same recording pipeline and
the app labels it "Replayed".

    python camera_sources.py capture [--seconds 300] [camera id ...]
    python camera_sources.py use replay
    python camera_sources.py use live

``capture`` writes server/replay/<camera id>.mp4 (gitignored). Restart the
backend after ``use``: it reads each camera's input when it starts.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

try:
    from . import db, fl511
    from .config import SERVER_ROOT, settings
except ImportError:
    # Supports running from the server directory.
    import db
    import fl511
    from config import SERVER_ROOT, settings

# Camera id to FL511 site id; the same as migrations/004_fl511_live_cameras.sql.
FL511_SITES = {
    "fl511-760": 450,
    "fl511-733": 5499,
    "fl511-1329": 435,
    "fl511-1428": 5489,
    "fl511-736": 5488,
}


def replay_path(camera_id: str) -> Path:
    """Where a camera's saved recording lives."""

    return SERVER_ROOT / "replay" / f"{camera_id}.mp4"


def capture(seconds: int, camera_ids: list[str]) -> None:
    """Save the next ``seconds`` of each live feed (all when none are named), at once."""

    unknown = set(camera_ids) - set(FL511_SITES)
    if unknown:
        raise SystemExit(f"Unknown camera id: {', '.join(sorted(unknown))}")
    jobs: dict[str, tuple[subprocess.Popen[bytes], Path]] = {}
    for camera_id, site in FL511_SITES.items():
        if camera_ids and camera_id not in camera_ids:
            continue
        try:
            url = fl511.resolve_stream_url(site)
        except fl511.FL511Error as exc:
            print(f"{camera_id}: skipped, {exc}")
            continue
        target = replay_path(camera_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.stem}.part.mp4")
        command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            *fl511.ffmpeg_input_options(),
            "-i",
            url,
            "-t",
            str(seconds),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(partial),
        ]
        jobs[camera_id] = (subprocess.Popen(command, stdin=subprocess.DEVNULL), partial)
        print(f"{camera_id}: recording {seconds} s")

    for camera_id, (process, partial) in jobs.items():
        if process.wait() == 0 and partial.is_file() and partial.stat().st_size > 0:
            partial.replace(replay_path(camera_id))
            print(f"{camera_id}: saved {replay_path(camera_id).relative_to(SERVER_ROOT.parent)}")
        else:
            partial.unlink(missing_ok=True)
            print(f"{camera_id}: failed (FFmpeg exit code {process.returncode})")


def use(mode: str) -> None:
    """Point every camera at its live feed or at its saved recording."""

    with db.connect() as connection:
        for camera_id, site in FL511_SITES.items():
            if mode == "live":
                source_type, input_url = "live", f"{fl511.INPUT_PREFIX}{site}"
            else:
                path = replay_path(camera_id)
                if not path.is_file():
                    print(f"{camera_id}: no saved recording at {path}; left as is")
                    continue
                source_type = "replay"
                input_url = str(path.relative_to(SERVER_ROOT.parent))
            connection.execute(
                "UPDATE camera SET source_type = %s, input_url = %s WHERE id = %s",
                (source_type, input_url, camera_id),
            )
            print(f"{camera_id}: {source_type} ({input_url})")
    print("Restart the backend to apply.")


def main() -> None:
    """Parse the command line and run it."""

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture", help="save each live feed")
    capture_parser.add_argument("--seconds", type=int, default=300)
    capture_parser.add_argument("cameras", nargs="*", metavar="camera id")
    use_parser = commands.add_parser("use", help="switch camera inputs")
    use_parser.add_argument("mode", choices=["live", "replay"])
    args = parser.parse_args()
    if args.command == "capture":
        capture(args.seconds, args.cameras)
    else:
        use(args.mode)


if __name__ == "__main__":
    main()
