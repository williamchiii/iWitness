"""Preserve camera segments overlapping an incident's recording window."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def preserve_segments(
    connection: Any,
    incident_id: Any,
    camera_id: str,
    window_start: datetime,
    window_end: datetime,
) -> None:
    """Mark temporary segments preserved and link all overlapping segments.

    The caller owns the transaction. Existing preserved segments can be shared
    by multiple incidents, so both statements use the same window bounds.
    """

    connection.execute(
        """
        UPDATE segment AS s
        SET status = 'preserved', incident_id = %s
        WHERE s.camera_id = %s
          AND s.status = 'temporary'
          AND s.actual_start < %s
          AND s.actual_end > %s
        """,
        (incident_id, camera_id, window_end, window_start),
    )
    connection.execute(
        """
        INSERT INTO incident_segment (incident_id, segment_id)
        SELECT %s, s.id
        FROM segment AS s
        WHERE s.camera_id = %s
          AND s.status = 'preserved'
          AND s.actual_start < %s
          AND s.actual_end > %s
        ON CONFLICT DO NOTHING
        """,
        (incident_id, camera_id, window_end, window_start),
    )
