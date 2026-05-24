"""SQLite-backed aiogram 3 FSM storage — persists state across bot restarts."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import aiosqlite
from aiogram.fsm.storage.base import BaseStorage, StorageKey

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS fsm (
    bot_id  INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    destiny TEXT    NOT NULL,
    state   TEXT,
    data    TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (bot_id, chat_id, user_id, destiny)
)
"""


class SqliteStorage(BaseStorage):
    """
    Single-file SQLite FSM storage for aiogram 3.
    One persistent connection; directory is created on first use.
    """

    def __init__(self, db_path: str) -> None:
        self._path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None

    async def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self._path)
            await self._db.execute(_CREATE_TABLE)
            await self._db.commit()
        return self._db

    def _k(self, key: StorageKey) -> tuple:
        return (key.bot_id, key.chat_id, key.user_id, key.destiny)

    async def set_state(
        self, key: StorageKey, state: Optional[str] = None
    ) -> None:
        db = await self._conn()
        await db.execute(
            """
            INSERT INTO fsm (bot_id, chat_id, user_id, destiny, state)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bot_id, chat_id, user_id, destiny)
            DO UPDATE SET state = excluded.state
            """,
            (*self._k(key), str(state) if state is not None else None),
        )
        await db.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        db = await self._conn()
        async with db.execute(
            "SELECT state FROM fsm"
            " WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?",
            self._k(key),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_data(
        self, key: StorageKey, data: Dict[str, Any]
    ) -> None:
        db = await self._conn()
        await db.execute(
            """
            INSERT INTO fsm (bot_id, chat_id, user_id, destiny, data)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bot_id, chat_id, user_id, destiny)
            DO UPDATE SET data = excluded.data
            """,
            (*self._k(key), json.dumps(data, ensure_ascii=False)),
        )
        await db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        db = await self._conn()
        async with db.execute(
            "SELECT data FROM fsm"
            " WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?",
            self._k(key),
        ) as cur:
            row = await cur.fetchone()
        if row is None or not row[0]:
            return {}
        return json.loads(row[0])

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
