"""Integration tests for the Mastodon adapter.

Four scenarios cover feed_partial state detection, feed extraction,
scroll_load_more state preservation, and scroll_load_more data return.

Run with: pytest tests/integration/test_mastodon.py -v -m network --timeout=60
"""
import pytest

MASTODON_URL = "https://hachyderm.io/public/local"


@pytest.mark.network
@pytest.mark.asyncio
async def test_feed_partial_state():
    """Mastodon 公开时间线被检测为 feed_partial 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MASTODON_URL, "adapter_hint": "mastodon"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "feed_partial"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_feed_extraction():
    """feed_partial 状态可提取 statuses，各字段正确。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MASTODON_URL, "adapter_hint": "mastodon"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert resp.json()["current_state"] == "feed_partial"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MASTODON_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        statuses = extracted.get("statuses", [])
        assert len(statuses) > 0

        status = statuses[0]
        assert isinstance(status.get("id"), str)
        assert len(status.get("id", "")) > 0
        assert isinstance(status.get("author"), str)
        assert isinstance(status.get("content"), str)
        assert isinstance(status.get("url"), str)


@pytest.mark.network
@pytest.mark.asyncio
async def test_scroll_load_more_keeps_state():
    """滚动加载更多仍保持 feed_partial 状态。

    滚动到底部加载新内容后，页面语义结构不变，
    FSM 不应认为状态改变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MASTODON_URL, "adapter_hint": "mastodon"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "scroll_load_more", "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "feed_partial"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_scroll_load_more_returns_data():
    """scroll_load_more 返回 {loaded_count, has_more} 数据字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MASTODON_URL, "adapter_hint": "mastodon"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "scroll_load_more", "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "loaded_count" in data["data"]
        assert "has_more" in data["data"]
        assert isinstance(data["data"]["loaded_count"], int)
        assert isinstance(data["data"]["has_more"], bool)
