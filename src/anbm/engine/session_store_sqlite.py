import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import aiosqlite

from anbm.adapter.base import SessionNotFoundError

logger = logging.getLogger(__name__)

SQL_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    adapter_id        TEXT NOT NULL,
    adapter_version   TEXT NOT NULL,
    current_state     TEXT NOT NULL,
    session_suspended INTEGER NOT NULL DEFAULT 0,
    state_history     TEXT NOT NULL DEFAULT '[]',
    retry_stats       TEXT NOT NULL DEFAULT '{}',
    cookie_data       TEXT,
    created_at        TEXT NOT NULL,
    last_action_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_locks (
    session_id TEXT PRIMARY KEY,
    locked     INTEGER NOT NULL DEFAULT 0
);
"""


class SQLiteSessionStore:
    """
    SQLite 后端 SessionStore。
    接口与 SessionStore（内存）一致，可被 FSMEngine 互换使用。
    asyncio.Lock 在内存中管理并发，SQLite locked 字段仅用于 observability。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._locks: dict[str, asyncio.Lock] = {}

    async def _ensure_conn(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(SQL_CREATE_TABLES)
            await self._conn.commit()

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def create(self, adapter_id: str, adapter_version: str, initial_state: str) -> SimpleNamespace:
        await self._ensure_conn()
        session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        state_history = json.dumps([initial_state])
        retry_stats = json.dumps({
            "total_attempts": 0,
            "successful_retries": 0,
            "state_changed_interrupts": 0,
            "fallback_count": 0,
        })
        await self._conn.execute(
            """INSERT INTO sessions
               (session_id, adapter_id, adapter_version, current_state,
                session_suspended, state_history, retry_stats, cookie_data,
                created_at, last_action_at)
               VALUES (?, ?, ?, ?, 0, ?, ?, NULL, ?, ?)""",
            (session_id, adapter_id, adapter_version, initial_state,
             state_history, retry_stats, now, now),
        )
        await self._conn.commit()
        logger.info(f"Session created (SQLite): {session_id} [{adapter_id}] -> {initial_state}")
        return SimpleNamespace(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            current_state=initial_state,
            session_suspended=False,
            cookie_data=None,
            state_history=[initial_state],
            retry_stats={
                "total_attempts": 0,
                "successful_retries": 0,
                "state_changed_interrupts": 0,
                "fallback_count": 0,
            },
            created_at=now,
            last_action_at=now,
        )

    async def get(self, session_id: str) -> SimpleNamespace:
        await self._ensure_conn()
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        return self._row_to_obj(row)

    async def acquire_lock(self, session_id: str) -> bool:
        await self._ensure_conn()
        lock = self._get_lock(session_id)
        # 非阻塞尝试获取锁
        if lock.locked():
            return False
        await lock.acquire()
        # SQLite 标记仅用于 observability
        await self._conn.execute(
            "INSERT OR REPLACE INTO session_locks (session_id, locked) VALUES (?, 1)",
            (session_id,),
        )
        await self._conn.commit()
        return True

    async def release_lock(self, session_id: str):
        lock = self._get_lock(session_id)
        if lock.locked():
            lock.release()
        if self._conn is not None:
            await self._conn.execute(
                "INSERT OR REPLACE INTO session_locks (session_id, locked) VALUES (?, 0)",
                (session_id,),
            )
            await self._conn.commit()

    async def update_state(self, session_id: str, new_state: str):
        await self._ensure_conn()
        row = await self.get(session_id)
        history = row.state_history if isinstance(row.state_history, list) else json.loads(row.state_history)
        # 去重
        if not history or history[-1] != new_state:
            history.append(new_state)
        # 截断
        if len(history) > 50:
            history = history[-50:]
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET current_state = ?, state_history = ?, last_action_at = ? WHERE session_id = ?",
            (new_state, json.dumps(history), now, session_id),
        )
        await self._conn.commit()
        logger.info(f"Session {session_id} state -> {new_state}")

    async def suspend(self, session_id: str):
        await self._ensure_conn()
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET session_suspended = 1, last_action_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        await self._conn.commit()

    async def resume(self, session_id: str):
        await self._ensure_conn()
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET session_suspended = 0, last_action_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        await self._conn.commit()

    async def _update_retry_stats(self, session_id: str, key: str):
        row = await self.get(session_id)
        stats = row.retry_stats if isinstance(row.retry_stats, dict) else json.loads(row.retry_stats)
        stats[key] += 1
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET retry_stats = ?, last_action_at = ? WHERE session_id = ?",
            (json.dumps(stats), now, session_id),
        )
        await self._conn.commit()

    async def record_retry(self, session_id: str, succeeded: bool):
        row = await self.get(session_id)
        stats = row.retry_stats if isinstance(row.retry_stats, dict) else json.loads(row.retry_stats)
        stats["total_attempts"] += 1
        if succeeded:
            stats["successful_retries"] += 1
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET retry_stats = ?, last_action_at = ? WHERE session_id = ?",
            (json.dumps(stats), now, session_id),
        )
        await self._conn.commit()

    async def record_state_change_interrupt(self, session_id: str):
        await self._update_retry_stats(session_id, "state_changed_interrupts")

    async def record_fallback(self, session_id: str):
        await self._update_retry_stats(session_id, "fallback_count")

    async def update_cookie_data(self, session_id: str, cookie_data: str):
        await self._ensure_conn()
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE sessions SET cookie_data = ?, last_action_at = ? WHERE session_id = ?",
            (cookie_data, now, session_id),
        )
        await self._conn.commit()

    async def get_cookie_data(self, session_id: str) -> str | None:
        row = await self.get(session_id)
        return row.cookie_data

    async def get_idle_sessions(self, max_idle_seconds: int) -> list[str]:
        await self._ensure_conn()
        now = datetime.now(timezone.utc)
        idle = []
        cursor = await self._conn.execute("SELECT session_id, last_action_at FROM sessions")
        rows = await cursor.fetchall()
        for row in rows:
            # Skip sessions with active lock
            lock_cursor = await self._conn.execute(
                "SELECT locked FROM session_locks WHERE session_id = ?", (row["session_id"],)
            )
            lock_row = await lock_cursor.fetchone()
            if lock_row and lock_row["locked"]:
                continue
            last_action = datetime.fromisoformat(row["last_action_at"])
            elapsed = (now - last_action).total_seconds()
            if elapsed > max_idle_seconds:
                idle.append(row["session_id"])
        return idle

    async def delete(self, session_id: str):
        await self._ensure_conn()
        await self.get(session_id)  # ensure exists
        await self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self._conn.execute("DELETE FROM session_locks WHERE session_id = ?", (session_id,))
        await self._conn.commit()
        self._locks.pop(session_id, None)
        logger.info(f"Session deleted (SQLite): {session_id}")

    async def close(self):
        """关闭数据库连接。"""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_obj(row: aiosqlite.Row) -> SimpleNamespace:
        return SimpleNamespace(
            session_id=row["session_id"],
            adapter_id=row["adapter_id"],
            adapter_version=row["adapter_version"],
            current_state=row["current_state"],
            session_suspended=bool(row["session_suspended"]),
            state_history=json.loads(row["state_history"]) if isinstance(row["state_history"], str) else row["state_history"],
            retry_stats=json.loads(row["retry_stats"]) if isinstance(row["retry_stats"], str) else row["retry_stats"],
            cookie_data=row["cookie_data"],
            created_at=row["created_at"],
            last_action_at=row["last_action_at"],
        )
