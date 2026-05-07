"""
Codeberg Adapter (Forgejo)
选择器选择理由：
- issue_list state: .page-content.repository.issue-list — issue 列表页容器
- issue_detail state: .page-content.repository.view.issue — issue 详情页容器
- not_logged_in state: a[href^="/user/login"] — 导航栏 Sign in 链接
- logged_in state: element_absent a[href^="/user/login"] — 登录后链接消失
- issue 卡片: div.issue-card[data-issue] — 含 data-issue ID
- assign 按钮: .select-assignees-modify.dropdown — 侧边栏 assign 下拉
- 标签过滤: a.label-filter-item[data-label-id] — 标签列表中的过滤链接
- 翻页: a[rel="next"] — Forgejo 标准分页链接
"""
from urllib.parse import urlparse

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "issue_list":
            return await self._extract_issue_list(page)
        elif state == "issue_detail":
            return await self._extract_issue_detail(page)
        elif state in ("not_logged_in", "logged_in"):
            return ExtractResult(data={}, state=state)
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "login":
            return await self._act_login(page, params)
        elif action == "open_issue":
            return await self._act_open_issue(page, params)
        elif action == "assign_issue":
            return await self._act_assign_issue(page, params)
        elif action == "paginate":
            return await self._act_paginate(page)
        elif action == "filter_by_label":
            return await self._act_filter_by_label(page, params)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_issue_list(self, page):
        cards = await page.query_selector_all("div.issue-card")
        if not cards:
            raise SelectorFailedError(
                "找不到 issue 卡片",
                selector="div.issue-card",
            )

        issues = []
        for card in cards:
            issue_id = await card.get_attribute("data-issue") or ""

            title_el = await card.query_selector(".issue-card-title")
            title = (await title_el.text_content()).strip() if title_el else ""

            url = ""
            if title_el:
                href = await title_el.get_attribute("href") or ""
                if href:
                    url = f"https://codeberg.org{href}" if href.startswith("/") else href

            state = "open"
            state_icon = await card.query_selector('[class*="octicon-issue-closed"]')
            if state_icon:
                state = "closed"

            issues.append({
                "id": issue_id,
                "title": title,
                "url": url,
                "state": state,
            })

        return ExtractResult(
            data={"issues": issues},
            state="issue_list",
        )

    async def _extract_issue_detail(self, page):
        title_el = await page.query_selector("#issue-title-display")
        if not title_el:
            raise SelectorFailedError(
                "找不到 issue 标题",
                selector="#issue-title-display",
            )
        title = (await title_el.text_content()).strip()

        body_el = await page.query_selector(".comment-container")
        body = (await body_el.text_content()).strip() if body_el else ""

        state_el = await page.query_selector(".issue-state-label")
        state = (await state_el.text_content()).strip() if state_el else "open"

        assignee_els = await page.query_selector_all(".ui.assignees.list .assignee")
        assignees = []
        for el in assignee_els:
            name = (await el.text_content()).strip()
            if name:
                assignees.append(name)

        return ExtractResult(
            data={
                "title": title,
                "body": body,
                "state": state,
                "assignees": assignees,
            },
            state="issue_detail",
        )

    async def _act_login(self, page, params: dict) -> ActResult:
        login_link = await page.query_selector("a[href^=\"/user/login\"]")
        if not login_link:
            raise SelectorFailedError(
                "找不到登录链接",
                selector="a[href^=\"/user/login\"]",
            )
        href = await login_link.get_attribute("href") or "/user/login"
        login_url = f"https://codeberg.org{href}" if href.startswith("/") else href
        await page.goto(login_url)
        await page.wait_for_load_state("networkidle", timeout=15000)

        username_input = await page.query_selector("input[name=\"user_name\"]")
        if not username_input:
            username_input = await page.query_selector("input[type=\"text\"]")
        if not username_input:
            raise SelectorFailedError(
                "找不到用户名输入框",
                selector="input[name=\"user_name\"]",
            )

        password_input = await page.query_selector("input[name=\"password\"]")
        if not password_input:
            password_input = await page.query_selector("input[type=\"password\"]")
        if not password_input:
            raise SelectorFailedError(
                "找不到密码输入框",
                selector="input[name=\"password\"]",
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

    async def _act_open_issue(self, page, params: dict) -> ActResult:
        url = params.get("url", "")
        if not url:
            raise SelectorFailedError(
                "open_issue 需要 url 参数",
                selector=None,
            )
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # 根据 URL 路径判断 next_state
        path = urlparse(url).path
        if path.rstrip("/").split("/")[-1].isdigit():
            return ActResult(success=True, next_state="issue_detail")
        return ActResult(success=True, next_state="issue_list")

    async def _act_assign_issue(self, page, params):
        assign_dropdown = await page.query_selector(
            ".select-assignees-modify.dropdown"
        )
        if not assign_dropdown:
            raise SelectorFailedError(
                "找不到 assign 下拉按钮",
                selector=".select-assignees-modify.dropdown",
            )
        await assign_dropdown.click()
        await page.wait_for_timeout(1500)

        username = params.get("username", "")
        if username:
            user_item = await page.query_selector(
                f'.menu .item:has-text("{username}")'
            )
            if user_item:
                await user_item.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                return ActResult(
                    success=True,
                    next_state="issue_detail",
                    side_effect_hint="assignees_updated",
                )

            search_input = await page.query_selector(
                ".select-assignees-modify.dropdown input[type=\"text\"]"
            )
            if search_input:
                await search_input.fill(username)
                await page.wait_for_timeout(1000)
                user_item = await page.query_selector(
                    f'.menu .item:has-text("{username}")'
                )
                if user_item:
                    await user_item.click()
                    await page.wait_for_load_state(
                        "networkidle", timeout=10000
                    )
                    return ActResult(
                        success=True,
                        next_state="issue_detail",
                        side_effect_hint="assignees_updated",
                    )

        return ActResult(
            success=True,
            next_state="issue_detail",
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
        return ActResult(success=True, next_state="issue_list")

    async def _act_filter_by_label(self, page, params):
        label_id = params.get("label_id", "")
        label_text = params.get("label", "")

        if label_id:
            selector = f'a.label-filter-item[data-label-id="{label_id}"]'
        elif label_text:
            selector = f'a.label-filter-item:has-text("{label_text}")'
        else:
            raise SelectorFailedError(
                "filter_by_label 需要 label_id 或 label 参数",
                selector=None,
            )

        label_link = await page.query_selector(selector)
        if not label_link:
            raise SelectorFailedError(
                f"找不到标签过滤链接: {label_id or label_text}",
                selector=selector,
            )
        await label_link.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="issue_list")
