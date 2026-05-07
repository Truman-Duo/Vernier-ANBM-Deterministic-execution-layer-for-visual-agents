"""
Lobsters Adapter
选择器选择理由：
- story_list state: ol.stories.list — 列表页独有的 class 组合，区分于详情页的 ol.stories
- story_detail state: div.story_content — 详情页故事描述区域，列表页不存在
- not_found state: .box.wide — 404 页面专用容器
- 条目容器: li.story — 每行故事容器，含 data-shortid
- 标题链接: a.u-url — 语义化微格式 class
- 标签: a.tag — 语义化 tag class
"""
from urllib.parse import quote

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "story_list":
            return await self._extract_story_list(page)
        elif state == "story_detail":
            return await self._extract_story_detail(page)
        elif state == "not_found":
            return ExtractResult(
                data={"stories": [], "total_results": 0},
                state="not_found",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "filter_by_tag":
            return await self._act_filter_by_tag(page, params)
        elif action == "open_story":
            return await self._act_open_story(page, params)
        elif action == "search":
            return await self._act_search(page, params)
        elif action == "extract_content":
            data = await self._extract_story_detail(page)
            return ActResult(success=True, next_state="story_detail", data=data.data)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_story_list(self, page):
        container = await page.query_selector("ol.stories.list")
        if not container:
            raise SelectorFailedError(
                "找不到故事列表容器",
                selector="ol.stories.list",
            )

        story_els = await page.query_selector_all("ol.stories.list > li.story")
        stories = []
        for el in story_els:
            title_el = await el.query_selector("a.u-url")
            title = (await title_el.text_content()).strip() if title_el else ""
            url = ""
            if title_el:
                url = await title_el.get_attribute("href") or ""

            tag_els = await el.query_selector_all("a.tag")
            tags = []
            for t in tag_els:
                tag_text = (await t.text_content()).strip()
                if tag_text:
                    tags.append(tag_text)

            score = 0
            voter_el = await el.query_selector(".voters .upvoter")
            if voter_el:
                score_text = (await voter_el.text_content()).strip()
                try:
                    score = int(score_text.replace("~", "0"))
                except ValueError:
                    score = 0

            comment_count = 0
            comment_el = await el.query_selector(".comments_label a")
            if comment_el:
                cc_text = (await comment_el.text_content()).strip()
                import re
                nums = re.findall(r"\d+", cc_text)
                if nums:
                    comment_count = int(nums[0])

            submitter = ""
            submitter_el = await el.query_selector(".byline .u-author")
            if submitter_el:
                submitter = (await submitter_el.text_content()).strip()

            domain = ""
            domain_el = await el.query_selector(".domain")
            if domain_el:
                domain = (await domain_el.text_content()).strip()

            stories.append({
                "title": title,
                "url": url,
                "tags": tags,
                "score": score,
                "comment_count": comment_count,
                "submitter": submitter,
                "domain": domain,
            })

        return ExtractResult(
            data={"stories": stories, "total_results": len(stories)},
            state="story_list",
        )

    async def _extract_story_detail(self, page):
        content_el = await page.query_selector("div.story_content")
        if not content_el:
            raise SelectorFailedError(
                "找不到故事详情内容",
                selector="div.story_content",
            )
        description_html = await content_el.inner_html()

        title = ""
        url = ""
        title_el = await page.query_selector(".details .link a.u-url")
        if title_el:
            title = (await title_el.text_content()).strip()
            url = await title_el.get_attribute("href") or ""

        tag_els = await page.query_selector_all("a.tag")
        tags = []
        for t in tag_els:
            tag_text = (await t.text_content()).strip()
            if tag_text:
                tags.append(tag_text)

        score = 0
        voter_el = await page.query_selector(".voters .upvoter")
        if voter_el:
            try:
                score_text = (await voter_el.text_content()).strip()
                score = int(score_text.replace("~", "0"))
            except ValueError:
                pass

        comment_count = 0
        comment_el = await page.query_selector(".comments_label a")
        if comment_el:
            cc_text = (await comment_el.text_content()).strip()
            import re
            nums = re.findall(r"\d+", cc_text)
            if nums:
                comment_count = int(nums[0])

        submitter = ""
        submitter_el = await page.query_selector(".byline .u-author")
        if submitter_el:
            submitter = (await submitter_el.text_content()).strip()

        domain = ""
        domain_el = await page.query_selector(".domain")
        if domain_el:
            domain = (await domain_el.text_content()).strip()

        return ExtractResult(
            data={
                "title": title,
                "url": url,
                "tags": tags,
                "score": score,
                "comment_count": comment_count,
                "submitter": submitter,
                "description_html": description_html,
                "domain": domain,
            },
            state="story_detail",
        )

    async def _act_filter_by_tag(self, page, params: dict) -> ActResult:
        tag = params.get("tag", "")
        if not tag:
            raise SelectorFailedError(
                "filter_by_tag 需要 tag 参数",
                selector=None,
            )
        tag_url = f"https://lobste.rs/t/{quote(tag)}"
        await page.goto(tag_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="story_list")

    async def _act_open_story(self, page, params: dict) -> ActResult:
        url = params.get("url", "")
        if not url:
            raise SelectorFailedError(
                "open_story 需要 url 参数",
                selector=None,
            )
        if url.startswith("/"):
            url = f"https://lobste.rs{url}"
        await page.goto(url)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        return ActResult(success=True, next_state="story_detail")

    async def _act_search(self, page, params: dict) -> ActResult:
        query = params.get("query", "")
        if not query:
            raise SelectorFailedError(
                "search 需要 query 参数",
                selector=None,
            )
        search_url = f"https://lobste.rs/search?q={quote(query)}&what=stories"
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="story_list")
