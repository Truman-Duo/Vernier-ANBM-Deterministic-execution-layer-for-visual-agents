"""Tests for ANBM Python client SDK."""
from unittest.mock import MagicMock, AsyncMock, patch

import httpx
import pytest

from anbm.client import (
    ANBMClient,
    AsyncANBMClient,
    ANBMActionRejected,
)


def test_browse_constructs_correct_request():
    """ANBMClient.browse 发送正确的请求体到 /browse。"""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.is_error = False
    mock_resp.json.return_value = {"session_id": "abc", "execution_path": "deterministic"}

    client = ANBMClient()
    with patch.object(client._client, "request", return_value=mock_resp) as mock_request:
        result = client.browse(
            "https://example.com",
            adapter_hint="test",
            session_id=None,
        )

    mock_request.assert_called_once_with(
        "POST",
        "http://localhost:8000/browse",
        json={"url": "https://example.com", "adapter_hint": "test"},
    )
    assert result["session_id"] == "abc"


def test_act_raises_on_409():
    """收到 409 时抛出 ANBMActionRejected。"""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 409
    mock_resp.is_error = True
    mock_resp.text = '{"error": "session_busy"}'

    client = ANBMClient()
    with patch.object(client._client, "request", return_value=mock_resp):
        with pytest.raises(ANBMActionRejected):
            client.act("session-1", "paginate")


@pytest.mark.asyncio
async def test_async_client_browse():
    """AsyncANBMClient.browse 发送正确请求并返回结果。"""
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.is_error = False
    mock_resp.json.return_value = {"session_id": "abc", "execution_path": "deterministic"}

    client = AsyncANBMClient()
    with patch.object(client._client, "request", return_value=mock_resp) as mock_request:
        result = await client.browse("https://example.com")

    mock_request.assert_called_once_with(
        "POST",
        "http://localhost:8000/browse",
        json={"url": "https://example.com"},
    )
    assert result["session_id"] == "abc"
