"""Integration tests for the Codeberg adapter.

Five scenarios cover issue_list state detection, issue extraction,
state transition between issue_list ↔ issue_detail, and pagination.

Run with: pytest tests/integration/test_codeberg.py -v -m network --timeout=60
"""
import pytest

CODEBERG_ISSUES = "https://codeberg.org/forgejo/forgejo/issues"
CODEBERG_ISSUE_URL = "https://codeberg.org/forgejo/forgejo/issues/1"


@pytest.mark.network
@pytest.mark.asyncio
async def test_issue_list_state():
    """issue 列表页被检测为 issue_list 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": CODEBERG_ISSUES, "adapter_hint": "codeberg"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "issue_list"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_issue_list_extraction():
    """issue 列表页可提取 issue 卡片，各字段正确。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": CODEBERG_ISSUES, "adapter_hint": "codeberg"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "issue_list"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": CODEBERG_ISSUES},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        issues = extracted.get("issues", [])
        assert len(issues) > 0

        issue = issues[0]
        assert isinstance(issue.get("id"), str)
        assert len(issue.get("id", "")) > 0
        assert isinstance(issue.get("title"), str)
        assert len(issue.get("title", "")) > 0
        assert isinstance(issue.get("url"), str)
        assert isinstance(issue.get("state"), str)


@pytest.mark.network
@pytest.mark.asyncio
async def test_open_issue_detail():
    """打开 issue 详情 → 状态跳转到 issue_detail。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": CODEBERG_ISSUES, "adapter_hint": "codeberg"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_issue", "params": {"url": CODEBERG_ISSUE_URL}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "issue_detail"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_issue_detail_extraction():
    """issue 详情页提取 title/body/state/assignees 字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": CODEBERG_ISSUE_URL, "adapter_hint": "codeberg"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "issue_detail"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": CODEBERG_ISSUE_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        assert len(extracted.get("title", "")) > 0
        assert isinstance(extracted.get("body"), str)
        assert isinstance(extracted.get("state"), str)
        assert isinstance(extracted.get("assignees"), list)


@pytest.mark.network
@pytest.mark.asyncio
async def test_paginate_keeps_state():
    """翻页保持 issue_list 状态。

    页码变化不改变页面语义结构，FSM 不应认为状态改变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": CODEBERG_ISSUES, "adapter_hint": "codeberg"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "issue_list"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True
