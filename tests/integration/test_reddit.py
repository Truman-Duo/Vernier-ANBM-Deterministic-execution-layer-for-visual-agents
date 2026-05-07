"""Integration tests for the Reddit adapter (login + voting).

Five scenarios cover auth flow, non-idempotent actions, cookie persistence,
and FSM-level action rejection.  All mock-based, no real network.
"""

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from anbm.adapter.base import (
    BaseAdapter,
    ExtractResult,
    ActResult,
    SelectorFailedError,
)
from anbm.engine.fsm import FSMEngine
from tests.fixtures.mock_pages import FakePage, FakeElement

REDDIT_URL = "https://www.reddit.com"

REDDIT_MANIFEST = {
    "id": "reddit",
    "name": "Reddit",
    "version": "1.0.0",
    "states": {
        "post_detail": {
            "check": {"type": "url_matches", "pattern": "/r/\\w+/comments/"},
            "allowed_actions": ["upvote_post", "extract_content"],
        },
        "subreddit_feed": {
            "check": {"type": "url_matches", "pattern": "/r/\\w+/$"},
            "allowed_actions": ["paginate", "open_post", "upvote_post"],
        },
        "logged_in": {
            "check": {"type": "element_present", "selector": "#user-info"},
            "allowed_actions": ["navigate_to_subreddit"],
        },
        "not_logged_in": {
            "check": {"type": "element_absent", "selector": "#user-info"},
            "allowed_actions": ["login"],
        },
    },
    "transitions": {
        "not_logged_in": {"login": "logged_in"},
        "logged_in": {"navigate_to_subreddit": "subreddit_feed"},
        "subreddit_feed": {
            "paginate": "subreddit_feed",
            "open_post": "post_detail",
            "upvote_post": "subreddit_feed",
        },
        "post_detail": {
            "upvote_post": "post_detail",
            "extract_content": "post_detail",
        },
    },
    "action_idempotency": {
        "login": False,
        "navigate_to_subreddit": True,
        "paginate": True,
        "open_post": True,
        "upvote_post": False,
        "extract_content": True,
    },
}


class MockRedditAdapter(BaseAdapter):
    """Configurable mock adapter for Reddit actions."""

    def __init__(self):
        self._upvote_fail = False

    def fail_next_upvote(self):
        self._upvote_fail = True

    async def extract(self, page, state):
        if state == "subreddit_feed":
            return ExtractResult(
                data={
                    "posts": [
                        {
                            "title": "Test Post",
                            "score": "42",
                            "url": "https://www.reddit.com/r/test/comments/abc/",
                            "comment_count": "7",
                        }
                    ]
                },
                state="subreddit_feed",
            )
        elif state == "post_detail":
            return ExtractResult(
                data={
                    "title": "Test Post",
                    "body": "This is a test post body.",
                    "score": "42",
                    "top_comments": [
                        {"author": "user1", "text": "Great post!"}
                    ],
                },
                state="post_detail",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        if action == "login":
            page.url = "https://www.reddit.com/"
            page.add_element("#user-info", FakeElement(text=params.get("username", "user")))
            return ActResult(success=True, next_state="logged_in")

        elif action == "navigate_to_subreddit":
            sub = params.get("subreddit", "")
            page.url = f"https://www.reddit.com/r/{sub}/"
            return ActResult(success=True, next_state="subreddit_feed")

        elif action == "paginate":
            return ActResult(success=True, next_state="subreddit_feed")

        elif action == "upvote_post":
            if self._upvote_fail:
                self._upvote_fail = False
                raise SelectorFailedError("mock upvote failure", "#upvote-btn")
            next_state = "post_detail" if "/comments/" in page.url else "subreddit_feed"
            return ActResult(success=True, next_state=next_state)

        elif action == "open_post":
            url = params.get("url", "")
            page.url = url
            return ActResult(success=True, next_state="post_detail")

        raise ValueError(f"act() 不支持操作: {action}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fsm(fsm, page, adapter):
    """Enter standard Reddit patches and return an ExitStack."""
    stack = ExitStack()
    stack.enter_context(patch.object(fsm.browser, "get_page", return_value=page))
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=REDDIT_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


def _page_not_logged_in():
    """Reddit front page for an anonymous user (no #user-info)."""
    return FakePage(url=REDDIT_URL, elements={
        "[data-testid=\"login-button\"]": FakeElement(text="Log In"),
    })


def _page_logged_in():
    """Reddit front page for a logged-in user."""
    return FakePage(url=REDDIT_URL, elements={
        "#user-info": FakeElement(text="test_user"),
    })


def _page_subreddit_feed(subreddit="test"):
    """A subreddit feed page for a logged-in user."""
    return FakePage(url=f"https://www.reddit.com/r/{subreddit}/", elements={
        "#user-info": FakeElement(text="test_user"),
    })


# ---------------------------------------------------------------------------
# Scenario 1 — Login flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_flow():
    """not_logged_in → act login → logged_in, session_suspended == false."""
    fsm = FSMEngine()
    page = _page_not_logged_in()
    adapter = MockRedditAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(REDDIT_URL, adapter_hint="reddit")
        sid = created.session_id
        assert created.current_state == "not_logged_in"

        result = await fsm.act(sid, "login", {"username": "alice", "password": "secret"})
        assert result["execution_path"] == "deterministic"
        assert result["retry"]["attempts"] == 1
        assert result["session_suspended"] is False

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "logged_in"


# ---------------------------------------------------------------------------
# Scenario 2 — Non-idempotent action failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_idempotent_upvote_failure():
    """upvote_post fails → requires_human_decision, retry.attempts=1, no detect_state."""
    fsm = FSMEngine()
    page = _page_subreddit_feed()
    adapter = MockRedditAdapter()
    adapter.fail_next_upvote()

    with _mock_fsm(fsm, page, adapter) as stack:
        # Spy on detect_state — manual wrapper keeps call tracking reliable
        original_detect = fsm.validator.detect_state

        class _DetectSpy:
            def __init__(self):
                self.call_count = 0

            async def __call__(self, page, manifest):
                self.call_count += 1
                return await original_detect(page, manifest)

        spy = _DetectSpy()
        stack.enter_context(patch.object(fsm.validator, "detect_state", spy))

        created = await fsm.create_session(REDDIT_URL, adapter_hint="reddit")
        sid = created.session_id

        br = await fsm.browse(sid, f"https://www.reddit.com/r/test/")
        assert br["execution_path"] == "deterministic"
        before = spy.call_count

        result = await fsm.act(sid, "upvote_post", {"post_id": "t3_abc"})

        assert result.get("error") == "non_idempotent_action_failed"
        assert result.get("requires_human_decision") is True
        assert result["retry"]["attempts"] == 1
        assert result["retry"]["succeeded"] is False
        assert spy.call_count == before, "detect_state was called during non-idempotent act"


# ---------------------------------------------------------------------------
# Scenario 3 — Cookie persistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_persistence(tmp_path):
    """Login → save cookies → new session loads cookies → logged_in, skip login."""
    cookie_dir = tmp_path / ".cookies"
    cookie_dir.mkdir(parents=True)

    fsm = FSMEngine()
    page = _page_not_logged_in()
    adapter = MockRedditAdapter()

    async def cookie_get_page(session_id):
        """Simulate create_context auto-loading cookies from disk."""
        path = os.path.join(str(cookie_dir), f"{session_id}.json")
        if os.path.isfile(path):
            page.add_element("#user-info", FakeElement(text="user"))
        return page

    with _mock_fsm(fsm, page, adapter) as stack:
        # Override get_page with cookie-aware version
        stack.enter_context(patch.object(fsm.browser, "get_page", cookie_get_page))

        created = await fsm.create_session(REDDIT_URL, adapter_hint="reddit")
        sid = created.session_id
        assert created.current_state == "not_logged_in"

        await fsm.act(sid, "login", {"username": "bob", "password": "p"})

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "logged_in"

        # Simulate save_cookies: write cookie file
        sesh.cookies_path = os.path.join(str(cookie_dir), f"{sid}.json")
        with open(sesh.cookies_path, "w") as f:
            json.dump([{"name": "reddit_session", "value": "abc123"}], f)

        # Also write at the "pending" location that create_session will use
        pending_path = os.path.join(str(cookie_dir), "reddit_pending.json")
        with open(pending_path, "w") as f:
            json.dump([{"name": "reddit_session", "value": "abc123"}], f)

    # --- New FSMEngine: loading cookies should make us logged_in ---
    fsm2 = FSMEngine()
    page2 = FakePage(url=REDDIT_URL, elements={
        "[data-testid=\"login-button\"]": FakeElement(text="Log In"),
    })
    adapter2 = MockRedditAdapter()

    async def cookie_get_page_2(session_id):
        path = os.path.join(str(cookie_dir), f"{session_id}.json")
        if os.path.isfile(path):
            page2.add_element("#user-info", FakeElement(text="bob"))
        return page2

    with _mock_fsm(fsm2, page2, adapter2) as stack:
        stack.enter_context(patch.object(fsm2.browser, "get_page", cookie_get_page_2))

        created2 = await fsm2.create_session(REDDIT_URL, adapter_hint="reddit")
        sid2 = created2.session_id

        # Cookie loaded -> page has #user-info -> detect returns logged_in
        assert created2.current_state == "logged_in", \
            f"expected logged_in, got {created2.current_state}"

        # Skip login, navigate directly
        result = await fsm2.act(sid2, "navigate_to_subreddit", {"subreddit": "test"})
        assert result["execution_path"] == "deterministic"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Scenario 4 — Non-idempotent action success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_idempotent_upvote_success():
    """upvote_post succeeds → retry.attempts=1, execution_path=deterministic."""
    fsm = FSMEngine()
    page = _page_subreddit_feed()
    adapter = MockRedditAdapter()  # upvote does NOT fail

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(REDDIT_URL, adapter_hint="reddit")
        sid = created.session_id

        br = await fsm.browse(sid, "https://www.reddit.com/r/test/")
        assert br["execution_path"] == "deterministic"

        result = await fsm.act(sid, "upvote_post", {"post_id": "t3_abc"})
        assert result["execution_path"] == "deterministic"
        assert result["retry"]["attempts"] == 1
        assert result["retry"]["succeeded"] is True
        assert result["success"] is True
        assert result["session_suspended"] is False


# ---------------------------------------------------------------------------
# Scenario 5 — FSM rejection: action not allowed in current state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_rejected_in_wrong_state():
    """upvote_post in not_logged_in → action_rejected, allowed_actions=[login]."""
    fsm = FSMEngine()
    page = _page_not_logged_in()
    adapter = MockRedditAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(REDDIT_URL, adapter_hint="reddit")
        sid = created.session_id
        assert created.current_state == "not_logged_in"

        result = await fsm.act(sid, "upvote_post", {"post_id": "t3_abc"})
        assert result.get("action_rejected") is True
        assert result.get("reason") is not None
        assert "upvote_post" in result.get("reason", "")
        assert result.get("allowed_actions") == ["login"]
