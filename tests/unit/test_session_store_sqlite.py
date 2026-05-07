"""Unit tests for SQLiteSessionStore."""
import os
import tempfile

import pytest

from anbm.adapter.base import SessionNotFoundError
from anbm.engine.session_store_sqlite import SQLiteSessionStore


@pytest.fixture
async def store():
    """Create a SQLiteSessionStore backed by a temp file, then clean up."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    s = SQLiteSessionStore(tmp.name)
    yield s
    await s.close()
    os.unlink(tmp.name)


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(store):
    """create() 写入 SQLite，get() 读回，字段完整、类型正确。"""
    obj = await store.create("test_adapter", "1.0.0", "initial_state")
    sid = obj.session_id

    loaded = await store.get(sid)
    assert loaded.session_id == sid
    assert loaded.adapter_id == "test_adapter"
    assert loaded.adapter_version == "1.0.0"
    assert loaded.current_state == "initial_state"
    assert loaded.session_suspended is False
    assert loaded.state_history == ["initial_state"]
    assert loaded.cookie_data is None
    assert loaded.retry_stats["total_attempts"] == 0


@pytest.mark.asyncio
async def test_update_state_and_lock(store):
    """update_state 正确更新状态和历史；acquire/release_lock 非阻塞。"""
    obj = await store.create("demo", "0.1.0", "start")
    sid = obj.session_id

    # 获取锁
    acquired = await store.acquire_lock(sid)
    assert acquired is True

    # 同一 session 再次获取锁应失败
    acquired2 = await store.acquire_lock(sid)
    assert acquired2 is False

    # 更新状态
    await store.update_state(sid, "next_state")
    loaded = await store.get(sid)
    assert loaded.current_state == "next_state"
    assert loaded.state_history == ["start", "next_state"]

    # 释放锁
    await store.release_lock(sid)
    # 释放后可再次获取
    acquired3 = await store.acquire_lock(sid)
    assert acquired3 is True
    await store.release_lock(sid)


@pytest.mark.asyncio
async def test_cookie_data_save_restore(store):
    """update_cookie_data / get_cookie_data 正确持久化。"""
    obj = await store.create("test", "1.0.0", "start")
    sid = obj.session_id

    cookie_json = '{"cookies": [{"name": "sessionid", "value": "abc"}]}'
    await store.update_cookie_data(sid, cookie_json)

    loaded = await store.get(sid)
    assert loaded.cookie_data == cookie_json

    retrieved = await store.get_cookie_data(sid)
    assert retrieved == cookie_json

    # 未设置时返回 None
    obj2 = await store.create("test2", "1.0.0", "start")
    retrieved2 = await store.get_cookie_data(obj2.session_id)
    assert retrieved2 is None


@pytest.mark.asyncio
async def test_delete_raises_not_found(store):
    """delete 后 get 抛出 SessionNotFoundError。"""
    obj = await store.create("test", "1.0.0", "start")
    sid = obj.session_id

    await store.delete(sid)

    with pytest.raises(SessionNotFoundError) as exc:
        await store.get(sid)
    assert exc.value.session_id == sid
