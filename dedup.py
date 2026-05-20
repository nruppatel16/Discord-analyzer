"""
dedup.py — SQLite-backed deduplication for processed Discord message IDs.
Prevents the same message from appearing in multiple reports.
"""

import sqlite3
import logging
from datetime import datetime, timedelta

DB_PATH = "analyzer.db"
RETENTION_DAYS = 30

logger = logging.getLogger(__name__)


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the processed_messages table if it doesn't exist."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id   TEXT PRIMARY KEY,
                processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.debug("Dedup DB initialised at %s", DB_PATH)


def is_processed(message_id: str) -> bool:
    """Return True if this message_id has already been processed."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_messages WHERE message_id = ?",
            (str(message_id),)
        ).fetchone()
    return row is not None


def mark_processed(message_id: str):
    """Record a message_id as processed (INSERT OR IGNORE to be safe)."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
            (str(message_id), datetime.utcnow().isoformat())
        )
        conn.commit()


def mark_processed_bulk(message_ids: list):
    """Bulk-insert a list of message IDs in a single transaction."""
    if not message_ids:
        return
    now = datetime.utcnow().isoformat()
    rows = [(str(mid), now) for mid in message_ids]
    with _get_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
            rows
        )
        conn.commit()
    logger.debug("Marked %d message IDs as processed", len(message_ids))


def purge_old_records():
    """Delete records older than RETENTION_DAYS to keep the DB lean."""
    cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
    with _get_connection() as conn:
        result = conn.execute(
            "DELETE FROM processed_messages WHERE processed_at < ?",
            (cutoff,)
        )
        conn.commit()
    if result.rowcount:
        logger.info("Purged %d old dedup records (>%d days)", result.rowcount, RETENTION_DAYS)
