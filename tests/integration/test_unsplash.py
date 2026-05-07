"""Integration tests for the Unsplash adapter.

Covers photo_grid state detection, photo extraction, photo detail state,
and search navigation.

Run with: pytest tests/integration/test_unsplash.py -v -m network --timeout=60
"""
import pytest

UNSPLASH_URL = "https://unsplash.com"
PHOTO_URL = "https://unsplash.com/photos/a-person-standing-on-a-rock-overlooking-a-mountain-range-Wv2VXvIqN3A"


@pytest.mark.network
@pytest.mark.asyncio
async def test_photo_grid_state():
    """Unsplash 首页被检测为 photo_grid 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": UNSPLASH_URL, "adapter_hint": "unsplash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "photo_grid"
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_photo_grid_extraction():
    """photo_grid 可提取 photos 列表，各字段正确。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": UNSPLASH_URL, "adapter_hint": "unsplash"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": UNSPLASH_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        photos = data.get("data", {}).get("photos", [])
        assert len(photos) > 0

        photo = photos[0]
        assert photo["type"] == "image"
        assert isinstance(photo.get("src"), str) and len(photo["src"]) > 0
        assert isinstance(photo.get("alt"), str)
        assert isinstance(photo.get("extractable"), bool)


@pytest.mark.network
@pytest.mark.asyncio
async def test_photo_detail_state():
    """照片详情页被检测为 photo_detail 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PHOTO_URL, "adapter_hint": "unsplash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "photo_detail"
        assert data["execution_path"] == "deterministic"
        assert data["retry"]["succeeded"] is True


@pytest.mark.network
@pytest.mark.asyncio
async def test_photo_detail_extraction():
    """photo_detail 提取 type/src/alt/extractable 字段。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": PHOTO_URL, "adapter_hint": "unsplash"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/browse/{sid}",
            json={"url": PHOTO_URL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "deterministic"

        detail = data.get("data", {})
        assert detail.get("type") == "image"
        assert isinstance(detail.get("src"), str) and len(detail["src"]) > 0
        assert isinstance(detail.get("alt"), str)
        assert isinstance(detail.get("extractable"), bool)
        # extractable: false for images without meaningful alt text
        # alt may vary depending on the photo, just verify the field exists


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_navigation():
    """搜索动作导航到搜索页 → photo_grid 状态。"""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/browse",
            json={"url": UNSPLASH_URL, "adapter_hint": "unsplash"},
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        resp = await client.post(
            f"http://localhost:8000/act/{sid}",
            json={"action": "search", "params": {"keyword": "nature"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "photo_grid"
        assert data["execution_path"] == "deterministic"
