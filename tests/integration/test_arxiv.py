"""Integration tests for the arXiv adapter.

These tests require a running server on port 8000 and real arxiv.org access.
Run with: pytest tests/integration/test_arxiv.py -v -m network --timeout=60
"""
import pytest

ARXIV_BASE = "https://arxiv.org"
ARXIV_SEARCH_URL = "https://arxiv.org/search/?query=transformer&searchtype=all"
ARXIV_PAPER_URL = "https://arxiv.org/abs/2401.00001"


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_triggers_state_transition():
    """搜索操作触发状态跳转：home → search_results。"""
    import httpx

    async with httpx.AsyncClient() as client:
        # Browse to arxiv home
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": ARXIV_BASE, "adapter_hint": "arxiv"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]

        # Act search
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "search", "params": {"query": "transformer"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "search_results"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_results_extraction():
    """搜索结果提取验证字段完整。"""
    import httpx

    async with httpx.AsyncClient() as client:
        # Create session and navigate to search results
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": ARXIV_SEARCH_URL, "adapter_hint": "arxiv"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "search_results"

        # Browse again to trigger extract
        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": ARXIV_SEARCH_URL},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["data"]["results"]) > 0
        result = data["data"]["results"][0]
        assert "id" in result
        assert "title" in result
        assert "url" in result
        assert isinstance(data["data"]["total_results"], int)
        assert isinstance(data["data"]["page_start"], int)


@pytest.mark.network
@pytest.mark.asyncio
async def test_paginate_keeps_state():
    """连续翻页保持 search_results 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": ARXIV_SEARCH_URL, "adapter_hint": "arxiv"},
        )
        sid = resp.json()["session_id"]

        # First paginate
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {"start": 25}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "search_results"
        assert data["retry"]["attempts"] == 1

        # Second paginate
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {"start": 50}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "search_results"
        assert data["session_suspended"] is False


@pytest.mark.network
@pytest.mark.asyncio
async def test_open_paper_detail():
    """打开论文详情页，提取 title/abstract。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": ARXIV_PAPER_URL, "adapter_hint": "arxiv"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "paper_detail"

        # Browse paper URL → extract content
        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": ARXIV_PAPER_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"
        assert len(data["data"]["title"]) > 0
        assert len(data["data"]["abstract"]) > 0


@pytest.mark.network
@pytest.mark.asyncio
async def test_state_rejection_on_home():
    """在 home 状态尝试不被允许的 paginate，返回 action_rejected。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": ARXIV_BASE, "adapter_hint": "arxiv"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "home"

        # Try paginate (not allowed on home)
        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("action_rejected") is True
        assert "search" in data.get("allowed_actions", [])
