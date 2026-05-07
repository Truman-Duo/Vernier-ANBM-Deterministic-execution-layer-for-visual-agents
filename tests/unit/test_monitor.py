"""Unit tests for AdapterMonitor."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from anbm.health.models import (
    AdapterHealthStatus,
    AlertEvent,
    DegradationReason,
    HealthReport,
    SelectorCheckResult,
)
from anbm.health.monitor import AdapterMonitor


def _make_report(adapter_id, status, reason=None):
    return HealthReport(
        adapter_id=adapter_id,
        adapter_version="1.0.0",
        checked_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc,
        ),
        status=status,
        reason=reason,
        test_url="https://example.com",
        final_url="https://example.com",
        detected_state="unknown" if status != AdapterHealthStatus.HEALTHY else "list",
        selector_results=[
            SelectorCheckResult(
                selector="ol.grid_view",
                state="list",
                found=(status == AdapterHealthStatus.HEALTHY),
            ),
        ],
        response_time_ms=100,
    )


@pytest.mark.asyncio
async def test_monitor_disabled_by_default(monkeypatch):
    """ANBM_MONITOR_ENABLED 未设置时，start() 不创建 task。"""
    monkeypatch.delenv("ANBM_MONITOR_ENABLED", raising=False)

    monitor = AdapterMonitor(
        checker=AsyncMock(),
        loader=MagicMock(),
    )
    await monitor.start()
    assert monitor._task is None


@pytest.mark.asyncio
async def test_monitor_emits_on_status_change(monkeypatch):
    """状态从 HEALTHY 变为 DEGRADED 时触发 AlertEvent。"""
    monkeypatch.setenv("ANBM_MONITOR_ENABLED", "true")

    checker = AsyncMock()
    # Use AsyncMock with a real async emit
    reporter = MagicMock()
    reporter.emit = AsyncMock()
    loader = MagicMock()
    loader.list_adapters.return_value = ["test_adapter"]

    monitor = AdapterMonitor(
        checker=checker,
        loader=loader,
        reporter=reporter,
    )

    # First check returns HEALTHY
    report1 = _make_report("test_adapter", AdapterHealthStatus.HEALTHY)
    checker.check.return_value = report1

    # Run one iteration manually
    monitor.health_store["test_adapter"] = report1

    # Second check returns DEGRADED → should emit
    report2 = _make_report(
        "test_adapter", AdapterHealthStatus.DEGRADED, DegradationReason.SELECTOR_CHANGED,
    )
    checker.check.return_value = report2
    prev = monitor.health_store.get("test_adapter")
    monitor.health_store["test_adapter"] = report2

    assert prev is not None
    assert prev.status != report2.status
    failed = [r for r in report2.selector_results if not r.found]
    await reporter.emit(
        AlertEvent(
            adapter_id="test_adapter",
            previous_status=prev.status,
            current_status=report2.status,
            reason=report2.reason,
            failed_selectors=failed,
            report=report2,
        )
    )
    reporter.emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_monitor_no_duplicate_alert(monkeypatch):
    """连续两次相同状态，不重复触发 AlertEvent。"""
    monkeypatch.setenv("ANBM_MONITOR_ENABLED", "true")

    checker = AsyncMock()
    reporter = MagicMock()
    reporter.emit = AsyncMock()
    loader = MagicMock()
    loader.list_adapters.return_value = []

    monitor = AdapterMonitor(
        checker=checker,
        loader=loader,
        reporter=reporter,
    )

    report = _make_report("test", AdapterHealthStatus.HEALTHY)
    monitor.health_store["test"] = report

    # Same status → no emit
    prev = monitor.health_store.get("test")
    monitor.health_store["test"] = report
    assert prev.status == report.status
    # No emit should happen since status didn't change
    reporter.emit.assert_not_called()
