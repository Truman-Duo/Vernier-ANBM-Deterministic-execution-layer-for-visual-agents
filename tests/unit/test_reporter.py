"""Unit tests for AlertReporter."""
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anbm.health.models import (
    AdapterHealthStatus,
    AlertEvent,
    DegradationReason,
    HealthReport,
    SelectorCandidate,
    SelectorCheckResult,
)
from anbm.health.reporter import AlertReporter


def _make_event(
    adapter_id="test_adapter",
    previous=None,
    current=AdapterHealthStatus.BROKEN,
    reason=DegradationReason.SELECTOR_CHANGED,
):
    return AlertEvent(
        adapter_id=adapter_id,
        previous_status=previous,
        current_status=current,
        reason=reason,
        failed_selectors=[
            SelectorCheckResult(
                selector="ol.grid_view",
                state="list",
                found=False,
                candidates=[
                    SelectorCandidate(selector="div.new_list", source="css_similar", similarity=0.6),
                ],
            ),
        ],
        report=HealthReport(
            adapter_id=adapter_id,
            adapter_version="1.0.0",
            checked_at=datetime.now(timezone.utc),
            status=current,
            reason=reason,
            test_url="https://example.com",
            final_url="https://example.com/other",
            detected_state="unknown",
            selector_results=[],
            response_time_ms=1200,
        ),
    )


@pytest.mark.asyncio
async def test_emit_log(monkeypatch):
    """ANBM_ALERT_LOG=true 时调用 log_event（默认行为）。"""
    monkeypatch.setenv("ANBM_ALERT_LOG", "true")
    monkeypatch.delenv("ANBM_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("ANBM_ALERT_FILE", raising=False)

    reporter = AlertReporter()
    event = _make_event()

    with patch.object(reporter, "_log_event") as mock_log:
        await reporter.emit(event)
        mock_log.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_emit_webhook(monkeypatch):
    """ANBM_ALERT_WEBHOOK 设置时发送 POST 请求。"""
    monkeypatch.setenv("ANBM_ALERT_LOG", "false")
    monkeypatch.setenv("ANBM_ALERT_WEBHOOK", "https://hooks.example.com/alert")
    monkeypatch.delenv("ANBM_ALERT_FILE", raising=False)

    reporter = AlertReporter()
    event = _make_event()

    with patch.object(reporter._http_client, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        await reporter.emit(event)
        mock_post.assert_awaited_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["adapter_id"] == "test_adapter"
        assert kwargs["json"]["current_status"] == "broken"


@pytest.mark.asyncio
async def test_emit_file(monkeypatch):
    """ANBM_ALERT_FILE 设置时追加写入 JSONL。"""
    monkeypatch.setenv("ANBM_ALERT_LOG", "false")
    monkeypatch.delenv("ANBM_ALERT_WEBHOOK", raising=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        monkeypatch.setenv("ANBM_ALERT_FILE", tmp_path)
        reporter = AlertReporter()
        event = _make_event()
        await reporter.emit(event)

        with open(tmp_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["adapter_id"] == "test_adapter"
        assert data["current_status"] == "broken"
        assert data["message"] == "建议运行 `anbm repair test_adapter` 更新选择器"
    finally:
        os.unlink(tmp_path)
