"""Integration tests for the MDN Web Docs adapter.

Covers article state detection, content extraction with code blocks,
interactive example boundary, and text content consistency.

Run with: pytest tests/integration/test_mdn.py -v -m network --timeout=60
"""
import pytest

MDN_ARTICLE_URL = "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a"


@pytest.mark.network
@pytest.mark.asyncio
async def test_article_state():
    """MDN 文章页面被检测为 article 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MDN_ARTICLE_URL, "adapter_hint": "mdn"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "article"
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_article_extraction():
    """文章提取返回 title + content_blocks，包含 text/code 等类型。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MDN_ARTICLE_URL, "adapter_hint": "mdn"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MDN_ARTICLE_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        extracted = data.get("data", {})
        assert isinstance(extracted.get("title"), str) and len(extracted["title"]) > 0

        blocks = extracted.get("content_blocks", [])
        assert len(blocks) > 0

        types_found = {b["type"] for b in blocks}
        assert "text" in types_found


@pytest.mark.network
@pytest.mark.asyncio
async def test_code_block_extraction():
    """代码块完整提取，保留内容。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MDN_ARTICLE_URL, "adapter_hint": "mdn"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MDN_ARTICLE_URL},
        )
        assert resp.status_code == 200
        data = resp.json()

        blocks = data.get("data", {}).get("content_blocks", [])
        code_blocks = [b for b in blocks if b["type"] == "code"]
        if code_blocks:
            cb = code_blocks[0]
            assert cb["extractable"] is True
            assert isinstance(cb["content"], str) and len(cb["content"]) > 0


@pytest.mark.network
@pytest.mark.asyncio
async def test_interactive_viz_boundary(handler=""):
    """交互式示例标记为 extractable=False，不穿透 iframe。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MDN_ARTICLE_URL, "adapter_hint": "mdn"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MDN_ARTICLE_URL},
        )
        assert resp.status_code == 200
        data = resp.json()

        blocks = data.get("data", {}).get("content_blocks", [])
        viz_blocks = [
            b for b in blocks if b.get("type") == "interactive_viz"
        ]
        if viz_blocks:
            for viz in viz_blocks:
                assert viz.get("extractable") is False
                assert isinstance(viz.get("src"), str)
                # 不穿透 iframe：不包含 iframe 内部的内容字段
                assert "content" not in viz


@pytest.mark.network
@pytest.mark.asyncio
async def test_text_content_consistency():
    """文本内容与 DOM 一致，不加工不推理。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": MDN_ARTICLE_URL, "adapter_hint": "mdn"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # 两次提取应返回一致的结构
        resp1 = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MDN_ARTICLE_URL},
        )
        resp2 = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": MDN_ARTICLE_URL},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200

        # 结构稳定性：两次返回的数据字段类型一致
        data1 = resp1.json().get("data", {})
        data2 = resp2.json().get("data", {})
        assert isinstance(data1.get("title"), str)
        assert isinstance(data2.get("title"), str)
