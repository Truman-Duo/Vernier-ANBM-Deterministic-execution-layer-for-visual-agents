import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from anbm.adapter.base import SessionNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """单站点执行上下文。

    Session 语义边界（invariant，不得修改）：
    - 一个 session 只属于一个 adapter（session.adapter_id 在生命周期内不变）
    - 跨站点任务由调用方（Agent）管理多个 session_id，ANBM 不提供跨 session 协调
    - session 的 cookie_data 只对应创建时的 adapter 所在域名，不跨域
    - state_history 只记录本 session 内的状态迁移，不跨 session 合并
    """
    session_id: str
    adapter_id: str
    adapter_version: str
    current_state: str
    session_suspended: bool = False
    cookies_path: str | None = None
    cookie_data: str | None = None
    _fingerprint_cache: dict = field(default_factory=dict, repr=False)
    state_history: list[str] = field(default_factory=list)
    retry_stats: dict = field(default_factory=lambda: {
        "total_attempts": 0,
        "successful_retries": 0,
        "state_changed_interrupts": 0,
        "fallback_count": 0,
    })
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_action_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def touch(self):
        self.last_action_at = datetime.now(timezone.utc)


class SessionStore:
    """
    第一阶段：内存存储。
    每个 session 内部维护一个 asyncio.Lock 用于串行化执行流。
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    async def create(self, adapter_id: str, adapter_version: str, initial_state: str) -> Session:
        session = Session(
            session_id=str(uuid4()),
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            current_state=initial_state,
            state_history=[initial_state],
        )
        self._sessions[session.session_id] = session
        logger.info(f"Session created: {session.session_id} [{adapter_id}] -> {initial_state}")
        return session

    async def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def acquire_lock(self, session_id: str) -> bool:
        """尝试获取执行锁，非阻塞。返回 True 表示获得锁。"""
        session = await self.get(session_id)
        if session._lock.locked():
            return False
        await session._lock.acquire()
        return True

    async def release_lock(self, session_id: str):
        session = await self.get(session_id)
        if session._lock.locked():
            session._lock.release()

    async def update_state(self, session_id: str, new_state: str):
        session = await self.get(session_id)
        session.current_state = new_state
        # 去重：连续相同状态不重复追加
        if not session.state_history or session.state_history[-1] != new_state:
            session.state_history.append(new_state)
        # 截断：最多保留 50 条
        if len(session.state_history) > 50:
            session.state_history = session.state_history[-50:]
        session.touch()
        logger.info(f"Session {session_id} state -> {new_state}")

    async def suspend(self, session_id: str):
        session = await self.get(session_id)
        session.session_suspended = True
        session.touch()

    async def resume(self, session_id: str):
        session = await self.get(session_id)
        session.session_suspended = False
        session.touch()

    async def record_retry(self, session_id: str, succeeded: bool):
        session = await self.get(session_id)
        session.retry_stats["total_attempts"] += 1
        if succeeded:
            session.retry_stats["successful_retries"] += 1
        session.touch()

    async def record_state_change_interrupt(self, session_id: str):
        session = await self.get(session_id)
        session.retry_stats["state_changed_interrupts"] += 1
        session.touch()

    async def record_fallback(self, session_id: str):
        session = await self.get(session_id)
        session.retry_stats["fallback_count"] += 1
        session.touch()

    async def update_cookie_data(self, session_id: str, cookie_data: str):
        session = await self.get(session_id)
        session.cookie_data = cookie_data
        session.touch()

    async def get_cookie_data(self, session_id: str) -> str | None:
        session = await self.get(session_id)
        return session.cookie_data

    async def get_idle_sessions(self, max_idle_seconds: int) -> list[str]:
        now = datetime.now(timezone.utc)
        idle = []
        for session_id, session in list(self._sessions.items()):
            if session._lock.locked():
                continue
            elapsed = (now - session.last_action_at).total_seconds()
            if elapsed > max_idle_seconds:
                idle.append(session_id)
        return idle

    async def delete(self, session_id: str):
        await self.get(session_id)  # 确保存在
        del self._sessions[session_id]
        logger.info(f"Session deleted: {session_id}")

    async def get_fingerprint_cache(self, session_id: str) -> dict:
        session = await self.get(session_id)
        return session._fingerprint_cache

    async def clear_fingerprint_cache(self, session_id: str):
        session = await self.get(session_id)
        session._fingerprint_cache.clear()

    async def clear_all_fingerprints_for_adapter(self, adapter_id: str):
        """清除指定 adapter 所有 session 的 fingerprint 缓存。"""
        for sid, s in list(self._sessions.items()):
            if s.adapter_id == adapter_id:
                s._fingerprint_cache.clear()
