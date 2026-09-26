"""Resolve a Florida 511 camera to a stream URL FFmpeg can record.

FL511 serves camera video from FDOT's DIVAS system behind a short-lived
token, the same token fl511.com fetches for its own player:

1. The camera's tooltip page lists its image id and stream URL.
2. ``/Camera/GetVideoUrl?imageId=...`` returns a token request.
3. The DIVAS token service exchanges that for ``?token=...``, appended to
   the stream URL.

The stream server also checks Origin and Referer, so FFmpeg must send
``STREAM_HEADERS``. Tokens expire, so resolve a fresh URL every time
FFmpeg starts; never store one.

A camera row selects this with ``input_url = 'fl511:<site id>'``, where the
site id is the number in the camera's fl511.com tooltip URL.
"""

from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

FL511_ORIGIN = "https://fl511.com"
TOKEN_SERVICE_URL = (
    "https://divas.cloud/VDS-API/SecureTokenUri/GetSecureTokenUriBySourceId"
)
INPUT_PREFIX = "fl511:"
USER_AGENT = "Mozilla/5.0 (compatible; iWitness)"
STREAM_HEADERS = {"Origin": FL511_ORIGIN, "Referer": f"{FL511_ORIGIN}/"}

# FL511 rate-limits token requests (HTTP 429), for example when every camera
# starts at once. Wait and retry this many times, doubling from 2 s.
_RATE_LIMIT_RETRIES = 3

_IMAGE_ID = re.compile(r'data-camera-id="(\d+)"')
_VIDEO_URL = re.compile(r'data-videourl="([^"]+)"')


class FL511Error(RuntimeError):
    """FL511 or DIVAS did not return a usable stream URL."""


def is_fl511_input(input_url: str) -> bool:
    """Whether a camera's input_url names an FL511 camera."""

    return str(input_url).startswith(INPUT_PREFIX)


def site_id(input_url: str) -> int:
    """Return the FL511 site id from an ``fl511:<site id>`` input_url."""

    value = str(input_url).removeprefix(INPUT_PREFIX)
    if not value.isdigit():
        raise FL511Error(f"Expected fl511:<site id>, got {input_url!r}")
    return int(value)


def ffmpeg_input_options() -> list[str]:
    """FFmpeg options (before ``-i``) the DIVAS stream server requires."""

    headers = "".join(f"{name}: {value}\r\n" for name, value in STREAM_HEADERS.items())
    return ["-user_agent", USER_AGENT, "-headers", headers]


def _fetch(request: Request, timeout: float) -> str:
    request.add_header("User-Agent", USER_AGENT)
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code != 429 or attempt == _RATE_LIMIT_RETRIES:
                raise FL511Error(f"Request to {request.full_url} failed: {exc}") from exc
            retry_after = exc.headers.get("Retry-After", "")
            time.sleep(min(int(retry_after), 30) if retry_after.isdigit() else 2 * 2**attempt)
        except OSError as exc:
            raise FL511Error(f"Request to {request.full_url} failed: {exc}") from exc
    raise AssertionError("unreachable")


def resolve_stream_url(site: int, timeout: float = 10.0) -> str:
    """Return the camera's HLS URL with a fresh DIVAS token appended."""

    tooltip = _fetch(
        Request(f"{FL511_ORIGIN}/tooltip/Cameras/{site}?lang=en&noCss=true"),
        timeout,
    )
    image_id = _IMAGE_ID.search(tooltip)
    video_url = _VIDEO_URL.search(tooltip)
    if image_id is None or video_url is None:
        raise FL511Error(f"FL511 camera {site} has no video stream listed")
    stream_url = video_url.group(1)
    if urlsplit(stream_url).scheme != "https":
        raise FL511Error(f"FL511 camera {site} lists an unexpected stream URL")

    token_request = _fetch(
        Request(f"{FL511_ORIGIN}/Camera/GetVideoUrl?imageId={image_id.group(1)}"),
        timeout,
    )
    token_query = json.loads(
        _fetch(
            Request(
                TOKEN_SERVICE_URL,
                data=token_request.encode("utf-8"),
                headers={"Content-Type": "application/json", **STREAM_HEADERS},
                method="POST",
            ),
            timeout,
        )
    )
    if not isinstance(token_query, str) or not token_query.startswith("?token="):
        raise FL511Error(f"DIVAS returned no token for FL511 camera {site}")
    return stream_url + token_query
