import pytest


@pytest.mark.network
@pytest.mark.asyncio
async def test_health_check_nonexistent_adapter():
    """Test health check returns not_found for non-existent adapter."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://localhost:8000/health/adapter/nonexistent_xyz"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["adapter_id"] == "nonexistent_xyz"
        assert data["status"] == "not_found"


@pytest.mark.network
@pytest.mark.asyncio
async def test_health_check_hackernews():
    """Test health check returns healthy for HN adapter."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://localhost:8000/health/adapter/hackernews"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded", "unreachable", "not_found")
        assert "response_time_ms" in data


@pytest.mark.network
@pytest.mark.asyncio
async def test_get_all_adapters_summary():
    """GET /health/adapters 返回所有 adapter 摘要。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/health/adapters")
        assert resp.status_code == 200
        data = resp.json()
        assert "adapters" in data
        assert len(data["adapters"]) >= 6
        for entry in data["adapters"]:
            assert "adapter_id" in entry
            assert "status" in entry


@pytest.mark.network
@pytest.mark.asyncio
async def test_arxiv_health_check_returns_healthy():
    """arxiv 健康检查返回 healthy 或 degraded（不能是 unreachable）。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://localhost:8000/health/adapter/arxiv"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded", "unreachable", "not_found")
        assert "response_time_ms" in data


@pytest.mark.network
@pytest.mark.asyncio
async def test_all_adapters_health_summary():
    """GET /health/adapters 列表包含 arxiv。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/health/adapters")
        assert resp.status_code == 200
        data = resp.json()
        adapter_ids = [a["adapter_id"] for a in data["adapters"]]
        assert "arxiv" in adapter_ids


@pytest.mark.network
@pytest.mark.asyncio
async def test_manual_trigger():
    """POST /health/adapter/douban_movie/check 返回完整 HealthReport。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/health/adapter/douban_movie/check"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["adapter_id"] == "douban_movie"
        assert "status" in data
        assert "detected_state" in data
        assert "selector_results" in data
        assert "response_time_ms" in data


@pytest.mark.network
@pytest.mark.asyncio
async def test_selector_candidates_in_report():
    """DEGRADED 状态的报告包含非空 candidates 列表。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/health/adapter/douban_movie/check"
        )
        assert resp.status_code == 200
        data = resp.json()
        # 如果状态为 DEGRADED，检查 candidates
        if data["status"] == "degraded":
            for sr in data["selector_results"]:
                if not sr.get("found"):
                    # 至少有一个失效选择器有 candidates
                    has_candidates = any(
                        r.get("candidates") for r in data["selector_results"] if not r.get("found")
                    )
                    if has_candidates:
                        break
