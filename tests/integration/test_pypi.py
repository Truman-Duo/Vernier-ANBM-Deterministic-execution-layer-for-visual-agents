"""Integration tests for the PyPI adapter.

These tests require a running server on port 8000 and real pypi.org access.
Run with: pytest tests/integration/test_pypi.py -v -m network --timeout=60
"""
import pytest

PYPI_SEARCH_URL = "https://pypi.org/search/?q=requests"
PYPI_PROJECT_URL = "https://pypi.org/project/requests/"


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_triggers_project_list_state():
    """搜索操作触发 project_list 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PYPI_SEARCH_URL, "adapter_hint": "pypi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "project_list"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_filter_version_does_not_change_state():
    """核心测试：filter_version 只改变 URL 参数，FSM 状态保持 project_list。

    URL query 参数变化不构成状态变化，页面语义结构未变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PYPI_SEARCH_URL, "adapter_hint": "pypi"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "filter_version", "params": {"query": "flask"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "project_list"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_open_project_detail():
    """打开项目详情页，状态跳转到 project_detail。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PYPI_SEARCH_URL, "adapter_hint": "pypi"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_project", "params": {"name": "requests"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "project_detail"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_paginate_keeps_state():
    """翻页保持 project_list 状态。

    页码变化不改变页面语义结构，FSM 不应认为状态改变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PYPI_SEARCH_URL, "adapter_hint": "pypi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {"direction": "next"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "project_list"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {"direction": "previous"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "project_list"
        assert data["session_suspended"] is False


@pytest.mark.network
@pytest.mark.asyncio
async def test_project_detail_extraction():
    """项目详情页提取 name/version/summary/license 等字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PYPI_PROJECT_URL, "adapter_hint": "pypi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "project_detail"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": PYPI_PROJECT_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        assert len(extracted.get("name", "")) > 0
        assert len(extracted.get("version", "")) > 0
        assert isinstance(extracted.get("summary"), str)
        assert isinstance(extracted.get("github_url"), str)
        assert isinstance(extracted.get("license"), str)
        assert isinstance(extracted.get("requires_python"), str)
