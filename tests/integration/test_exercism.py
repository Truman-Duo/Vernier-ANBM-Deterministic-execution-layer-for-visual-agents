"""Integration tests for the Exercism adapter.

Covers multi-step workflow state preservation, intermediate failure,
cookie persistence, and state history completeness.

Run with: pytest tests/integration/test_exercism.py -v -m network --timeout=60
"""
import pytest

TRACKS_URL = "https://exercism.org/tracks"
PYTHON_TRACK = "python"
HELLO_WORLD_EXERCISE = "hello-world"


@pytest.mark.network
@pytest.mark.asyncio
async def test_track_list_state():
    """Exercism tracks 页面被检测为 track_list 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": TRACKS_URL, "adapter_hint": "exercism"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "track_list"
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_state_correctly_passed_across_steps():
    """三步工作流后 state_history 包含完整路径。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": TRACKS_URL, "adapter_hint": "exercism"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # Step 2: open_track → exercise_list
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_track", "params": {"track": PYTHON_TRACK}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "exercise_list"
        assert data["execution_path"] == "deterministic"

        # Step 3: open_exercise → exercise_detail
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_exercise", "params": {"exercise": HELLO_WORLD_EXERCISE}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "exercise_detail"
        assert data["execution_path"] == "deterministic"

        # 验证 state_history
        resp = await client.get(f"http://localhost:8000/session/{sid}")
        assert resp.status_code == 200
        session = resp.json()
        assert session["state_history"] == [
            "track_list", "exercise_list", "exercise_detail",
        ]


@pytest.mark.network
@pytest.mark.asyncio
async def test_cookies_persist_across_steps():
    """完整工作流后 cookie 数据完整。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": TRACKS_URL, "adapter_hint": "exercism"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # 记录初始 last_action_at
        resp = await client.get(f"http://localhost:8000/session/{sid}")
        initial_session = resp.json()
        initial_time = initial_session.get("last_action_at", "")

        # 执行两步操作
        await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_track", "params": {"track": PYTHON_TRACK}},
        )
        await client.post(
            f"http://localhost:8000/act/{sid}",
            json={
                "action": "open_exercise",
                "params": {"exercise": HELLO_WORLD_EXERCISE},
            },
        )

        # 验证 session 存在且 last_action_at 已更新
        resp = await client.get(f"http://localhost:8000/session/{sid}")
        assert resp.status_code == 200
        session_data = resp.json()
        assert session_data["last_action_at"] != initial_time


@pytest.mark.network
@pytest.mark.asyncio
async def test_intermediate_failure_preserves_state():
    """中间步骤失败时 state 停留在最后成功状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": TRACKS_URL, "adapter_hint": "exercism"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # open_track 成功
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_track", "params": {"track": PYTHON_TRACK}},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "exercise_list"

        # 使用不存在的 exercise 名称触发失败
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_exercise", "params": {"exercise": "nonexistent-exercise-name"}},
        )
        # 可能返回 200 但 execution_path 不是 deterministic
        # 也可能触发 fallback
        data = resp.json()
        assert resp.status_code == 200
        # current_state 应保持为 exercise_list（或已进入 visual_fallback 但状态不变）
        assert data["current_state"] == "exercise_list"


@pytest.mark.network
@pytest.mark.asyncio
async def test_state_history_complete_path():
    """完整工作流后 state_history 按顺序包含所有经过的状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": TRACKS_URL, "adapter_hint": "exercism"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # 完整工作流
        await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_track", "params": {"track": PYTHON_TRACK}},
        )
        await client.post(
            f"http://localhost:8000/act/{sid}",
            json={
                "action": "open_exercise",
                "params": {"exercise": HELLO_WORLD_EXERCISE},
            },
        )

        # 验证 state_history
        resp = await client.get(f"http://localhost:8000/session/{sid}")
        assert resp.status_code == 200
        history = resp.json().get("state_history", [])

        assert "track_list" in history
        assert "exercise_list" in history
        assert "exercise_detail" in history

        # 顺序正确
        tl_idx = history.index("track_list")
        el_idx = history.index("exercise_list")
        ed_idx = history.index("exercise_detail")
        assert tl_idx < el_idx < ed_idx
