import re
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "news_list":
            story_rows = await page.query_selector_all("tr.athing")
            if not story_rows:
                raise SelectorFailedError(
                    "找不到新闻列表行",
                    selector="tr.athing",
                )

            subtext_els = await page.query_selector_all("td.subtext")
            more_link = await page.query_selector("a.morelink")

            stories = []
            for i, row in enumerate(story_rows):
                title_el = await row.query_selector("span.titleline > a")
                site_el = await row.query_selector("span.sitestr")

                title = (await title_el.text_content()).strip() if title_el else ""
                url = await title_el.get_attribute("href") if title_el else ""

                site = (await site_el.text_content()).strip() if site_el else ""

                score = ""
                author = ""
                comments_count = "0"
                item_id = ""
                if i < len(subtext_els):
                    score_el = await subtext_els[i].query_selector("span.score")
                    author_el = await subtext_els[i].query_selector("a.hnuser")
                    age_link = await subtext_els[i].query_selector(
                        "span.age > a[href^=\"item\"]"
                    )

                    if score_el:
                        score_text = (await score_el.text_content()).strip()
                        score_match = re.search(r"(\d+)", score_text)
                        score = score_match.group(1) if score_match else score_text

                    if author_el:
                        author = (await author_el.text_content()).strip()

                    if age_link:
                        age_href = await age_link.get_attribute("href") or ""
                        id_match = re.search(r"id=(\d+)", age_href)
                        item_id = id_match.group(1) if id_match else ""

                    comment_links = await subtext_els[i].query_selector_all(
                        "a[href^=\"item\"]"
                    )
                    for cl in comment_links:
                        cl_text = (await cl.text_content()).strip()
                        count_match = re.search(r"(\d+)", cl_text)
                        if count_match:
                            comments_count = count_match.group(1)
                            break

                stories.append({
                    "id": item_id,
                    "title": title,
                    "url": url,
                    "site": site,
                    "score": score,
                    "author": author,
                    "comments_count": comments_count,
                })

            has_next = more_link is not None
            next_page = ""
            if more_link:
                next_page = await more_link.get_attribute("href") or ""

            logout_el = await page.query_selector("a#logout")
            is_logged_in = logout_el is not None

            return ExtractResult(
                data={
                    "stories": stories,
                    "pagination": {
                        "current_page": "1",
                        "has_next": has_next,
                        "next_page": next_page,
                    },
                    "is_logged_in": is_logged_in,
                },
                state="news_list",
            )

        elif state == "item_detail":
            title_el = await page.query_selector("span.titleline > a")
            story_link = ""
            title = ""
            if title_el:
                title = (await title_el.text_content()).strip()
                story_link = await title_el.get_attribute("href") or ""

            comtrs = await page.query_selector_all("tr.comtr")

            comments = []
            for row in comtrs:
                indent_img = await row.query_selector("td.ind > img[width]")
                indent_level = 0
                if indent_img:
                    width_str = await indent_img.get_attribute("width") or "0"
                    indent_level = int(width_str) // 40

                author_el = await row.query_selector("a.hnuser")
                body_el = await row.query_selector("div.commtext")

                author = (await author_el.text_content()).strip() if author_el else ""
                text = (await body_el.text_content()).strip() if body_el else ""

                comments.append({
                    "author": author,
                    "text": text,
                    "indent_level": indent_level,
                })

            logout_el = await page.query_selector("a#logout")
            is_logged_in = logout_el is not None

            return ExtractResult(
                data={
                    "title": title,
                    "url": story_link,
                    "comments": comments,
                    "is_logged_in": is_logged_in,
                },
                state="item_detail",
            )

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "paginate":
            direction = params.get("direction", "next")
            if direction == "next":
                more_link = await page.query_selector("a.morelink")
                if not more_link:
                    raise SelectorFailedError(
                        "找不到翻页链接",
                        selector="a.morelink",
                    )
                await more_link.click()
            else:
                back_link = await page.query_selector("a[rel=\"prev\"]")
                if back_link:
                    await back_link.click()
                else:
                    await page.goto("https://news.ycombinator.com/news")
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="news_list")

        elif action == "open_item":
            url = params.get("url")
            if not url:
                raise ValueError("open_item 需要 url 参数")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="item_detail")

        raise ValueError(f"act() 不支持操作: {action}")
