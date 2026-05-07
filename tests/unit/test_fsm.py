from unittest.mock import AsyncMock, MagicMock

import pytest

from anbm.adapter.base import SessionNotFoundError
from anbm.engine.session_store import SessionStore


@pytest.fixture
def store():
    return SessionStore()


@pytest.mark.asyncio
async def test_session_create_and_get(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")
    assert session.session_id is not None
    assert session.adapter_id == "douban_movie"
    assert session.current_state == "movie_list"
    assert session.state_history == ["movie_list"]

    fetched = await store.get(session.session_id)
    assert fetched == session


@pytest.mark.asyncio
async def test_session_not_found(store):
    with pytest.raises(SessionNotFoundError):
        await store.get("non-existent")


@pytest.mark.asyncio
async def test_session_update_state(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")
    await store.update_state(session.session_id, "movie_detail")
    assert session.current_state == "movie_detail"
    assert session.state_history == ["movie_list", "movie_detail"]


@pytest.mark.asyncio
async def test_session_suspend_resume(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")
    assert session.session_suspended is False

    await store.suspend(session.session_id)
    assert session.session_suspended is True

    await store.resume(session.session_id)
    assert session.session_suspended is False


@pytest.mark.asyncio
async def test_retry_stats_recording(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")

    await store.record_retry(session.session_id, succeeded=True)
    assert session.retry_stats["total_attempts"] == 1
    assert session.retry_stats["successful_retries"] == 1

    await store.record_retry(session.session_id, succeeded=False)
    assert session.retry_stats["total_attempts"] == 2
    assert session.retry_stats["successful_retries"] == 1

    await store.record_state_change_interrupt(session.session_id)
    assert session.retry_stats["state_changed_interrupts"] == 1

    await store.record_fallback(session.session_id)
    assert session.retry_stats["fallback_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_lock(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")

    acquired1 = await store.acquire_lock(session.session_id)
    assert acquired1 is True

    # Second acquire should fail (non-blocking)
    acquired2 = await store.acquire_lock(session.session_id)
    assert acquired2 is False

    await store.release_lock(session.session_id)

    acquired3 = await store.acquire_lock(session.session_id)
    assert acquired3 is True
    await store.release_lock(session.session_id)


@pytest.mark.asyncio
async def test_lock_released_on_exception(store):
    """非预期异常时 session lock 仍被释放（模拟 FSMEngine.act() 的 try/finally 模式）。"""
    session = await store.create("test_adapter", "1.0.0", "start")

    acquired = await store.acquire_lock(session.session_id)
    assert acquired is True
    assert session._lock.locked() is True

    try:
        raise ValueError("模拟 execute_act 非预期异常")
    except ValueError:
        pass  # 异常被上层捕获
    finally:
        await store.release_lock(session.session_id)

    assert session._lock.locked() is False

    # 应能重新获取锁
    reacquired = await store.acquire_lock(session.session_id)
    assert reacquired is True
    await store.release_lock(session.session_id)


@pytest.mark.asyncio
async def test_session_delete(store):
    session = await store.create("douban_movie", "1.0.0", "movie_list")
    await store.delete(session.session_id)

    with pytest.raises(SessionNotFoundError):
        await store.get(session.session_id)


@pytest.mark.asyncio
async def test_state_history_deduplication(store):
    """连续 3 次相同状态转换，history 只记录 1 条。"""
    session = await store.create("douban_movie", "1.0.0", "start")
    assert session.state_history == ["start"]

    await store.update_state(session.session_id, "same")
    assert session.state_history == ["start", "same"]

    await store.update_state(session.session_id, "same")
    assert session.state_history == ["start", "same"]

    await store.update_state(session.session_id, "same")
    assert session.state_history == ["start", "same"]


@pytest.mark.asyncio
async def test_state_history_max_length(store):
    """触发 51 次不同状态变更，history 长度不超过 50。"""
    session = await store.create("douban_movie", "1.0.0", "s0")
    for i in range(1, 52):
        await store.update_state(session.session_id, f"s{i}")

    assert len(session.state_history) == 50
    assert session.state_history[0] == "s2"
    assert session.state_history[-1] == "s51"


@pytest.mark.asyncio
async def test_act_failure_preserves_last_successful_state():
    """三步工作流中第三步失败时，state 停留在第二步成功后的状态。"""
    import asyncio

    from anbm.engine.fsm import FSMEngine

    engine = FSMEngine(reaper_interval=999999)

    try:
        # Mock browser
        engine.browser = AsyncMock()
        engine.browser.get_page.return_value = AsyncMock()
        engine.browser.save_cookies_to_store = AsyncMock()
        engine.browser.restore_cookies_from_store = AsyncMock()

        # Mock adapter loader
        engine.adapter_loader.load_manifest = MagicMock(return_value={
            "states": {
                "track_list": {"allowed_actions": ["open_track"]},
                "exercise_list": {"allowed_actions": ["open_exercise"]},
                "exercise_detail": {"allowed_actions": ["extract_content"]},
            },
            "transitions": {
                "track_list": {"open_track": "exercise_list"},
                "exercise_list": {"open_exercise": "exercise_detail"},
                "exercise_detail": {"extract_content": "exercise_detail"},
            },
            "action_idempotency": {
                "open_track": True, "open_exercise": True, "extract_content": True,
            },
        })
        engine.adapter_loader.load_handler = MagicMock()

        # Mock validator
        engine.validator.check_action_allowed = MagicMock(return_value=True)
        engine.validator.get_idempotency = MagicMock(return_value=True)
        engine.validator.validate_transition = AsyncMock(return_value=True)

        # Mock router
        engine.router.execute_act = AsyncMock()

        session = await engine.session_store.create("exercism", "1.0.0", "track_list")
        sid = session.session_id

        # Step 1: open_track succeeds → exercise_list
        engine.router.execute_act.return_value = {
            "execution_path": "deterministic",
            "success": True,
            "next_state": "exercise_list",
            "retry": {"attempts": 1, "succeeded": True},
            "session_suspended": False,
        }
        await engine.act(sid, "open_track")
        assert session.current_state == "exercise_list"

        # Step 2: open_exercise succeeds → exercise_detail
        engine.router.execute_act.return_value = {
            "execution_path": "deterministic",
            "success": True,
            "next_state": "exercise_detail",
            "retry": {"attempts": 1, "succeeded": True},
            "session_suspended": False,
        }
        await engine.act(sid, "open_exercise")
        assert session.current_state == "exercise_detail"
        assert session.state_history == [
            "track_list", "exercise_list", "exercise_detail",
        ]

        # Step 3: extract_content raises RuntimeError
        engine.router.execute_act.side_effect = RuntimeError("模拟非预期异常")
        with pytest.raises(RuntimeError):
            await engine.act(sid, "extract_content")

        # State unchanged from last success
        assert session.current_state == "exercise_detail"
        assert session.state_history == [
            "track_list", "exercise_list", "exercise_detail",
        ]

        # Lock released
        assert session._lock.locked() is False

    finally:
        engine._reaper_task.cancel()
        try:
            await engine._reaper_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_fingerprint_cache_cleared_on_state_transition():
    """状态跳转时 clear_fingerprint_cache 被调用，同状态操作不调用。"""
    import asyncio

    from anbm.engine.fsm import FSMEngine

    engine = FSMEngine(reaper_interval=999999)

    try:
        engine.browser = AsyncMock()
        engine.browser.get_page.return_value = AsyncMock()
        engine.browser.save_cookies_to_store = AsyncMock()
        engine.browser.restore_cookies_from_store = AsyncMock()

        engine.adapter_loader.load_manifest = MagicMock(return_value={
            "states": {
                "page_a": {"allowed_actions": ["go_to_b", "stay"]},
                "page_b": {"allowed_actions": ["go_to_a"]},
            },
            "transitions": {
                "page_a": {"go_to_b": "page_b", "stay": "page_a"},
            },
            "action_idempotency": {"go_to_b": True, "stay": True},
        })
        engine.adapter_loader.load_handler = MagicMock()

        engine.validator.check_action_allowed = MagicMock(return_value=True)
        engine.validator.get_idempotency = MagicMock(return_value=True)
        engine.validator.validate_transition = AsyncMock(return_value=True)

        engine.router.execute_act = AsyncMock()

        # Spy on clear_fingerprint_cache
        engine.session_store.clear_fingerprint_cache = AsyncMock()

        session = await engine.session_store.create("test", "1.0.0", "page_a")
        sid = session.session_id

        # Test 1: next_state != current_state → cache cleared
        engine.router.execute_act.return_value = {
            "execution_path": "deterministic",
            "success": True,
            "next_state": "page_b",
            "retry": {"attempts": 1, "succeeded": True},
            "session_suspended": False,
        }
        await engine.act(sid, "go_to_b")
        engine.session_store.clear_fingerprint_cache.assert_awaited_once_with(sid)

        # Test 2: next_state == current_state (stay) → cache NOT cleared
        engine.session_store.clear_fingerprint_cache.reset_mock()
        engine.router.execute_act.return_value = {
            "execution_path": "deterministic",
            "success": True,
            "next_state": "page_b",
            "retry": {"attempts": 1, "succeeded": True},
            "session_suspended": False,
        }
        await engine.act(sid, "stay")
        engine.session_store.clear_fingerprint_cache.assert_not_called()

    finally:
        engine._reaper_task.cancel()
        try:
            await engine._reaper_task
        except BaseException:
            pass
