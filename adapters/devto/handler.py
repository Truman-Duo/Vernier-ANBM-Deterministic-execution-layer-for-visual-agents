"""
DEV.to Adapter
选择器选择理由：
- article_detail state: #article-body — 文章正文容器，唯一 ID
- feed state: div.articles-list — 首页文章流容器
- not_logged_in state: a[aria-label="Log in"] — 未登录时导航栏显示"Log in"链接
- logged_in state: element_absent a[aria-label="Log in"] — 登录后链接消失
- 文章卡片: div.crayons-story — 含 data-feed-content-id
- 点赞按钮: .reaction-like — 类语义化名，detail 页反应区域
- 收藏按钮: .crayons-reaction--readinglist — 语义化 ARIA 友好类名
"""
from urllib.parse import urlparse

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "feed":
            return await self._extract_feed(page)
        elif state == "article_detail":
            return await self._extract_article_detail(page)
        elif state == "not_found":
            return ExtractResult(
                data={"articles": [], "has_more": False},
                state="not_found",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "login":
            return await self._act_login(page, params)
        elif action == "open_article":
            return await self._act_open_article(page, params)
        elif action == "like_post":
            return await self._act_like_post(page)
        elif action == "save_post":
            return await self._act_save_post(page)
        elif action == "paginate":
            return await self._act_paginate(page)
        elif action == "extract_content":
            data = await self._extract_article_detail(page)
            return ActResult(success=True, next_state="article_detail", data=data.data)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_feed(self, page):
        container = await page.query_selector("div.articles-list")
        if not container:
            raise SelectorFailedError(
                "找不到文章流容器",
                selector="div.articles-list",
            )

        article_els = await page.query_selector_all("div.crayons-story")
        articles = []
        for el in article_els:
            article_id = ""
            feed_id = await el.get_attribute("data-feed-content-id")
            if feed_id:
                article_id = feed_id

            title_el = await el.query_selector("h2.crayons-story__title a")
            title = (await title_el.text_content()).strip() if title_el else ""
            url = ""
            if title_el:
                url = await title_el.get_attribute("href") or ""

            reactions_count = 0
            reactions_el = await el.query_selector(".aggregate_reactions_counter")
            if reactions_el:
                try:
                    text = (await reactions_el.text_content()).strip()
                    if text:
                        reactions_count = int(text)
                except (ValueError, TypeError):
                    pass

            reading_list = False
            save_el = await el.query_selector(".crayons-story__save .bookmark-button")
            if save_el:
                cls = await save_el.get_attribute("class") or ""
                reading_list = "reacted" in cls

            articles.append({
                "id": article_id,
                "title": title,
                "url": url,
                "reactions_count": reactions_count,
                "reading_list": reading_list,
            })

        return ExtractResult(
            data={"articles": articles, "has_more": len(article_els) > 0},
            state="feed",
        )

    async def _extract_article_detail(self, page):
        body_el = await page.query_selector("#article-body")
        if not body_el:
            raise SelectorFailedError(
                "找不到文章正文",
                selector="#article-body",
            )
        body_text = await body_el.text_content()

        title = await page.evaluate(
            "() => document.querySelector('meta[property=\"og:title\"]')?.content || ''"
        )

        article_id = await page.evaluate(
            "() => document.querySelector('[data-article-id]')?.getAttribute('data-article-id') || ''"
        )

        reactions_count = 0
        count_el = await page.query_selector("#reaction_engagement_like_count")
        if count_el:
            try:
                text = (await count_el.text_content()).strip()
                if text:
                    reactions_count = int(text)
            except (ValueError, TypeError):
                pass

        reading_list = False
        save_btn = await page.query_selector(".crayons-reaction--readinglist")
        if save_btn:
            cls = await save_btn.get_attribute("class") or ""
            reading_list = "reacted" in cls

        return ExtractResult(
            data={
                "id": article_id,
                "title": title,
                "body_text": body_text.strip() if body_text else "",
                "reactions_count": reactions_count,
                "reading_list": reading_list,
            },
            state="article_detail",
        )

    async def _act_login(self, page, params: dict) -> ActResult:
        login_btn = await page.query_selector("a[aria-label=\"Log in\"]")
        if not login_btn:
            raise SelectorFailedError(
                "找不到登录按钮",
                selector="a[aria-label=\"Log in\"]",
            )
        href = await login_btn.get_attribute("href") or "/enter"
        login_url = f"https://dev.to{href}" if href.startswith("/") else href
        await page.goto(login_url)
        await page.wait_for_load_state("networkidle", timeout=15000)

        username_input = await page.query_selector("input[name=\"user[email]\"]")
        if not username_input:
            username_input = await page.query_selector("input[type=\"email\"]")
        if not username_input:
            raise SelectorFailedError(
                "找不到邮箱输入框",
                selector="input[name=\"user[email]\"]",
            )
        password_input = await page.query_selector("input[name=\"user[password]\"]")
        if not password_input:
            password_input = await page.query_selector("input[type=\"password\"]")
        if not password_input:
            raise SelectorFailedError(
                "找不到密码输入框",
                selector="input[name=\"user[password]\"]",
            )

        await username_input.fill(params.get("username", ""))
        await password_input.fill(params.get("password", ""))
        submit_btn = await page.query_selector("button[type=\"submit\"]")
        if submit_btn:
            await submit_btn.click()
        else:
            await password_input.press("Enter")

        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="logged_in")

    async def _act_open_article(self, page, params: dict) -> ActResult:
        url = params.get("url", "")
        if not url:
            raise SelectorFailedError(
                "open_article 需要 url 参数",
                selector=None,
            )
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="article_detail")

    async def _act_like_post(self, page):
        like_btn = await page.query_selector(".reaction-like")
        if not like_btn:
            raise SelectorFailedError(
                "找不到点赞按钮",
                selector=".reaction-like",
            )
        await like_btn.click()
        await page.wait_for_load_state("networkidle", timeout=10000)
        return ActResult(
            success=True,
            next_state="article_detail",
            side_effect_hint="reactions_count_incremented",
        )

    async def _act_save_post(self, page):
        save_btn = await page.query_selector(".crayons-reaction--readinglist")
        if not save_btn:
            raise SelectorFailedError(
                "找不到收藏按钮",
                selector=".crayons-reaction--readinglist",
            )
        await save_btn.click()
        await page.wait_for_load_state("networkidle", timeout=10000)
        return ActResult(
            success=True,
            next_state="article_detail",
            side_effect_hint="reading_list_updated",
        )

    async def _act_paginate(self, page):
        next_link = await page.query_selector("a[rel=\"next\"]")
        if not next_link:
            raise SelectorFailedError(
                "找不到翻页链接",
                selector="a[rel=\"next\"]",
            )
        await next_link.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="feed")
