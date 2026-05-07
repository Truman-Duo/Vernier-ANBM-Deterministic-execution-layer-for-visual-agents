"""Fake Playwright Page/Element classes for integration tests."""
from html.parser import HTMLParser


class FakeLocator:
    """Mimics playwright.async_api.Locator with minimal surface."""

    def __init__(self, count: int = 0):
        self._count = count

    async def count(self):
        return self._count


class FakeElement:
    """Mimics playwright.async_api.ElementHandle with minimal surface."""

    def __init__(self, text="", attributes=None, children=None):
        self._text = text
        self._attributes = attributes or {}
        self._children = children or {}

    async def text_content(self):
        return self._text

    async def get_attribute(self, name):
        return self._attributes.get(name)

    async def query_selector(self, selector):
        child = self._children.get(selector)
        if child is not None:
            return child
        if hasattr(self, '_node'):
            return _query_selector_from_tree(self._node, selector)
        return None

    async def click(self):
        pass

    async def inner_html(self):
        if hasattr(self, '_node'):
            return self._node.get_text()
        return ""

    async def evaluate(self, expression: str):
        """支持 tagName/classList/innerHTML evaluate。"""
        if hasattr(self, '_node'):
            node = self._node
            if 'tagName' in expression:
                return node.tag
            if 'classList' in expression:
                return node.attrs.get('class', '')
            if 'innerHTML' in expression:
                return node.inner_html()
        raise NotImplementedError(f"FakeElement 不支持 evaluate({expression!r})")


class HtmlNode:
    """Minimal HTML tree node with tag, attributes, text, children."""

    def __init__(self, tag="", attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.text = ""
        self.parent = parent
        self.children: list["HtmlNode"] = []

    def add_child(self, child: "HtmlNode"):
        child.parent = self
        self.children.append(child)

    def get_text(self) -> str:
        parts = []
        if self.text.strip():
            parts.append(self.text.strip())
        for child in self.children:
            t = child.get_text()
            if t.strip():
                parts.append(t.strip())
        return " ".join(parts)

    def inner_html(self) -> str:
        """返回该节点 innerHTML 的近似字符串，用于 fingerprint 比较。"""
        parts = []
        for child in self.children:
            parts.append(f"<{child.tag}")
            for key, val in child.attrs.items():
                parts.append(f' {key}="{val}"')
            parts.append(">")
            inner = child.inner_html()
            if inner:
                parts.append(inner)
            elif child.text:
                parts.append(child.text)
            parts.append(f"</{child.tag}>")
        return "".join(parts)


def _matches_selector(node: HtmlNode, selector: str) -> bool:
    """Check if an HtmlNode matches a single CSS selector (no combinator).

    Supported: tag, .class, #id, [attr], [attr="val"], [attr^="val"].
    """
    rest = selector

    # tag name
    if rest and rest[0].isalpha():
        tag_end = 0
        while tag_end < len(rest) and (rest[tag_end].isalnum() or rest[tag_end] == '-'):
            tag_end += 1
        tag = rest[:tag_end]
        if node.tag.lower() != tag.lower():
            return False
        rest = rest[tag_end:]

    while rest:
        if rest.startswith('.'):
            end = 1
            while end < len(rest) and (rest[end].isalnum() or rest[end] in '-_'):
                end += 1
            cls = rest[1:end]
            node_classes = (node.attrs.get('class') or '').split()
            if cls not in node_classes:
                return False
            rest = rest[end:]
        elif rest.startswith('#'):
            end = 1
            while end < len(rest) and (rest[end].isalnum() or rest[end] in '-_'):
                end += 1
            id_val = rest[1:end]
            if node.attrs.get('id') != id_val:
                return False
            rest = rest[end:]
        elif rest.startswith('['):
            end = rest.index(']')
            attr_expr = rest[1:end]
            if '*=' in attr_expr:
                key, val = attr_expr.split('*=', 1)
                val = val.strip().strip('\"\'')
                actual = node.attrs.get(key.strip(), '')
                if val not in actual:
                    return False
            elif '^=' in attr_expr:
                key, val = attr_expr.split('^=', 1)
                val = val.strip().strip('\"\'')
                actual = node.attrs.get(key.strip(), '')
                if not actual.startswith(val):
                    return False
            elif '=' in attr_expr:
                key, val = attr_expr.split('=', 1)
                val = val.strip().strip('\"\'')
                if node.attrs.get(key.strip()) != val:
                    return False
            else:
                # [attr] — existence check
                if attr_expr.strip() not in node.attrs:
                    return False
            rest = rest[end + 1:]
        else:
            break

    return True


def _query_selector_from_tree(root: HtmlNode, selector: str):
    """Walk tree, return first match for a CSS selector.

    Supports combinator '>' for direct child (single level only).
    """
    if '>' in selector:
        parent_sel, child_sel = selector.rsplit('>', 1)
        parent_sel = parent_sel.strip()
        child_sel = child_sel.strip()
        parent_result = _query_selector_from_tree(root, parent_sel)
        if parent_result is None:
            return None
        parent_node = getattr(parent_result, '_node', None)
        if parent_node is None:
            return None
        for child in parent_node.children:
            if _matches_selector(child, child_sel):
                el = FakeElement(
                    text=child.get_text(),
                    attributes=dict(child.attrs),
                )
                el._node = child
                return el
        return None

    # depth-first walk
    stack = [root]
    while stack:
        node = stack.pop()
        if _matches_selector(node, selector):
            el = FakeElement(
                text=node.get_text(),
                attributes=dict(node.attrs),
            )
            el._node = node
            return el
        stack.extend(reversed(node.children))
    return None


def _query_selector_all_from_tree(root: HtmlNode, selector: str):
    """Walk tree, return all matches for a CSS selector.

    Supports combinator '>' for direct child (single level only).
    """
    if '>' in selector:
        parent_sel, child_sel = selector.rsplit('>', 1)
        parent_sel = parent_sel.strip()
        child_sel = child_sel.strip()
        parents = _query_selector_all_from_tree(root, parent_sel)
        results = []
        for p in parents:
            pnode = getattr(p, '_node', None)
            if pnode is None:
                continue
            for child in pnode.children:
                if _matches_selector(child, child_sel):
                    el = FakeElement(
                        text=child.get_text(),
                        attributes=dict(child.attrs),
                    )
                    el._node = child
                    results.append(el)
        return results

    results = []
    stack = [root]
    while stack:
        node = stack.pop()
        if _matches_selector(node, selector):
            el = FakeElement(
                text=node.get_text(),
                attributes=dict(node.attrs),
            )
            el._node = node
            results.append(el)
        stack.extend(reversed(node.children))
    return results


class _SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = HtmlNode(tag="__root__")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = HtmlNode(tag=tag, attrs=dict(attrs))
        self._stack[-1].add_child(node)
        self._stack.append(node)

    def handle_endtag(self, tag):
        if len(self._stack) > 1 and self._stack[-1].tag == tag:
            self._stack.pop()

    def handle_data(self, data):
        if data.strip():
            if self._stack[-1].text:
                self._stack[-1].text += " " + data.strip()
            else:
                self._stack[-1].text = data.strip()


class FakeAccessibility:
    """Mimics playwright accessibility snapshot."""

    def __init__(self, snapshot_result: dict | None = None):
        self._snapshot_result = snapshot_result

    async def snapshot(self):
        return self._snapshot_result


class FakePage:
    """Mimics playwright.async_api.Page with configurable url and elements."""

    def __init__(self, url="about:blank", elements=None, html_root=None, locators=None, ax_snapshot=None):
        self.url = url
        self._elements = elements or {}
        self._html_root = html_root
        self._locators = locators or {}
        self.accessibility = FakeAccessibility(ax_snapshot)

    @classmethod
    def from_html(cls, html_string: str, url: str = "about:blank") -> "FakePage":
        """Parse HTML string and build a FakePage backed by an element tree.

        query_selector / query_selector_all walk the tree with full selector
        matching support (tag, .class, #id, [attr], [attr=val], [attr^=val],
        parent > child).
        """
        parser = _SimpleHTMLParser()
        parser.feed(html_string)
        return cls(url=url, html_root=parser.root)

    async def query_selector(self, selector):
        if self._html_root is not None:
            return _query_selector_from_tree(self._html_root, selector)
        return self._elements.get(selector)

    async def query_selector_all(self, selector):
        if self._html_root is not None:
            return _query_selector_all_from_tree(self._html_root, selector)
        result = self._elements.get(selector)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    def add_element(self, selector, element):
        self._elements[selector] = element

    def remove_element(self, selector):
        self._elements.pop(selector, None)

    async def goto(self, url, **kwargs):
        self.url = url

    async def wait_for_load_state(self, state=None, **kwargs):
        pass

    async def wait_for_timeout(self, timeout: int):
        pass

    async def wait_for_selector(self, selector, timeout=None):
        pass

    def get_by_role(self, role: str, name: str | None = None):
        """返回 FakeLocator，支持 .count()。

        如果 elements 中注册了 get_by_role 的返回数据则使用之，
        否则返回 count=0 的 locator。
        """
        key = f"role={role}"
        if name:
            key = f"role={role},name={name}"
        locator = self._locators.get(key)
        if locator is not None:
            return locator
        return FakeLocator(count=0)

    async def screenshot(self, type="jpeg", quality=80):
        return b"fake_screenshot_data"

    async def evaluate(self, expression, arg=None):
        """简易 evaluate：支持 origin、fingerprint、scroll 等常见模式。"""
        if expression == "window.location.origin":
            parts = self.url.split("/")
            return f"{parts[0]}//{parts[2]}" if len(parts) > 2 else self.url
        if "=>" in expression or "function" in expression:
            expr_lower = expression.lower()
            if "fingerprint" in expr_lower or "innerhtml" in expr_lower:
                return {"fingerprint": "mock_fp", "ids": ["1", "2", "3"]}
            if "scrolltop" in expr_lower or "scrollto" in expr_lower or "scroll" in expr_lower:
                return None  # scroll 操作在 mock 中为 no-op
            return arg if arg is not None else {}
        return expression
