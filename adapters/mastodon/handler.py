"""
Mastodon Adapter (via hachyderm.io)
选择器选择理由：
- feed_partial state: article[data-id] — Mastodon 时间线中的状态条目，data-id 为唯一标识
- feed_exhausted state: 无限滚动耗尽后无更多状态可加载（DOM 上 article 仍存在但已到底）
- 状态内容: .status__content — 嘟文的 HTML 内容
- 显示名称: .display-name — 作者显示名（@ 用户显示名）
- 时间链接: a.status__relative-time — 嘟文链接（相对时间，含 href）
- feed 容器: [role="feed"] — Mastodon 时间线滚动容器
"""
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


CONTAINER_SELECTORS = ['[role="feed"]', ".scrollable"]


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "feed_partial":
            return await self._extract_feed(page)
        if state == "feed_exhausted":
            return ExtractResult(
                data={"statuses": [], "has_more": False},
                state="feed_exhausted",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "scroll_load_more":
            return await self._act_scroll_load_more(page)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_feed(self, page):
        articles = await page.query_selector_all("article[data-id]")
        if not articles:
            raise SelectorFailedError(
                "找不到 feed 中的状态条目",
                selector="article[data-id]",
            )

        origin = await page.evaluate("window.location.origin")
        statuses = []
        for article in articles:
            status_id = await article.get_attribute("data-id") or ""

            author_el = await article.query_selector(".display-name")
            author = (await author_el.text_content()).strip() if author_el else ""

            content_el = await article.query_selector(".status__content")
            content = (await content_el.text_content()).strip() if content_el else ""

            url_el = await article.query_selector("a.status__relative-time")
            url = ""
            if url_el:
                href = await url_el.get_attribute("href") or ""
                url = origin + href if href.startswith("/") else href

            time_el = await article.query_selector("time")
            created_at = await time_el.get_attribute("datetime") if time_el else ""

            statuses.append({
                "id": status_id,
                "author": author,
                "content": content,
                "url": url,
                "created_at": created_at,
            })

        return ExtractResult(
            data={"statuses": statuses, "has_more": True},
            state="feed_partial",
        )

    async def _act_scroll_load_more(self, page):
        # 获取滚动前状态：container fingerprint + article IDs
        before = await page.evaluate(
            """(selectors) => {
                let container = null;
                for (const sel of selectors) {
                    container = document.querySelector(sel);
                    if (container) break;
                }
                const fp = container ? container.innerHTML : document.body.innerHTML.substring(0, 5000);
                const ids = Array.from(document.querySelectorAll('article[data-id]'))
                    .map(el => el.dataset.id);
                return { fingerprint: fp, ids: ids };
            }""",
            CONTAINER_SELECTORS,
        )

        # 执行滚动到底部
        await page.evaluate(
            """(selectors) => {
                let container = null;
                for (const sel of selectors) {
                    container = document.querySelector(sel);
                    if (container) break;
                }
                if (container) {
                    container.scrollTop = container.scrollHeight;
                } else {
                    window.scrollTo(0, document.body.scrollHeight);
                }
            }""",
            CONTAINER_SELECTORS,
        )

        # P3: timeout 安全网 — 等待内容加载
        await page.wait_for_timeout(2000)

        # 获取滚动后状态
        after = await page.evaluate(
            """(selectors) => {
                let container = null;
                for (const sel of selectors) {
                    container = document.querySelector(sel);
                    if (container) break;
                }
                const fp = container ? container.innerHTML : document.body.innerHTML.substring(0, 5000);
                const ids = Array.from(document.querySelectorAll('article[data-id]'))
                    .map(el => el.dataset.id);
                return { fingerprint: fp, ids: ids };
            }""",
            CONTAINER_SELECTORS,
        )

        # P1: fingerprint 未变 → 确实无新内容
        if after["fingerprint"] == before["fingerprint"]:
            return ActResult(
                success=True,
                next_state="feed_partial",
                data={"loaded_count": 0, "has_more": False},
            )

        # P2: 唯一 ID 去重检测
        before_ids = set(before["ids"])
        new_ids = [id_ for id_ in after["ids"] if id_ not in before_ids]
        loaded_count = len(new_ids)

        return ActResult(
            success=True,
            next_state="feed_partial",
            data={"loaded_count": loaded_count, "has_more": loaded_count > 0},
        )
