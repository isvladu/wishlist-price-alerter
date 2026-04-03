"""SQLite storage for price history and notification deduplication."""

import sqlite3
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "prices.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist, and run one-time migrations."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                appid       INTEGER PRIMARY KEY,
                name        TEXT    NOT NULL,
                last_checked TEXT
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                appid       INTEGER NOT NULL,
                source      TEXT    NOT NULL,
                price_usd   REAL    NOT NULL,
                currency    TEXT    NOT NULL DEFAULT 'USD',
                store_url   TEXT,
                captured_at TEXT    NOT NULL,
                FOREIGN KEY (appid) REFERENCES games(appid)
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_appid ON price_snapshots(appid);
            CREATE INDEX IF NOT EXISTS idx_snapshots_source ON price_snapshots(source);

            CREATE TABLE IF NOT EXISTS notifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                appid       INTEGER NOT NULL,
                source      TEXT    NOT NULL,
                price_usd   REAL    NOT NULL,
                notified_at TEXT    NOT NULL,
                FOREIGN KEY (appid) REFERENCES games(appid)
            );
        """)

        # Migration 1: source "ggdeals" was split into "ggdeals_retail" and
        # "ggdeals_keyshop". Remove any rows written under the old name.
        deleted_snapshots = conn.execute(
            "DELETE FROM price_snapshots WHERE source = 'ggdeals'"
        ).rowcount
        deleted_notifications = conn.execute(
            "DELETE FROM notifications WHERE source = 'ggdeals'"
        ).rowcount
        if deleted_snapshots or deleted_notifications:
            import logging
            logging.getLogger(__name__).info(
                "Migration: removed %d snapshot(s) and %d notification(s) with obsolete source 'ggdeals'.",
                deleted_snapshots, deleted_notifications,
            )



def upsert_game(appid: int, name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO games (appid, name, last_checked)
            VALUES (?, ?, ?)
            ON CONFLICT(appid) DO UPDATE SET name=excluded.name, last_checked=excluded.last_checked
            """,
            (appid, name, now),
        )


def save_snapshot(appid: int, source: str, price_usd: float, currency: str, store_url: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO price_snapshots (appid, source, price_usd, currency, store_url, captured_at) VALUES (?,?,?,?,?,?)",
            (appid, source, price_usd, currency, store_url, now),
        )


def get_price_stats(appid: int, source: str, history_days: int) -> dict | None:
    """Return min/avg/count for a game+source within the history window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=history_days)).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                MIN(price_usd) AS min_price,
                AVG(price_usd) AS avg_price,
                MAX(price_usd) AS max_price,
                COUNT(*)       AS snapshot_count
            FROM price_snapshots
            WHERE appid = ? AND source = ? AND captured_at >= ?
            """,
            (appid, source, cutoff),
        ).fetchone()
    if row and row["snapshot_count"] > 0:
        return dict(row)
    return None


def get_alltime_min(appid: int, source: str) -> float | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MIN(price_usd) AS min_price FROM price_snapshots WHERE appid=? AND source=?",
            (appid, source),
        ).fetchone()
    return row["min_price"] if row and row["min_price"] is not None else None


def was_recently_notified(appid: int, source: str, cooldown_hours: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM notifications WHERE appid=? AND source=? AND notified_at >= ? LIMIT 1",
            (appid, source, cutoff),
        ).fetchone()
    return row is not None


def log_notification(appid: int, source: str, price_usd: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO notifications (appid, source, price_usd, notified_at) VALUES (?,?,?,?)",
            (appid, source, price_usd, now),
        )
