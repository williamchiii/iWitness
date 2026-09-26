"""Retry media-file deletion after the transaction that releases it commits."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger(__name__)


def enqueue(
    connection: Any,
    paths: Iterable[Path],
    *,
    server_root: Path,
    media_root: Path,
) -> None:
    """Add validated paths to the deletion queue in the caller's transaction."""

    root = server_root.resolve()
    media = media_root.resolve()
    for path in paths:
        candidate = path.resolve()
        if not candidate.is_relative_to(media) or not candidate.is_relative_to(root):
            raise ValueError(f"Unsafe media cleanup path: {path}")
        connection.execute(
            """
            INSERT INTO pending_media_delete (file_path)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (candidate.relative_to(root).as_posix(),),
        )


def drain(
    database: Any,
    *,
    server_root: Path,
    media_root: Path,
    limit: int = 100,
) -> None:
    """Remove queued files and clear each entry only after unlink succeeds."""

    root = server_root.resolve()
    media = media_root.resolve()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT file_path FROM pending_media_delete
            ORDER BY created_at, file_path
            LIMIT %s
            """,
            (limit,),
        ).fetchall()

    for (file_path,) in rows:
        path = (root / file_path).resolve()
        if not path.is_relative_to(media):
            logger.error("Skipping unsafe queued media path %s", file_path)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not delete queued media file %s", path)
            continue
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM pending_media_delete WHERE file_path = %s",
                (file_path,),
            )
