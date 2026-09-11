"""SQLite-backed chat history."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    message_id INTEGER,
    user_id    INTEGER,
    name       TEXT,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id);
"""


@dataclass(frozen=True)
class HistoryItem:
    role: str          # "user" | "assistant"
    name: str          # display name of the author ("" for the bot)
    text: str


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def add_message(
        self,
        *,
        chat_id: int,
        role: str,
        text: str,
        message_id: int | None = None,
        user_id: int | None = None,
        name: str = "",
    ) -> None:
        await self.conn.execute(
            "INSERT INTO messages (chat_id, message_id, user_id, name, role, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, message_id, user_id, name, role, text, time.time()),
        )
        await self.conn.commit()

    async def get_history(
        self, chat_id: int, limit: int, max_chars: int
    ) -> list[HistoryItem]:
        """Return the last messages of a chat, oldest first, trimmed to max_chars."""
        cursor = await self.conn.execute(
            "SELECT role, name, text FROM messages WHERE chat_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        items: list[HistoryItem] = []
        total = 0
        for row in rows:  # newest first: stop as soon as the budget is spent
            text = row["text"] or ""
            total += len(text)
            if total > max_chars and items:
                break
            items.append(HistoryItem(role=row["role"], name=row["name"] or "", text=text))
        items.reverse()
        return items

    async def clear_history(self, chat_id: int) -> int:
        cursor = await self.conn.execute(
            "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
        )
        await self.conn.commit()
        return cursor.rowcount or 0

    async def count(self, chat_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row["n"]) if row else 0
