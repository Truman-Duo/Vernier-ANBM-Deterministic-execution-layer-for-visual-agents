"""Integration tests for the DEV.to adapter.

Five scenarios cover feed state detection, article extraction,
state transition between feed ↔ article_detail, and pagination.

Run with: pytest tests/integration/test_devto.py -v -m network --timeout=60
"""
import pytest

DEVTO_HOME = "https://dev.to"


@pytest.mark.network
@pytest.mark.asyncio
async def test_home_page_is_feed():
    """首页被检测为 feed 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": DEVTO_HOME, "adapter_hint": "devto"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "feed"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_feed_extraction():
    """首页 feed 可提取文章列表，各字段正确。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": DEVTO_HOME, "adapter_hint": "devto"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "feed"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": DEVTO_HOME},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        articles = extracted.get("articles", [])
        assert len(articles) > 0

        article = articles[0]
        assert isinstance(article.get("id"), str)
        assert isinstance(article.get("title"), str)
        assert len(article.get("title", "")) > 0
        assert isinstance(article.get("url"), str)
        assert isinstance(article.get("reactions_count"), int)
        assert isinstance(article.get("reading_list"), bool)


@pytest.mark.network
@pytest.mark.asyncio
async def test_open_article_from_feed():
    """从 feed 打开文章 → 状态跳转到 article_detail。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": DEVTO_HOME, "adapter_hint": "devto"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": DEVTO_HOME},
        )
        assert resp.status_code == 200
        articles = resp.json()["data"].get("articles", [])
        assert len(articles) > 0
        article_url = articles[0]["url"]
        assert len(article_url) > 0

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_article", "params": {"url": article_url}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "article_detail"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_article_detail_extraction():
    """文章详情页提取 title/body_text/reactions_count/reading_list 字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": DEVTO_HOME, "adapter_hint": "devto"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": DEVTO_HOME},
        )
        assert resp.status_code == 200
        articles = resp.json()["data"].get("articles", [])
        assert len(articles) > 0
        article_url = articles[0]["url"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "open_article", "params": {"url": article_url}},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "article_detail"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": article_url},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        assert len(extracted.get("title", "")) > 0
        assert isinstance(extracted.get("body_text"), str)
        assert len(extracted.get("body_text", "")) > 0
        assert isinstance(extracted.get("reactions_count"), int)
        assert isinstance(extracted.get("reading_list"), bool)


@pytest.mark.network
@pytest.mark.asyncio
async def test_paginate_keeps_state():
    """翻页保持 feed 状态。

    URL 参数变化不改变页面语义结构，FSM 不应认为状态改变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": DEVTO_HOME, "adapter_hint": "devto"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "paginate", "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "feed"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True
