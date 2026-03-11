#!/usr/bin/env python3
"""
Schedule database integration for per-chapter YouTube uploads.

Uses the shared visurena_studio.db schedule table to claim time slots
for audiobook chapter uploads with scheduled publishing.

Table schema:
    schedule(env TEXT, time_slot TEXT, type TEXT, book_id TEXT, book_name TEXT, part INTEGER)
    PK: (env, time_slot, type)
    time_slot format: YYYYMMDDHHMM (e.g., "202603101000")
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEDULE_DB = Path(r"D:\Projects\GlobalDatabases\visurena_studio.db")


def claim_slots(
    book_id: str,
    book_name: str,
    num_chapters: int,
    env: str = "alpha",
) -> list[dict]:
    """
    Claim N free time slots for a book's chapter uploads.

    Args:
        book_id:       Unique book identifier (e.g., "pg11")
        book_name:     Human-readable book name for the schedule
        num_chapters:  Number of slots to claim (one per chapter)
        env:           Environment ("alpha" or "prod")

    Returns:
        List of dicts: [{"part": 1, "time_slot": "202603101000", "publish_at": "2026-03-10T10:00:00.000Z"}, ...]

    Raises:
        ValueError: If not enough free slots available
    """
    conn = sqlite3.connect(str(SCHEDULE_DB))
    try:
        cur = conn.cursor()

        # Find free slots
        cur.execute(
            "SELECT time_slot FROM schedule "
            "WHERE book_id IS NULL AND env = ? AND type = 'audiobook' "
            "ORDER BY time_slot LIMIT ?",
            (env, num_chapters),
        )
        rows = cur.fetchall()

        if len(rows) < num_chapters:
            raise ValueError(
                f"Only {len(rows)} free slots available for env={env}, "
                f"need {num_chapters}"
            )

        slots = []
        for i, (time_slot,) in enumerate(rows, start=1):
            cur.execute(
                "UPDATE schedule SET book_id = ?, book_name = ?, part = ? "
                "WHERE env = ? AND time_slot = ? AND type = 'audiobook'",
                (book_id, book_name, i, env, time_slot),
            )
            slots.append({
                "part": i,
                "time_slot": time_slot,
                "publish_at": time_slot_to_publish_at(time_slot),
            })

        conn.commit()
        return slots

    finally:
        conn.close()


def release_slots(book_id: str, env: str = "alpha") -> int:
    """
    Release all slots claimed by a book (rollback on failure).

    Returns:
        Number of slots released.
    """
    conn = sqlite3.connect(str(SCHEDULE_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE schedule SET book_id = NULL, book_name = NULL, part = NULL "
            "WHERE book_id = ? AND env = ?",
            (book_id, env),
        )
        released = cur.rowcount
        conn.commit()
        return released
    finally:
        conn.close()


def time_slot_to_publish_at(time_slot: str) -> str:
    """
    Convert schedule time_slot to YouTube publishAt ISO 8601 format.

    "202603101000" -> "2026-03-10T10:00:00.000Z"
    """
    dt = datetime.strptime(time_slot, "%Y%m%d%H%M")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
