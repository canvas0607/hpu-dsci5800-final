from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path("data/furniture_assistant.sqlite3")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                user_request TEXT NOT NULL,
                summary TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(uid) REFERENCES users(uid)
            )
            """
        )
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_user() -> str:
    init_db()
    uid = uuid.uuid4().hex
    with connect() as conn:
        conn.execute("INSERT INTO users (uid) VALUES (?)", (uid,))
        conn.commit()
    return uid


def ensure_user(uid: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        conn.commit()


def get_preferences(uid: str) -> dict[str, Any]:
    ensure_user(uid)
    with connect() as conn:
        row = conn.execute(
            "SELECT preferences_json FROM users WHERE uid = ?", (uid,)
        ).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["preferences_json"])
    except json.JSONDecodeError:
        return {}


def update_preferences(uid: str, preferences: dict[str, Any]) -> None:
    ensure_user(uid)
    with connect() as conn:
        conn.execute(
            "UPDATE users SET preferences_json = ? WHERE uid = ?",
            (json.dumps(preferences, ensure_ascii=False), uid),
        )
        conn.commit()


def add_history(uid: str, user_request: str, summary: str, total: float) -> None:
    ensure_user(uid)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO recommendation_history (uid, user_request, summary, total)
            VALUES (?, ?, ?, ?)
            """,
            (uid, user_request, summary, total),
        )
        conn.commit()


def get_history(uid: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_user(uid)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, uid, user_request, summary, total, created_at
            FROM recommendation_history
            WHERE uid = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (uid, limit),
        ).fetchall()
    return [dict(row) for row in rows]
