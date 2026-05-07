from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "issue_list":
            # GitHub 新版 UI 用 role="row"（表格），旧版用 role="listitem"（列表）
            rows = await page.query_selector_all('[role="row"]')
            if not rows:
                rows = await page.query_selector_all('[role="listitem"]')
            if not rows:
                raise SelectorFailedError(
                    "找不到 issue 列表",
                    selector='[role="row"] or [role="listitem"]',
                )

            issues = []
            for row in rows:
                title_el = await row.query_selector(
                    '[data-testid="issue-pr-title-link"]'
                )
                state_el = await row.query_selector(
                    '[data-testid="list-row-state-icon"]'
                )

                title = (await title_el.text_content()).strip() if title_el else ""

                state_str = "open"
                if state_el:
                    svg_html = await state_el.inner_html()
                    if "issue-closed" in svg_html:
                        state_str = "closed"

                url = ""
                if title_el:
                    href = await title_el.get_attribute("href") or ""
                    if href:
                        url = f"https://github.com{href}" if href.startswith("/") else href

                issue_id = ""
                if url:
                    parts = url.strip("/").split("/")
                    if parts:
                        issue_id = parts[-1]

                issues.append({
                    "id": issue_id,
                    "title": title,
                    "state": state_str,
                    "url": url,
                })

            return ExtractResult(data={"issues": issues}, state="issue_list")

        elif state == "issue_detail":
            title_el = await page.query_selector('[data-testid="issue-title"]')
            if not title_el:
                raise SelectorFailedError(
                    "找不到 issue 标题",
                    selector='[data-testid="issue-title"]',
                )

            body_el = await page.query_selector('[data-testid="issue-body"]')
            state_el = await page.query_selector('[data-testid="header-state"]')

            title = (await title_el.text_content()).strip()
            body = (await body_el.text_content()).strip() if body_el else ""
            state_str = (await state_el.text_content()).strip() if state_el else "open"

            comment_els = await page.query_selector_all(".react-issue-comment")
            comments = []
            for comment_el in comment_els:
                avatar = await comment_el.query_selector(
                    '[data-testid="github-avatar"]'
                )
                author = await avatar.get_attribute("alt") if avatar else ""
                body_el2 = await comment_el.query_selector(
                    '[data-testid="markdown-body"]'
                )
                text = (await body_el2.text_content()).strip() if body_el2 else ""
                comments.append({"author": author, "text": text})

            return ExtractResult(
                data={
                    "title": title,
                    "body": body,
                    "state": state_str,
                    "comments": comments,
                },
                state="issue_detail",
            )

        elif state in ("not_logged_in", "logged_in"):
            return ExtractResult(data={}, state=state)

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "login":
            login_input = await page.query_selector("input[name=\"login\"]")
            if not login_input:
                raise SelectorFailedError(
                    "找不到登录用户名输入框",
                    selector="input[name=\"login\"]",
                )

            password_input = await page.query_selector("input[name=\"password\"]")
            if not password_input:
                raise SelectorFailedError(
                    "找不到登录密码输入框",
                    selector="input[name=\"password\"]",
                )

            await login_input.fill(params["username"])
            await password_input.fill(params["password"])

            submit_btn = await page.query_selector("input[type=\"submit\"]")
            if not submit_btn:
                raise SelectorFailedError(
                    "找不到登录提交按钮",
                    selector="input[type=\"submit\"]",
                )
            await submit_btn.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="logged_in")

        elif action == "navigate_to_repo":
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            await page.goto(f"https://github.com/{owner}/{repo}/issues")
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_list")

        elif action == "paginate":
            direction = params.get("direction", "next")
            selector = (
                "[aria-label=\"Next Page\"]"
                if direction == "next"
                else "[aria-label=\"Previous Page\"]"
            )
            link = await page.query_selector(selector)
            if not link:
                raise SelectorFailedError(
                    f"找不到翻页按钮 ({direction})",
                    selector=selector,
                )
            await link.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_list")

        elif action == "open_issue":
            url = params.get("url")
            if not url:
                raise ValueError("open_issue 需要 url 参数")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_detail")

        elif action == "filter":
            label = params.get("label", "")
            selector = f"a[data-label-name=\"{label}\"]"
            link = await page.query_selector(selector)
            if not link:
                raise SelectorFailedError(
                    f"找不到 label 过滤链接 ({label})",
                    selector=selector,
                )
            await link.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_list")

        elif action == "post_comment":
            comment_field = await page.query_selector("#new_comment_field")
            if not comment_field:
                raise SelectorFailedError(
                    "找不到评论输入框",
                    selector="#new_comment_field",
                )
            await comment_field.fill(params["body"])

            submit_btn = await page.query_selector("button[name=\"comment\"]")
            if not submit_btn:
                raise SelectorFailedError(
                    "找不到评论提交按钮",
                    selector="button[name=\"comment\"]",
                )
            await submit_btn.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_detail")

        elif action == "close_issue":
            close_btn = await page.query_selector("button[data-component=\"close\"]")
            if not close_btn:
                raise SelectorFailedError(
                    "找不到 Close Issue 按钮",
                    selector="button[data-component=\"close\"]",
                )
            await close_btn.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="issue_detail")

        raise ValueError(f"act() 不支持操作: {action}")
