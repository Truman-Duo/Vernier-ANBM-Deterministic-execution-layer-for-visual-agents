import pytest

from anbm.engine.validator import StateValidator


class FakeElement:
    def __init__(self, present=True):
        self._present = present

    def __await__(self):
        async def _():
            return self
        return _().__await__()


class FakePage:
    def __init__(self, url: str = "", elements: dict[str, bool] = None):
        self.url = url
        self._elements = elements or {}

    async def query_selector(self, selector: str):
        present = self._elements.get(selector, False)
        if present:
            return FakeElement()
        return None


@pytest.fixture
def validator():
    return StateValidator()


@pytest.fixture
def manifest():
    return {
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "/list"},
                "also_check": {
                    "type": "element_present",
                    "selector": "ol.grid_view",
                },
                "allowed_actions": ["paginate", "extract"],
            },
            "detail": {
                "check": {"type": "url_matches", "pattern": "/detail/\\d+"},
                "allowed_actions": ["extract_detail"],
            },
            "login": {
                "check": {"type": "element_present", "selector": "#login_form"},
                "allowed_actions": ["login"],
            },
            "logged_out": {
                "check": {"type": "element_absent", "selector": "[data-user]"},
                "allowed_actions": ["login"],
            },
        },
        "action_idempotency": {
            "paginate": True,
            "extract": True,
        },
    }


@pytest.mark.asyncio
async def test_detect_state_url_contains(validator, manifest):
    page = FakePage(url="https://example.com/list", elements={"ol.grid_view": True})
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "list"
    assert detected_by["check_type"] == "url_contains"
    assert detected_by["value"] == "/list"


@pytest.mark.asyncio
async def test_detect_state_url_matches(validator, manifest):
    page = FakePage(url="https://example.com/detail/12345")
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "detail"
    assert detected_by["check_type"] == "url_matches"
    assert detected_by["pattern"] == "/detail/\\d+"


@pytest.mark.asyncio
async def test_detect_state_element_present(validator, manifest):
    page = FakePage(url="https://example.com/login", elements={"#login_form": True})
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "login"
    assert detected_by["check_type"] == "element_present"
    assert detected_by["selector"] == "#login_form"


@pytest.mark.asyncio
async def test_detect_state_element_absent(validator, manifest):
    page = FakePage(url="https://example.com/other")
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "logged_out"
    assert detected_by["check_type"] == "element_absent"
    assert detected_by["selector"] == "[data-user]"


@pytest.mark.asyncio
async def test_detect_state_unknown(validator, manifest):
    page = FakePage(url="https://example.com/unknown", elements={"[data-user]": True})
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "unknown"
    assert detected_by is None


@pytest.mark.asyncio
async def test_validate_transition_ok(validator, manifest):
    page = FakePage(url="https://example.com/list", elements={"ol.grid_view": True})
    assert await validator.validate_transition(page, manifest, "list") is True


@pytest.mark.asyncio
async def test_validate_transition_fail(validator, manifest):
    page = FakePage(url="https://example.com/unknown")
    assert await validator.validate_transition(page, manifest, "list") is False


def test_check_action_allowed(validator, manifest):
    assert validator.check_action_allowed(manifest, "list", "paginate") is True
    assert validator.check_action_allowed(manifest, "list", "login") is False
    assert validator.check_action_allowed(manifest, "detail", "extract_detail") is True


def test_get_idempotency(validator, manifest):
    assert validator.get_idempotency(manifest, "paginate") is True
    assert validator.get_idempotency(manifest, "unknown_action") is False


@pytest.mark.asyncio
async def test_also_check_both_pass(validator):
    """check + also_check 都满足，正确识别为目标状态。"""
    manifest = {
        "states": {
            "target": {
                "check": {"type": "url_contains", "value": "/target"},
                "also_check": {
                    "type": "element_present",
                    "selector": ".required-el",
                },
            },
            "fallback": {
                "check": {"type": "url_contains", "value": "/target"},
            },
        }
    }
    page = FakePage(url="/target", elements={".required-el": True})
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "target"
    assert detected_by["check_type"] == "url_contains"


@pytest.mark.asyncio
async def test_also_check_main_pass_secondary_fail(validator):
    """check 满足但 also_check 不满足，不识别为该状态，继续遍历。"""
    manifest = {
        "states": {
            "target": {
                "check": {"type": "url_contains", "value": "/target"},
                "also_check": {
                    "type": "element_present",
                    "selector": ".required-el",
                },
            },
            "fallback": {
                "check": {"type": "url_contains", "value": "/target"},
            },
        }
    }
    page = FakePage(url="/target", elements={".required-el": False})
    state, detected_by = await validator.detect_state(page, manifest)
    assert state == "fallback"
    assert detected_by["check_type"] == "url_contains"


@pytest.mark.asyncio
async def test_aria_present_found(validator):
    """page mock 包含 role=list 的元素，aria_present 返回 True。"""
    from tests.fixtures.mock_pages import FakePage as MockPage, FakeLocator

    page = MockPage(url="https://example.com")
    page._locators["role=list"] = FakeLocator(count=1)

    check = {"type": "aria_present", "role": "list"}
    assert await validator._check_satisfied(page, check) is True


@pytest.mark.asyncio
async def test_aria_present_not_found(validator):
    """page mock 不含 role=list 的元素，aria_present 返回 False。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    page = MockPage(url="https://example.com")

    check = {"type": "aria_present", "role": "list"}
    assert await validator._check_satisfied(page, check) is False


@pytest.mark.asyncio
async def test_aria_present_with_name(validator):
    """check 包含 role 和 name，get_by_role 带 name 参数匹配。"""
    from tests.fixtures.mock_pages import FakePage as MockPage, FakeLocator

    page = MockPage(url="https://example.com")
    page._locators["role=list,name=电影列表"] = FakeLocator(count=1)

    check = {"type": "aria_present", "role": "list", "name": "电影列表"}
    assert await validator._check_satisfied(page, check) is True


@pytest.mark.asyncio
async def test_aria_absent(validator):
    """aria_absent 要求元素不存在（count=0）才返回 True。"""
    from tests.fixtures.mock_pages import FakePage as MockPage, FakeLocator

    page = MockPage(url="https://example.com")
    page._locators["role=dialog"] = FakeLocator(count=1)

    check = {"type": "aria_absent", "role": "dialog"}
    # 元素存在 (count=1)，aria_absent 应返回 False
    assert await validator._check_satisfied(page, check) is False


# ── Fingerprint 缓存测试 ──────────────────────────────────────────────

FP_MANIFEST = {
    "states": {
        "list": {
            "check": {"type": "url_contains", "value": "/list"},
            "also_check": {
                "type": "element_present", "selector": "ol.grid_view",
            },
        },
        "detail": {
            "check": {"type": "url_contains", "value": "/detail"},
        },
    },
}


@pytest.mark.asyncio
async def test_fingerprint_cache_hit(validator):
    """同一 fingerprint 第二次调用直接返回缓存结果，不走全量遍历。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    page = MockPage.from_html(
        '<html><body><ol class="grid_view"><li>item</li></ol></body></html>',
        url="https://example.com/list",
    )
    cache: dict = {}

    state1, _ = await validator.detect_state(page, FP_MANIFEST, cache)
    assert state1 == "list"

    # 第二次调用 — 相同 URL + DOM → cache hit
    state2, _ = await validator.detect_state(page, FP_MANIFEST, cache)
    assert state2 == "list"
    assert len(cache) == 1, "缓存应只有一条记录"


@pytest.mark.asyncio
async def test_fingerprint_cache_miss_different_url(validator):
    """URL 不同 → fingerprint 不同 → cache miss，重新 detect_state。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    page_list = MockPage.from_html(
        '<html><body><ol class="grid_view"><li>item</li></ol></body></html>',
        url="https://example.com/list",
    )
    page_detail = MockPage.from_html(
        '<html><body><div class="detail">content</div></body></html>',
        url="https://example.com/detail",
    )
    cache: dict = {}

    state1, _ = await validator.detect_state(page_list, FP_MANIFEST, cache)
    assert state1 == "list"

    # 不同 URL → cache miss
    state2, _ = await validator.detect_state(page_detail, FP_MANIFEST, cache)
    assert state2 == "detail"
    assert len(cache) == 2, "两个不同 fingerprint 应分别缓存"


@pytest.mark.asyncio
async def test_fingerprint_cache_updates_on_miss(validator):
    """cache miss 后结果正确写入缓存。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    page = MockPage.from_html(
        '<html><body><ol class="grid_view"><li>item</li></ol></body></html>',
        url="https://example.com/list",
    )
    cache: dict = {}

    # cache miss
    state, detected_by = await validator.detect_state(page, FP_MANIFEST, cache)
    assert state == "list"

    # 验证缓存内容
    assert len(cache) == 1
    fp = list(cache.keys())[0]
    assert isinstance(fp, str) and len(fp) == 32
    cached_state, cached_detected_by = cache[fp]
    assert cached_state == "list"


@pytest.mark.asyncio
async def test_compute_fingerprint_dom_change(validator):
    """DOM 变化 → fingerprint 不同。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    html_with = '<html><body><ol class="grid_view"><li>A</li></ol></body></html>'
    html_without = '<html><body><div>no list</div></body></html>'

    page_a = MockPage.from_html(html_with, url="/list")
    page_b = MockPage.from_html(html_without, url="/list")

    fp_a = await validator._compute_fingerprint(page_a, FP_MANIFEST)
    fp_b = await validator._compute_fingerprint(page_b, FP_MANIFEST)

    assert fp_a != fp_b, "ol.grid_view 存在与否应产生不同 fingerprint"


@pytest.mark.asyncio
async def test_compute_fingerprint_container_selector(validator):
    """container_selector 指定时只计算该容器的 innerHTML，含 URL + innerHTML。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    html = (
        '<html><body>'
        '<div class="scrollable" role="feed">'
        '<article data-id="1">item 1</article>'
        '<article data-id="2">item 2</article>'
        '</div>'
        '<footer>footer content</footer>'
        '</body></html>'
    )
    page = MockPage.from_html(html, url="https://example.com/public")

    fp = await validator._compute_fingerprint(page, {}, container_selector='[role="feed"]')
    assert isinstance(fp, str) and len(fp) == 32
    # Same URL + same container DOM → same fingerprint
    fp2 = await validator._compute_fingerprint(page, {}, container_selector='[role="feed"]')
    assert fp == fp2


@pytest.mark.asyncio
async def test_compute_fingerprint_container_selector_dom_change(validator):
    """容器 DOM 变化 → fingerprint 不同。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    html_a = (
        '<html><body>'
        '<div class="scrollable" role="feed">'
        '<article data-id="1">item 1</article>'
        '</div>'
        '</body></html>'
    )
    html_b = (
        '<html><body>'
        '<div class="scrollable" role="feed">'
        '<article data-id="1">item 1</article>'
        '<article data-id="2">item 2</article>'
        '</div>'
        '</body></html>'
    )
    page_a = MockPage.from_html(html_a, url="https://example.com/public")
    page_b = MockPage.from_html(html_b, url="https://example.com/public")

    fp_a = await validator._compute_fingerprint(page_a, {}, container_selector='[role="feed"]')
    fp_b = await validator._compute_fingerprint(page_b, {}, container_selector='[role="feed"]')
    assert fp_a != fp_b, "容器内 article 数量变化应产生不同 fingerprint"


@pytest.mark.asyncio
async def test_compute_fingerprint_container_not_found(validator):
    """container_selector 未匹配 → 只基于 URL 生成 fingerprint（不抛异常）。"""
    from tests.fixtures.mock_pages import FakePage as MockPage

    page = MockPage.from_html(
        '<html><body><div>no matching container</div></body></html>',
        url="https://example.com/public",
    )
    fp = await validator._compute_fingerprint(page, {}, container_selector=".nonexistent")
    assert isinstance(fp, str) and len(fp) == 32
