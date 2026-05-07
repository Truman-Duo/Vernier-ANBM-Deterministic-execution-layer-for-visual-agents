from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "subreddit_feed":
            # Reddit 新 UI 用 role="article"，旧 UI 用 shreddit-post
            posts = await page.query_selector_all('shreddit-post')
            if not posts:
                posts = await page.query_selector_all('[role="article"]')
            if not posts:
                raise SelectorFailedError(
                    "找不到帖子列表",
                    selector="shreddit-post or [role=\"article\"]",
                )

            result = []
            for post in posts:
                title_el = await post.query_selector("[data-testid=\"post-title\"]")
                score_el = await post.query_selector("[data-testid=\"score\"]")
                link_el = await post.query_selector("a[data-testid=\"post-title-link\"]")
                comments_el = await post.query_selector("[data-testid=\"comments-count\"]")

                title = (await title_el.text_content()).strip() if title_el else ""
                score = (await score_el.text_content()).strip() if score_el else "0"
                url = await link_el.get_attribute("href") if link_el else ""
                comment_count = (await comments_el.text_content()).strip() if comments_el else "0"

                result.append({
                    "title": title,
                    "score": score,
                    "url": url,
                    "comment_count": comment_count,
                })

            return ExtractResult(data={"posts": result}, state="subreddit_feed")

        elif state == "post_detail":
            title_el = await page.query_selector("[data-testid=\"post-title\"]")
            if not title_el:
                raise SelectorFailedError(
                    "找不到帖子标题",
                    selector="[data-testid=\"post-title\"]",
                )

            body_el = await page.query_selector("[data-testid=\"post-body\"]")
            score_el = await page.query_selector("[data-testid=\"score\"]")

            title = (await title_el.text_content()).strip()
            body = (await body_el.text_content()).strip() if body_el else ""
            score = (await score_el.text_content()).strip() if score_el else "0"

            # Reddit 新 UI 用 role="article"，旧 UI 用 shreddit-comment
            comments = await page.query_selector_all("shreddit-comment")
            if not comments:
                comments = await page.query_selector_all('[role="article"]')
            top_comments = []
            for comment in comments[:5]:
                author_el = await comment.query_selector("[data-testid=\"comment-author\"]")
                body_el2 = await comment.query_selector("[data-testid=\"comment-body\"]")
                author = (await author_el.text_content()).strip() if author_el else ""
                text = (await body_el2.text_content()).strip() if body_el2 else ""
                top_comments.append({"author": author, "text": text})

            return ExtractResult(
                data={
                    "title": title,
                    "body": body,
                    "score": score,
                    "top_comments": top_comments,
                },
                state="post_detail",
            )

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "login":
            username_input = await page.query_selector("input[name=\"username\"]")
            if not username_input:
                raise SelectorFailedError(
                    "找不到用户名输入框",
                    selector="input[name=\"username\"]",
                )

            password_input = await page.query_selector("input[name=\"password\"]")
            if not password_input:
                raise SelectorFailedError(
                    "找不到密码输入框",
                    selector="input[name=\"password\"]",
                )

            await username_input.fill(params["username"])
            await password_input.fill(params["password"])

            submit_btn = await page.query_selector("button[type=\"submit\"]")
            if not submit_btn:
                raise SelectorFailedError(
                    "找不到登录按钮",
                    selector="button[type=\"submit\"]",
                )
            await submit_btn.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="logged_in")

        elif action == "navigate_to_subreddit":
            subreddit = params.get("subreddit")
            await page.goto(f"https://www.reddit.com/r/{subreddit}/")
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="subreddit_feed")

        elif action == "paginate":
            direction = params.get("direction", "next")
            selector = "a[rel=\"next\"]" if direction == "next" else "a[rel=\"prev\"]"
            link = await page.query_selector(selector)
            if not link:
                raise SelectorFailedError(
                    f"找不到翻页按钮 ({direction})",
                    selector=selector,
                )
            await link.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="subreddit_feed")

        elif action == "upvote_post":
            post_id = params.get("post_id")
            selector = f"shreddit-post[id=\"{post_id}\"] [data-testid=\"upvote-button\"]"
            btn = await page.query_selector(selector)
            if not btn:
                raise SelectorFailedError(
                    "找不到 upvote 按钮",
                    selector=selector,
                )
            await btn.click()
            await page.wait_for_load_state("networkidle")

            next_state = "post_detail" if "/comments/" in page.url else "subreddit_feed"
            return ActResult(success=True, next_state=next_state)

        elif action == "open_post":
            url = params.get("url")
            if not url:
                raise ValueError("open_post 需要 url 参数")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="post_detail")

        raise ValueError(f"act() 不支持操作: {action}")
