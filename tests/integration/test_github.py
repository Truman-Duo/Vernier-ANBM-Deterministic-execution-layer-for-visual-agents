"""Integration tests for the GitHub Issues adapter + VisualClient + MCP server.

Five scenarios: full workflow, visual fallback, post_comment failure,
MCP tool dispatch, and cross-adapter session isolation.
All mock-based — no real network or API calls.
"""

import json
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
from anbm.engine.router import DecisionRouter
from tests.fixtures.mock_pages import FakePage, FakeElement

GITHUB_URL = "https://github.com"

GITHUB_MANIFEST = {
    "id": "github_issues",
    "name": "GitHub Issues",
    "version": "1.0.0",
    "states": {
        "issue_detail": {
            "check": {"type": "url_matches", "pattern": "/issues/\\d+$"},
            "allowed_actions": ["post_comment", "close_issue"],
        },
        "issue_list": {
            "check": {"type": "url_matches", "pattern": "/issues/?$"},
            "allowed_actions": ["paginate", "open_issue", "filter"],
        },
        "logged_in": {
            "check": {
                "type": "element_present",
                "selector": "[aria-label=\"View profile and more\"]",
            },
            "allowed_actions": ["navigate_to_repo"],
        },
        "not_logged_in": {
            "check": {
                "type": "element_absent",
                "selector": "[aria-label=\"View profile and more\"]",
            },
            "allowed_actions": ["login"],
        },
    },
    "transitions": {
        "not_logged_in": {"login": "logged_in"},
        "logged_in": {"navigate_to_repo": "issue_list"},
        "issue_list": {
            "paginate": "issue_list",
            "open_issue": "issue_detail",
            "filter": "issue_list",
        },
        "issue_detail": {
            "post_comment": "issue_detail",
            "close_issue": "issue_detail",
        },
    },
    "action_idempotency": {
        "login": False,
        "navigate_to_repo": True,
        "paginate": True,
        "open_issue": True,
        "filter": True,
        "post_comment": False,
        "close_issue": False,
    },
}

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


class MockGitHubAdapter(BaseAdapter):
    """Configurable mock for GitHub Issues handler."""

    def __init__(self):
        self._comment_fail = False

    def fail_next_comment(self):
        self._comment_fail = True

    async def extract(self, page, state):
        if state == "issue_list":
            return ExtractResult(
                data={
                    "issues": [
                        {
                            "title": "Fix login bug",
                            "state": "open",
                            "url": "https://github.com/owner/repo/issues/1",
                        }
                    ]
                },
                state="issue_list",
            )
        elif state == "issue_detail":
            return ExtractResult(
                data={
                    "title": "Fix login bug",
                    "body": "Users cannot log in with SSO",
                    "state": "open",
                    "comments": [
                        {"author": "dev1", "text": "Looking into this"}
                    ],
                },
                state="issue_detail",
            )
        elif state in ("not_logged_in", "logged_in"):
            return ExtractResult(data={}, state=state)
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        if action == "login":
            page.url = "https://github.com/"
            page.add_element(
                "[aria-label=\"View profile and more\"]",
                FakeElement(text="user"),
            )
            return ActResult(success=True, next_state="logged_in")

        elif action == "navigate_to_repo":
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            page.url = f"https://github.com/{owner}/{repo}/issues"
            return ActResult(success=True, next_state="issue_list")

        elif action == "paginate":
            return ActResult(success=True, next_state="issue_list")

        elif action == "open_issue":
            page.url = params.get("url", "")
            return ActResult(success=True, next_state="issue_detail")

        elif action == "filter":
            return ActResult(success=True, next_state="issue_list")

        elif action == "post_comment":
            if self._comment_fail:
                self._comment_fail = False
                raise SelectorFailedError("mock comment failure", "#new_comment_field")
            return ActResult(success=True, next_state="issue_detail")

        elif action == "close_issue":
            return ActResult(success=True, next_state="issue_detail")

        raise ValueError(f"act() 不支持操作: {action}")


class MockDoubanAdapter(BaseAdapter):
    """Minimal douban adapter for cross-isolation testing."""

    async def extract(self, page, state):
        return ExtractResult(
            data={"movies": [], "pagination": {"current": 1}},
            state=state,
        )

    async def act(self, page, action, params):
        return ActResult(success=True, next_state="movie_list")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fsm(fsm, page, adapter):
    stack = ExitStack()
    stack.enter_context(patch.object(fsm.browser, "get_page", return_value=page))
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=GITHUB_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


def _page_not_logged_in():
    return FakePage(url=GITHUB_URL, elements={})


def _page_logged_in():
    return FakePage(url=GITHUB_URL, elements={
        "[aria-label=\"View profile and more\"]": FakeElement(text="user"),
    })


def _page_issue_list():
    return FakePage(url="https://github.com/owner/repo/issues", elements={
        "[aria-label=\"View profile and more\"]": FakeElement(text="user"),
    })


def _page_issue_detail():
    return FakePage(url="https://github.com/owner/repo/issues/1", elements={
        "[aria-label=\"View profile and more\"]": FakeElement(text="user"),
    })


# ---------------------------------------------------------------------------
# Scenario 1 — Full workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_workflow():
    """not_logged_in → login → navigate_to_repo → extract → open → comment."""
    fsm = FSMEngine()
    page = _page_not_logged_in()
    adapter = MockGitHubAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(GITHUB_URL, adapter_hint="github_issues")
        sid = created.session_id
        assert created.current_state == "not_logged_in"

        r = await fsm.act(sid, "login", {"username": "u", "password": "p"})
        assert r["execution_path"] == "deterministic"
        assert r["retry"]["attempts"] == 1
        assert r["session_suspended"] is False

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "logged_in"

        r = await fsm.act(sid, "navigate_to_repo", {"owner": "owner", "repo": "repo"})
        assert r["execution_path"] == "deterministic"
        assert r["success"] is True

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "issue_list"

        br = await fsm.browse(sid, "https://github.com/owner/repo/issues")
        assert br["execution_path"] == "deterministic"
        assert br["data"]["issues"][0]["title"] == "Fix login bug"

        r = await fsm.act(sid, "open_issue", {"url": "https://github.com/owner/repo/issues/1"})
        assert r["execution_path"] == "deterministic"

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "issue_detail"

        br = await fsm.browse(sid, "https://github.com/owner/repo/issues/1")
        assert br["execution_path"] == "deterministic"
        assert br["data"]["title"] == "Fix login bug"

        r = await fsm.act(sid, "post_comment", {"body": "Fixed in PR #42"})
        assert r["execution_path"] == "deterministic"
        assert r["retry"]["attempts"] == 1

        sesh = await fsm.session_store.get(sid)
        assert sesh.current_state == "issue_detail"


# ---------------------------------------------------------------------------
# Scenario 2 — Visual fallback with mocked VisualClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_visual_fallback_with_mock_client():
    """Fallback with mocked VisualClient → response includes mock analysis."""
    fsm = FSMEngine()
    page = _page_issue_list()
    adapter = MockGitHubAdapter()

    # Replace router with one that has a mock VisualClient
    mock_vc = AsyncMock()
    mock_vc.analyze.return_value = "Visual analysis: the page shows an empty issue list"
    fsm.router = DecisionRouter(
        retry=fsm.retry,
        session_store=fsm.session_store,
        visual_client=mock_vc,
    )

    # Make adapter.extract always fail to trigger fallback
    class FailingExtractAdapter(MockGitHubAdapter):
        async def extract(self, page, state):
            raise SelectorFailedError("always fails", ".js-issue-row")

    failing_adapter = FailingExtractAdapter()

    with _mock_fsm(fsm, page, failing_adapter):
        created = await fsm.create_session(
            "https://github.com/owner/repo/issues", adapter_hint="github_issues"
        )
        sid = created.session_id

        br = await fsm.browse(sid, "https://github.com/owner/repo/issues")
        assert br["execution_path"] == "visual_fallback"
        assert br["fallback_result"]["visual_model_response"] == \
            "Visual analysis: the page shows an empty issue list"
        assert br["session_suspended"] is True


# ---------------------------------------------------------------------------
# Scenario 3 — Non-idempotent post_comment failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_comment_failure():
    """post_comment fails → requires_human_decision, retry.attempts=1, not suspended."""
    fsm = FSMEngine()
    page = _page_issue_detail()
    adapter = MockGitHubAdapter()
    adapter.fail_next_comment()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(
            "https://github.com/owner/repo/issues/1", adapter_hint="github_issues"
        )
        sid = created.session_id

        # create_session goes to GITHUB_URL, detect_state returns logged_in
        # We need to be in issue_detail for post_comment to be allowed
        # Navigate to issue detail first
        br = await fsm.browse(sid, "https://github.com/owner/repo/issues/1")
        assert br["execution_path"] == "deterministic"

        result = await fsm.act(sid, "post_comment", {"body": "Me too"})
        assert result.get("error") == "non_idempotent_action_failed"
        assert result.get("requires_human_decision") is True
        assert result["retry"]["attempts"] == 1
        assert result["retry"]["succeeded"] is False
        assert result["session_suspended"] is False


# ---------------------------------------------------------------------------
# Scenario 4 — MCP tool dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_tool_dispatch():
    """MCP server's handle_tool_call returns same structure as REST API."""
    import anbm.mcp.server as mcp_server

    fsm = FSMEngine()
    page = _page_not_logged_in()
    adapter = MockGitHubAdapter()

    # Patch the module-level fsm in mcp.server
    with _mock_fsm(fsm, page, adapter) as stack:
        stack.enter_context(patch.object(mcp_server, "fsm", fsm))

        # anbm_browse without session_id (creates new session)
        result = await mcp_server.handle_tool_call("anbm_browse", {
            "url": GITHUB_URL,
            "adapter_hint": "github_issues",
        })
        assert result["isError"] is False
        content = json.loads(result["content"][0]["text"])
        assert "session_id" in content
        assert "current_state" in content
        session_id = content["session_id"]

        # anbm_act: login
        result = await mcp_server.handle_tool_call("anbm_act", {
            "session_id": session_id,
            "action": "login",
            "params": {"username": "u", "password": "p"},
        })
        assert result["isError"] is False
        content = json.loads(result["content"][0]["text"])
        assert content["execution_path"] == "deterministic"
        assert content["session_suspended"] is False

        # anbm_session: check state
        result = await mcp_server.handle_tool_call("anbm_session", {
            "session_id": session_id,
        })
        assert result["isError"] is False
        content = json.loads(result["content"][0]["text"])
        assert content["current_state"] == "logged_in"
        assert content["session_id"] == session_id

        # Unknown tool → error
        result = await mcp_server.handle_tool_call("anbm_unknown", {})
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# Scenario 5 — Cross-adapter session isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_adapter_isolation():
    """Simultaneous douban + github sessions stay independent."""
    fsm = FSMEngine()

    douban_page = FakePage(url="https://movie.douban.com/top250", elements={
        "ol.grid_view": FakeElement(),
    })
    github_page = FakePage(url=GITHUB_URL, elements={})
    douban_adapter = MockDoubanAdapter()
    github_adapter = MockGitHubAdapter()

    session_pages = {}

    async def route_get_page(session_id):
        if session_id in session_pages:
            return session_pages[session_id]
        if "douban" in session_id:
            return douban_page
        if "github" in session_id:
            return github_page
        return FakePage()

    with (
        patch.object(fsm.browser, "get_page", route_get_page),
        patch.object(fsm.adapter_loader, "load_manifest") as mock_load_manifest,
        patch.object(fsm.adapter_loader, "load_handler") as mock_load_handler,
    ):
        # --- Douban session ---
        mock_load_manifest.return_value = DOUBAN_MANIFEST
        mock_load_handler.return_value = douban_adapter
        r_a = await fsm.create_session(
            "https://movie.douban.com/top250", adapter_hint="douban_movie"
        )
        sid_a = r_a.session_id
        session_pages[sid_a] = douban_page
        assert r_a.current_state == "movie_list"

        # --- GitHub session ---
        mock_load_manifest.return_value = GITHUB_MANIFEST
        mock_load_handler.return_value = github_adapter
        r_b = await fsm.create_session(GITHUB_URL, adapter_hint="github_issues")
        sid_b = r_b.session_id
        session_pages[sid_b] = github_page
        assert r_b.current_state == "not_logged_in"

        # Verify both sessions exist and are independent
        sesh_a = await fsm.session_store.get(sid_a)
        sesh_b = await fsm.session_store.get(sid_b)
        assert sesh_a.current_state == "movie_list"
        assert sesh_b.current_state == "not_logged_in"

        # Act on GitHub: login
        mock_load_manifest.return_value = GITHUB_MANIFEST
        mock_load_handler.return_value = github_adapter
        act_b = await fsm.act(sid_b, "login", {"username": "u", "password": "p"})
        assert act_b["execution_path"] == "deterministic"

        sesh_a = await fsm.session_store.get(sid_a)
        sesh_b = await fsm.session_store.get(sid_b)
        assert sesh_a.current_state == "movie_list"  # Unchanged
        assert sesh_b.current_state == "logged_in"  # Changed

        # Act on Douban: paginate
        mock_load_manifest.return_value = DOUBAN_MANIFEST
        mock_load_handler.return_value = douban_adapter
        act_a = await fsm.act(sid_a, "paginate")
        assert act_a["execution_path"] == "deterministic"

        sesh_a = await fsm.session_store.get(sid_a)
        sesh_b = await fsm.session_store.get(sid_b)
        assert sesh_a.current_state == "movie_list"  # Stayed on list
        assert sesh_b.current_state == "logged_in"   # Unchanged
