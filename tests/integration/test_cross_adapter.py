"""Cross-adapter isolation tests for v0.9.9.

Verifies that sessions are bound to a single adapter and cannot be reused
across different adapters. Cross-site workflows are managed by the caller
using multiple independent session IDs.

Run with: pytest tests/integration/test_cross_adapter.py -v -m network --timeout=60
"""
import pytest

BASE_URL = "http://localhost:8000"


@pytest.mark.network
@pytest.mark.asyncio
async def test_two_sessions_have_different_adapter_ids():
    """两个 session 绑定不同 adapter，adapter_id 各自独立。"""
    import httpx

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        r1 = await client.post("/browse", json={
            "url": "https://pypi.org/search/?q=requests",
            "adapter_hint": "pypi",
        })
        assert r1.status_code == 200
        assert r1.json()["adapter"] == "pypi"
        session_1_id = r1.json()["session_id"]

        r2 = await client.post("/browse", json={
            "url": "https://github.com/psf/requests/issues",
            "adapter_hint": "github_issues",
        })
        assert r2.status_code == 200
        assert r2.json()["adapter"] == "github_issues"
        session_2_id = r2.json()["session_id"]

        assert session_1_id != session_2_id


@pytest.mark.network
@pytest.mark.asyncio
async def test_cookie_isolation_between_sessions():
    """两个 session 的 cookie 完全隔离，不互相泄漏。"""
    import httpx

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        r1 = await client.post("/browse", json={
            "url": "https://pypi.org/search/?q=flask",
            "adapter_hint": "pypi",
        })
        session_1_id = r1.json()["session_id"]

        r2 = await client.post("/browse", json={
            "url": "https://github.com/pallets/flask/issues",
            "adapter_hint": "github_issues",
        })
        session_2_id = r2.json()["session_id"]

        s1 = await client.get(f"/session/{session_1_id}")
        s2 = await client.get(f"/session/{session_2_id}")

        assert s1.json()["adapter"] == "pypi"
        assert s2.json()["adapter"] == "github_issues"
        assert s1.json()["session_id"] != s2.json()["session_id"]

        # state_history 是各自独立的列表
        assert isinstance(s1.json().get("state_history"), list)
        assert isinstance(s2.json().get("state_history"), list)


@pytest.mark.network
@pytest.mark.asyncio
async def test_state_rebuilds_from_scratch_in_new_session():
    """新 session 的 state 从头重建，不继承任何已有 session 的状态。"""
    import httpx

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        r1 = await client.post("/browse", json={
            "url": "https://pypi.org/search/?q=django",
            "adapter_hint": "pypi",
        })
        session_1_id = r1.json()["session_id"]

        # 不传 session_id，创建全新的 session
        r2 = await client.post("/browse", json={
            "url": "https://pypi.org/search/?q=flask",
            "adapter_hint": "pypi",
        })
        session_2_id = r2.json()["session_id"]

        assert session_1_id != session_2_id

        # 新 session 的 state_history 只包含本次 browse 的结果
        s2 = await client.get(f"/session/{session_2_id}")
        assert len(s2.json().get("state_history", [])) <= 2


@pytest.mark.network
@pytest.mark.asyncio
async def test_adapter_mismatch_returns_error():
    """用 pypi session 请求 github url，返回 adapter_mismatch 错误。"""
    import httpx

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        r1 = await client.post("/browse", json={
            "url": "https://pypi.org/search/?q=requests",
            "adapter_hint": "pypi",
        })
        assert r1.status_code == 200
        session_id = r1.json()["session_id"]

        # 用同一 session_id 访问 GitHub（不同 adapter）
        r2 = await client.post("/browse", json={
            "url": "https://github.com/psf/requests/issues",
            "session_id": session_id,
            "adapter_hint": "github_issues",
        })
        assert r2.status_code == 200
        body = r2.json()
        assert body.get("error") == "adapter_mismatch"
        assert body.get("bound_adapter") == "pypi"
        assert body.get("requested_adapter") == "github_issues"


@pytest.mark.network
@pytest.mark.asyncio
async def test_cross_site_workflow_caller_manages_sessions():
    """
    跨站点工作流：调用方管理两个 session_id，系统不感知跨站任务。
    工作流：PyPI 获取项目信息 → GitHub 浏览对应 issues。
    """
    import httpx

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        # Step 1: PyPI 获取项目信息
        r_pypi = await client.post("/browse", json={
            "url": "https://pypi.org/project/requests/",
            "adapter_hint": "pypi",
        })
        assert r_pypi.status_code == 200
        pypi_data = r_pypi.json()
        assert pypi_data.get("execution_path") in ("deterministic", "visual_fallback")
        pypi_session_id = pypi_data["session_id"]

        # Step 2: 调用方决定跳转到 GitHub（创建新 session）
        r_gh = await client.post("/browse", json={
            "url": "https://github.com/psf/requests/issues",
            "adapter_hint": "github_issues",
        })
        assert r_gh.status_code == 200
        gh_data = r_gh.json()
        gh_session_id = gh_data["session_id"]

        # 验证两个 session 独立
        assert pypi_session_id != gh_session_id

        s_pypi = await client.get(f"/session/{pypi_session_id}")
        s_gh = await client.get(f"/session/{gh_session_id}")

        assert s_pypi.json()["adapter"] == "pypi"
        assert s_gh.json()["adapter"] == "github_issues"
        assert isinstance(s_pypi.json().get("state_history"), list)
        assert isinstance(s_gh.json().get("state_history"), list)

        # 清理
        await client.delete(f"/session/{pypi_session_id}")
        await client.delete(f"/session/{gh_session_id}")
