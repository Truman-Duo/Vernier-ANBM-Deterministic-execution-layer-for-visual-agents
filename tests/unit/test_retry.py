import pytest

from anbm.adapter.base import SelectorFailedError, StateChangedError
from anbm.engine.retry_config import RETRY_CONFIGS
from anbm.engine.router import RetryOrchestrator
from anbm.engine.validator import StateValidator


class MockValidator:
    """Mock validator that returns controlled detect_state results."""

    def __init__(self, states: list[str]):
        self.states = states
        self.call_count = 0
        self.called = False

    async def detect_state(self, page, manifest):
        self.called = True
        idx = min(self.call_count, len(self.states) - 1)
        self.call_count += 1
        return self.states[idx], None


@pytest.fixture
def manifest():
    return {
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "/list"},
            },
            "detail": {
                "check": {"type": "url_contains", "value": "/detail"},
            },
        }
    }


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(manifest):
    """第一次抛 SelectorFailedError，第二次成功。"""
    validator = MockValidator(["list", "list"])
    orchestrator = RetryOrchestrator(validator)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SelectorFailedError("first fail", selector=".item")
        return "success"

    result, retry_info = await orchestrator.execute_with_retry(
        operation,
        config=RETRY_CONFIGS["extract"],
        operation_name="test_extract",
        page=None,
        manifest=manifest,
        expected_state="list",
    )

    assert result == "success"
    assert retry_info == {"attempts": 2, "succeeded": True}
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_aborts_on_state_change(manifest):
    """detect_state 返回不同状态，抛 StateChangedError。"""
    validator = MockValidator(["detail"])  # first retry detects "detail"
    orchestrator = RetryOrchestrator(validator)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        raise SelectorFailedError("fail", selector=".item")

    class MockPage:
        url = "https://example.com/detail"

    with pytest.raises(StateChangedError) as exc_info:
        await orchestrator.execute_with_retry(
            operation,
            config=RETRY_CONFIGS["extract"],
            operation_name="test_extract",
            page=MockPage(),
            manifest=manifest,
            expected_state="list",
        )

    assert exc_info.value.new_state == "detail"
    assert exc_info.value.attempts_before_change == 1
    assert exc_info.value.trigger_url == "https://example.com/detail"
    assert exc_info.value.detected_by == {}
    assert call_count == 1  # 只执行了一次操作就跳转了


@pytest.mark.asyncio
async def test_retry_continues_on_unknown_state(manifest):
    """detect_state 返回 unknown，继续重试不报跳转。"""
    validator = MockValidator(["unknown", "list"])
    orchestrator = RetryOrchestrator(validator)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise SelectorFailedError("fail", selector=".item")
        return "success"

    result, retry_info = await orchestrator.execute_with_retry(
        operation,
        config=RETRY_CONFIGS["extract"],
        operation_name="test_extract",
        page=None,
        manifest=manifest,
        expected_state="list",
    )

    assert result == "success"
    assert retry_info == {"attempts": 2, "succeeded": True}
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_exhausted_raises(manifest):
    """连续失败至耗尽，抛 SelectorFailedError。"""
    validator = MockValidator(["list", "list", "list"])
    orchestrator = RetryOrchestrator(validator)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        raise SelectorFailedError("always fail", selector=".item")

    with pytest.raises(SelectorFailedError):
        await orchestrator.execute_with_retry(
            operation,
            config=RETRY_CONFIGS["extract"],
            operation_name="test_extract",
            page=None,
            manifest=manifest,
            expected_state="list",
        )

    assert call_count == RETRY_CONFIGS["extract"].max_attempts


@pytest.mark.asyncio
async def test_non_idempotent_no_retry(manifest):
    """max_attempts=1，失败后不重试，detect_state 未被调用。"""
    validator = MockValidator(["some_state"])
    orchestrator = RetryOrchestrator(validator)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        raise SelectorFailedError("fail once", selector=".item")

    with pytest.raises(SelectorFailedError):
        await orchestrator.execute_with_retry(
            operation,
            config=RETRY_CONFIGS["act_non_idempotent"],
            operation_name="test_non_idempotent",
            page=None,
            manifest=manifest,
            expected_state="some_state",
        )

    assert call_count == 1
    assert not validator.called, "max_attempts=1 时不应调用 detect_state()"
