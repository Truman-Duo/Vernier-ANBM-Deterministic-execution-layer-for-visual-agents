import pytest

from anbm.adapter.base import ExtractResult, ActResult
from anbm.engine.router import RetryOrchestrator, DecisionRouter
from anbm.engine.session_store import SessionStore


class MockValidator:
    def __init__(self, detect_result="list"):
        self.detect_result = detect_result

    async def detect_state(self, page, manifest):
        return self.detect_result, None


class MockAdapter:
    async def extract(self, page, state):
        return ExtractResult(data={"movies": []}, state="list")


class MockAdapterFails:
    async def extract(self, page, state):
        raise SelectorFailedError("no elements", selector=".item")

    async def act(self, page, action, params):
        raise SelectorFailedError("no elements", selector=".item")


from anbm.adapter.base import SelectorFailedError


@pytest.fixture
def session_store():
    return SessionStore()


@pytest.fixture
def manifest():
    return {
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "/list"},
            },
        },
        "action_idempotency": {
            "paginate": True,
            "post_comment": False,
        },
    }


@pytest.mark.asyncio
async def test_execute_extract_deterministic(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    result = await router.execute_extract(None, sesh, MockAdapter(), manifest)

    assert result["execution_path"] == "deterministic"
    assert result["data"] == {"movies": []}
    assert result["retry"]["succeeded"] is True
    assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_execute_extract_state_changed(session_store, manifest):
    validator = MockValidator("detail")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    class MockPage:
        url = "https://example.com/other"

    result = await router.execute_extract(MockPage(), sesh, MockAdapterFails(), manifest)

    assert result["execution_path"] == "state_changed"
    assert result["new_state"] == "detail"
    assert result["trigger_url"] == "https://example.com/other"
    assert result["detected_by"] == {}
    assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_execute_extract_fallback_no_visual(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    class MockPage:
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake_screenshot_data"

    result = await router.execute_extract(MockPage(), sesh, MockAdapterFails(), manifest)

    assert result["execution_path"] == "visual_fallback"
    assert result["error"] == "visual_model_not_configured"
    assert result["session_suspended"] is False
    assert result["selector_diff"]["failed_selector"] == ".item"


@pytest.mark.asyncio
async def test_execute_act_non_idempotent_fails(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    result = await router.execute_act(
        None, sesh, "post_comment", {}, MockAdapterFails(), manifest, is_idempotent=False
    )

    assert result["execution_path"] == "deterministic"
    assert result["success"] is False
    assert result["error"] == "non_idempotent_action_failed"
    assert result["requires_human_decision"] is True
    assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_fallback_records_stats(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    class MockPage:
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake"

    result = await router.execute_extract(MockPage(), sesh, MockAdapterFails(), manifest)

    assert result["execution_path"] == "visual_fallback"
    fetched = await session_store.get(sesh.session_id)
    assert fetched.retry_stats["fallback_count"] == 1


class MockAdapterRaisesValueError:
    async def extract(self, page, state):
        raise ValueError("mock extraction error")

    async def act(self, page, action, params):
        raise ValueError("mock act error")


@pytest.mark.asyncio
async def test_non_idempotent_unexpected_exception(session_store, manifest):
    """非幂等操作抛出 ValueError 时，返回 requires_human_decision: true，不进 fallback。"""
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    result = await router.execute_act(
        None, sesh, "post_comment", {}, MockAdapterRaisesValueError(), manifest, is_idempotent=False
    )

    assert result["execution_path"] == "deterministic"
    assert result["success"] is False
    assert result["error"] == "unexpected_error:ValueError"
    assert result["requires_human_decision"] is True
    assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_idempotent_unexpected_exception(session_store, manifest):
    """幂等操作抛出 ValueError 时，进入 visual_fallback 路径。"""
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("douban_movie", "1.0.0", "list")

    class MockPage:
        url = "https://example.com/test"
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake_screenshot_data"

    result = await router.execute_act(
        MockPage(), sesh, "paginate", {}, MockAdapterRaisesValueError(), manifest, is_idempotent=True
    )

    assert result["execution_path"] == "visual_fallback"
    assert result["session_suspended"] is False
    assert result["error"] == "visual_model_not_configured"


@pytest.mark.asyncio
async def test_visual_fallback_state_known_does_not_suspend(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("test", "1.0.0", "list")

    class MockPage:
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake"

    result = await router._visual_fallback(
        MockPage(), sesh, "test error",
        state_known=True,
        failed_selector=".broken",
    )

    assert result["session_suspended"] is False
    assert result["selector_diff"] == {
        "failed_selector": ".broken",
        "error_context": "test error",
    }


@pytest.mark.asyncio
async def test_visual_fallback_state_unknown_suspends(session_store, manifest):
    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("test", "1.0.0", "list")

    class MockPage:
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake"

    result = await router._visual_fallback(
        MockPage(), sesh, "test error",
        state_known=False,
        failed_selector=None,
    )

    assert result["session_suspended"] is True
    assert result["selector_diff"] is None


@pytest.mark.asyncio
async def test_execute_extract_fallback_passes_state_known_true(session_store, manifest):
    from unittest.mock import AsyncMock

    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("test", "1.0.0", "list")

    class MockPage:
        url = "https://example.com"
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake"

    mock_fallback = AsyncMock(return_value={"execution_path": "visual_fallback"})
    router._visual_fallback = mock_fallback

    class MockAdapterFailsAct:
        async def extract(self, page, state):
            raise SelectorFailedError("no elements", selector=".js-issue-row")

    await router.execute_extract(MockPage(), sesh, MockAdapterFailsAct(), manifest)

    mock_fallback.assert_called_once()
    call_kwargs = mock_fallback.call_args.kwargs
    assert call_kwargs["state_known"] is True
    assert call_kwargs["failed_selector"] == ".js-issue-row"


@pytest.mark.asyncio
async def test_execute_act_idempotent_fallback_passes_state_known_true(session_store, manifest):
    from unittest.mock import AsyncMock

    validator = MockValidator("list")
    retry = RetryOrchestrator(validator)
    router = DecisionRouter(retry, session_store, visual_client=None)
    sesh = await session_store.create("test", "1.0.0", "list")

    class MockPage:
        url = "https://example.com"
        async def screenshot(self, type="jpeg", quality=80):
            return b"fake"

    mock_fallback = AsyncMock(return_value={"execution_path": "visual_fallback"})
    router._visual_fallback = mock_fallback

    class MockAdapterFailsAct:
        async def act(self, page, action, params):
            raise SelectorFailedError("no elements", selector="[aria-label='Next']")

    await router.execute_act(
        MockPage(), sesh, "paginate", {}, MockAdapterFailsAct(), manifest, is_idempotent=True,
    )

    mock_fallback.assert_called_once()
    call_kwargs = mock_fallback.call_args.kwargs
    assert call_kwargs["state_known"] is True
    assert call_kwargs["failed_selector"] == "[aria-label='Next']"
