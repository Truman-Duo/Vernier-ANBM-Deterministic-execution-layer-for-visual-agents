"""Integration tests for the Lobsters adapter.

These tests require a running server on port 8000 and real lobste.rs access.
Run with: pytest tests/integration/test_lobsters.py -v -m network --timeout=60
"""
import pytest

LOBSTERS_HOME = "https://lobste.rs"
LOBSTERS_STORY_URL = "https://lobste.rs/s/ifcyr1/contributor_poker_zig_s_ai_ban"


@pytest.mark.network
@pytest.mark.asyncio
async def test_home_page_is_story_list():
    """首页被检测为 story_list 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": LOBSTERS_HOME, "adapter_hint": "lobsters"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "story_list"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_filter_by_tag_does_not_change_state():
    """核心测试：filter_by_tag 只改变 URL 路径，FSM 状态保持 story_list。

    URL 路径从 / 变为 /t/rust 不构成状态变化——页面语义结构未变。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": LOBSTERS_HOME, "adapter_hint": "lobsters"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "filter_by_tag", "params": {"tag": "rust"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "story_list"
        assert data["execution_path"] == "deterministic"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_open_story_detail():
    """打开故事详情页，状态跳转到 story_detail。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": LOBSTERS_STORY_URL, "adapter_hint": "lobsters"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "story_detail"
        assert data["session_suspended"] is False
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_keeps_state():
    """搜索保持在 story_list 状态。

    URL 参数变化不改变页面语义结构。
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": LOBSTERS_HOME, "adapter_hint": "lobsters"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "search", "params": {"query": "zig"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "story_list"
        assert data["session_suspended"] is False
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_story_detail_extraction():
    """故事详情页提取 title/url/tags/score/domain 等字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": LOBSTERS_STORY_URL, "adapter_hint": "lobsters"},
        )
        assert resp.status_code == 200
        data = resp.json()
        sid = data["session_id"]
        assert data["current_state"] == "story_detail"

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": LOBSTERS_STORY_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data["data"]
        assert len(extracted.get("title", "")) > 0
        assert isinstance(extracted.get("url"), str)
        assert isinstance(extracted.get("tags"), list)
        assert isinstance(extracted.get("score"), int)
        assert isinstance(extracted.get("comment_count"), int)
        assert isinstance(extracted.get("submitter"), str)
        assert isinstance(extracted.get("description_html"), str)
        assert isinstance(extracted.get("domain"), str)
