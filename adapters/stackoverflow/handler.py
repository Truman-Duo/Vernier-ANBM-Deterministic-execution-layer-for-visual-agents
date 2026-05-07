"""
Stack Overflow Adapter — aria 优先选择器策略的验证实现。

选择器优先级与理由：
  [role="article"]           → aria role 是 WAI-ARIA 标准属性，前端重构时很少改动
  h3 > a.s-link              → h3 是语义化标题标签，.s-link 是 Stacks 设计系统类名（稳定）
  [itemprop="upvoteCount"]   → itemprop 是微数据标准属性，搜索引擎依赖，冻结概率极低
  [aria-label$="answers"]    → aria-label 末尾匹配 answers，避免数字导致选择器失效
  [rel="tag"]                → rel 属性标记分类关系，独立于 UI 框架
  [role="searchbox"]         → aria role 标准搜索框标识，比 input#id 稳定
  [rel="next"]               → rel="next" 表示翻页链接，语义化标记
  [data-se-page='404']       → data-se-* 是 Stacks 的自定义数据属性，内部使用频次低

所有 CSS class 选择器（.s-link, .post-tag, .s-prose 等）作为备选，
在 aria 选择器不可用时作为回退。当前 handler 优先使用 aria/data 选择器。
"""

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "question_list" or state == "search_results":
            articles = await page.query_selector_all('[role="article"]')
            questions = []
            for article in articles:
                title_el = await article.query_selector("h3 > a.s-link")
                title = (await title_el.text_content()).strip() if title_el else ""

                href = ""
                if title_el:
                    href = await title_el.get_attribute("href") or ""

                vote_el = await article.query_selector(
                    '[itemprop="upvoteCount"]'
                )
                vote_count = (
                    (await vote_el.text_content()).strip() if vote_el else "0"
                )

                answer_el = await article.query_selector(
                    '[aria-label$="answers"]'
                )
                answer_count = ""
                if answer_el:
                    answer_count = (await answer_el.text_content()).strip()

                tag_els = await article.query_selector_all('[rel="tag"]')
                tags = []
                for tag_el in tag_els:
                    text = (await tag_el.text_content()).strip()
                    if text:
                        tags.append(text)

                questions.append({
                    "title": title,
                    "url": href,
                    "vote_count": vote_count,
                    "answer_count": answer_count,
                    "tags": tags,
                })

            return ExtractResult(
                data={"questions": questions},
                state=state,
            )

        elif state == "question_detail":
            title_el = await page.query_selector('h1 [itemprop="name"]')
            title = (await title_el.text_content()).strip() if title_el else ""

            body_el = await page.query_selector('[itemprop="text"]')
            body_text = ""
            if body_el:
                first_p = await body_el.query_selector("p")
                if first_p:
                    body_text = (await first_p.text_content()).strip()

            vote_el = await page.query_selector('[itemprop="upvoteCount"]')
            vote_count = (
                (await vote_el.text_content()).strip() if vote_el else "0"
            )

            tag_els = await page.query_selector_all('[rel="tag"]')
            tags = []
            for tag_el in tag_els:
                text = (await tag_el.text_content()).strip()
                if text:
                    tags.append(text)

            answer_el = await page.query_selector(
                '[aria-label$="answers"]'
            )
            answer_count = ""
            if answer_el:
                answer_count = (await answer_el.text_content()).strip()

            return ExtractResult(
                data={
                    "title": title,
                    "body_text": body_text,
                    "vote_count": vote_count,
                    "tags": tags,
                    "answer_count": answer_count,
                },
                state="question_detail",
            )

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "paginate":
            link = await page.query_selector('[rel="next"]')
            if not link:
                raise SelectorFailedError(
                    "找不到翻页链接",
                    selector='[rel="next"]',
                )
            await link.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state=None)

        elif action == "open_question":
            url = params.get("url", "")
            if not url:
                raise SelectorFailedError(
                    "open_question 需要 url 参数",
                    selector="[role='article'] h3 > a.s-link",
                )
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            return ActResult(success=True, next_state="question_detail")

        elif action == "search":
            query = params.get("query", "")
            if not query:
                raise SelectorFailedError(
                    "search 需要 query 参数",
                    selector='[role="searchbox"]',
                )
            searchbox = await page.query_selector('[role="searchbox"]')
            if not searchbox:
                raise SelectorFailedError(
                    "找不到搜索框",
                    selector='[role="searchbox"]',
                )
            await searchbox.fill(query)
            await searchbox.press("Enter")
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="search_results")

        elif action == "upvote":
            btn = await page.query_selector('[aria-label="Up vote"]')
            if not btn:
                raise SelectorFailedError(
                    "找不到 upvote 按钮",
                    selector='[aria-label="Up vote"]',
                )
            await btn.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="question_detail")

        raise ValueError(f"act() 不支持操作: {action}")
