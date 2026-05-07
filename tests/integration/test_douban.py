"""Integration tests for the full FSMEngine browse → act → session lifecycle.

All tests use mocked Playwright pages and adapters — no real network or browser.
Six scenarios cover the complete decision-routing matrix.
"""

import asyncio
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

import pytest

from anbm.adapter.base import (
    BaseAdapter,
    ExtractResult,
    ActResult,
    SelectorFailedError,
)
from anbm.engine.fsm import FSMEngine
from tests.fixtures.mock_pages import FakePage, FakeElement

DOUBAN_URL = "https://movie.douban.com/top250"

DOUBAN_MANIFEST = {
    "id": "douban_movie",
    "name": "豆瓣电影 Top250",
    "version": "1.0.0",
    "states": {
        "movie_list": {
            "check": {"type": "element_present", "selector": "ol.grid_view"},
            "also_check": {"type": "url_contains", "value": "top250"},
            "allowed_actions": ["paginate"],
        },
        "movie_detail": {
            "check": {"type": "url_matches", "pattern": "/subject/\\d+"},
            "allowed_actions": [],
        },
    },
    "transitions": {"movie_list": {"paginate": "movie_list"}},
    "action_idempotency": {"paginate": True},
}


class MockDoubanAdapter(BaseAdapter):
    """Configurable mock adapter — controls extract failure count and act delay."""

    def __init__(self):
        self._extract_failures = 0
        self._act_delay = 0

    def fail_n_times(self, n: int):
        """Fail the next *n* extract calls, then succeed."""
        self._extract_failures = n

    def set_act_delay(self, seconds: float):
        """Add a delay before act returns (for concurrency tests)."""
        self._act_delay = seconds

    async def extract(self, page, state):
        if self._extract_failures > 0:
            self._extract_failures -= 1
            raise SelectorFailedError("mock failure", selector=".item")
        return ExtractResult(
            data={
                "movies": [
                    {
                        "title": "Test Movie",
                        "rating": "9.1",
                        "url": "https://movie.douban.com/subject/1/",
                    }
                ],
                "pagination": {"current": 1, "has_next": True},
            },
            state=state,
        )

    async def act(self, page, action, params):
        if self._act_delay > 0:
            await asyncio.sleep(self._act_delay)
        return ActResult(success=True, next_state="movie_list")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fsm(fsm, page, adapter):
    """Enter standard patches on *fsm* and return an ExitStack."""
    stack = ExitStack()
    stack.enter_context(
        patch.object(fsm.browser, "get_page", return_value=page)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=DOUBAN_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


def _fake_page():
    return FakePage(url=DOUBAN_URL, elements={"ol.grid_view": FakeElement()})


# ---------------------------------------------------------------------------
# Scenario 1 — Normal path: browse + 3 × paginate, all deterministic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_browse_and_paginate():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()

    with _mock_fsm(fsm, _fake_page(), adapter):
        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id
        assert created.current_state == "movie_list"

        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "deterministic"
        assert br["retry"] == {"attempts": 1, "succeeded": True}
        assert br["session_suspended"] is False

        for i in range(3):
            ar = await fsm.act(sid, "paginate")
            assert ar["execution_path"] == "deterministic", f"act #{i} failed"
            assert ar["retry"] == {"attempts": 1, "succeeded": True}
            assert ar["success"] is True
            assert ar["session_suspended"] is False

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "movie_list"


# ---------------------------------------------------------------------------
# Scenario 2 — Retry succeeds: extract fails once, retries, succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()
    adapter.fail_n_times(1)  # first extract → fail, second → succeed

    with _mock_fsm(fsm, _fake_page(), adapter):
        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id

        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "deterministic"
        assert br["retry"]["attempts"] == 2
        assert br["retry"]["succeeded"] is True

        sesh = await fsm.session_store.get(sid)
        assert sesh.retry_stats["successful_retries"] == 1


# ---------------------------------------------------------------------------
# Scenario 3 — State changed during retry → execution_path = state_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_state_changed_during_retry():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()
    adapter.fail_n_times(1)

    with _mock_fsm(fsm, _fake_page(), adapter) as stack:
        mock_detect = stack.enter_context(
            patch.object(fsm.validator, "detect_state", new_callable=AsyncMock)
        )
        # create_session → browse initial → retry after failure
        mock_detect.side_effect = [
            ("movie_list", None),    # create_session
            ("movie_list", None),    # browse initial state check
            ("movie_detail", None),  # retry: state changed → StateChangedError
        ]

        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id

        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "state_changed"
        assert br["previous_state"] == "movie_list"
        assert br["new_state"] == "movie_detail"
        assert br["retry"]["attempts"] == 1
        assert br["retry"]["succeeded"] is False

        sesh = await fsm.session_store.get(sid)
        assert sesh.retry_stats["state_changed_interrupts"] == 1


# ---------------------------------------------------------------------------
# Scenario 4 — Unknown tolerance: detect_state returns "unknown", retry
#              continues, eventually succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tolerance_continues_retry():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()
    adapter.fail_n_times(1)

    with _mock_fsm(fsm, _fake_page(), adapter) as stack:
        mock_detect = stack.enter_context(
            patch.object(fsm.validator, "detect_state", new_callable=AsyncMock)
        )
        mock_detect.side_effect = [
            ("movie_list", None),  # create_session
            ("movie_list", None),  # browse initial state check
            ("unknown", None),     # retry after failure → tolerated, retry continues
        ]

        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id

        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "deterministic"
        assert br["retry"]["attempts"] == 2
        assert br["retry"]["succeeded"] is True
        assert br["session_suspended"] is False


# ---------------------------------------------------------------------------
# Scenario 5 — Fallback: extract fails 3× → visual_fallback → session
#              suspended → act rejected → browse resumes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_suspend_and_resume():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()
    adapter.fail_n_times(99)  # always fail

    with _mock_fsm(fsm, _fake_page(), adapter):
        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id

        # ---- First browse → extract fails 3× → visual_fallback ----
        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "visual_fallback"
        assert br["error"] == "visual_model_not_configured"
        assert br["session_suspended"] is True

        sesh = await fsm.session_store.get(sid)
        assert sesh.session_suspended is True
        assert sesh.retry_stats["fallback_count"] == 1

        # ---- act while suspended → rejected ----
        ar = await fsm.act(sid, "paginate")
        assert ar.get("error") == "session_suspended"

        # ---- Fix adapter and browse again → resumes ----
        adapter.fail_n_times(0)

        br2 = await fsm.browse(sid, DOUBAN_URL)
        assert br2["execution_path"] == "deterministic"

        sesh2 = await fsm.session_store.get(sid)
        assert sesh2.session_suspended is False

        # ---- act now works ----
        ar2 = await fsm.act(sid, "paginate")
        assert ar2["execution_path"] == "deterministic"


# ---------------------------------------------------------------------------
# Scenario 6 — Concurrency: two simultaneous act calls → one 409
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_act_returns_409():
    fsm = FSMEngine()
    adapter = MockDoubanAdapter()
    adapter.set_act_delay(0.3)

    with _mock_fsm(fsm, _fake_page(), adapter):
        created = await fsm.create_session(DOUBAN_URL, adapter_hint="douban_movie")
        sid = created.session_id

        br = await fsm.browse(sid, DOUBAN_URL)
        assert br["execution_path"] == "deterministic"

        results = await asyncio.gather(
            fsm.act(sid, "paginate"),
            fsm.act(sid, "paginate"),
            return_exceptions=True,
        )

        successes = [
            r
            for r in results
            if isinstance(r, dict) and r.get("execution_path") == "deterministic"
        ]
        busies = [
            r
            for r in results
            if isinstance(r, dict) and r.get("error") == "session_busy"
        ]

        assert len(successes) == 1, (
            f"expected 1 success, got {len(successes)}: {results}"
        )
        assert len(busies) == 1, (
            f"expected 1 busy, got {len(busies)}: {results}"
        )
