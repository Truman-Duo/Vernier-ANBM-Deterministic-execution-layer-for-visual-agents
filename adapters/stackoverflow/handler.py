"""
Stack Overflow Adapter — Stacks 设计系统选择器策略（2026-05-17 更新）。

2026-05 改版变化：
  - SO 移除了 WAI-ARIA roles（[role='article'] 消失）
  - SO 移除了 schema.org 微数据（[itemprop='upvoteCount'] 消失）
  - SO 移除了 Stacks data-* 属性（[data-se-page] 消失）
  - 搜索框 role 从 searchbox 改为 combobox

新版选择器（基于 Stacks 设计系统类名 + 保留的语义属性）：
  .s-post-summary               → 问题列表卡片容器（替代 [role='article']）
  h3 a.s-link                   → 标题链接（Stacks 设计系统，仍有效）
  .s-post-summary--stats-item__emphasized .s-post-summary--stats-item-number
                                → 投票数（替代 [itemprop='upvoteCount']）
  .s-post-summary--stats-item.has-answers .s-post-summary--stats-item-number
                                → 回答数（替代 [aria-label$='answers']）
  [rel="tag"]                   → 标签（rel 属性仍有效）
  [role="combobox"]             → 搜索框（替代 [role='searchbox']）
  .s-pagination .js-pagination-item → 翻页链接（替代 [rel='next']）

⚠️ 详情页选择器（2026-05-17 bridge 快照验证更新）：
  a.question-hyperlink         → 问题标题链接（替代 [itemprop='name']）
  .s-prose.js-post-body        → 问题正文（替代 [itemprop='text']）
  .js-vote-count               → 投票数（替代 [itemprop='upvoteCount']）
  .post-tag                    → 标签（替代 [rel='tag']，详情页无 rel 属性）
  [aria-label$="answers"]      → 回答数（仍有效）
  [aria-label="Up vote"]       → upvote 按钮（仍有效）
"""

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "question_list" or state == "search_results":
            cards = await page.query_selector_all(".s-post-summary")
            questions = []
            for card in cards:
                title_el = await card.query_selector("h3 a.s-link")
                title = (await title_el.text_content()).strip() if title_el else ""

                href = ""
                if title_el:
                    href = await title_el.get_attribute("href") or ""

                vote_el = await card.query_selector(
                    ".s-post-summary--stats-item__emphasized .s-post-summary--stats-item-number"
                )
                vote_count = (
                    (await vote_el.text_content()).strip() if vote_el else "0"
                )

                answer_el = await card.query_selector(
                    ".s-post-summary--stats-item.has-answers .s-post-summary--stats-item-number"
                )
                answer_count = ""
                if answer_el:
                    answer_count = (await answer_el.text_content()).strip()

                tag_els = await card.query_selector_all('[rel="tag"]')
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
            title_el = await page.query_selector('a.question-hyperlink')
            title = (await title_el.text_content()).strip() if title_el else ""

            body_el = await page.query_selector('.s-prose.js-post-body')
            body_text = ""
            if body_el:
                first_p = await body_el.query_selector("p")
                if first_p:
                    body_text = (await first_p.text_content()).strip()

            vote_el = await page.query_selector('.js-vote-count')
            vote_count = (
                (await vote_el.text_content()).strip() if vote_el else "0"
            )

            tag_els = await page.query_selector_all('.post-tag')
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
            # 新版 SO 翻页：找到 is-selected 的下一页
            next_href = await page.evaluate(
                "() => {"
                "  const selected = document.querySelector('.s-pagination--item.is-selected');"
                "  if (!selected) return null;"
                "  const next = selected.nextElementSibling;"
                "  if (!next || !next.classList.contains('js-pagination-item')) return null;"
                "  return next.href;"
                "}"
            )
            if not next_href:
                raise SelectorFailedError(
                    "找不到翻页链接",
                    selector=".s-pagination .js-pagination-item (next after is-selected)",
                )
            await page.goto(next_href)
            await page.wait_for_load_state("domcontentloaded")
            return ActResult(success=True, next_state=None)

        elif action == "open_question":
            url = params.get("url", "")
            if not url:
                raise SelectorFailedError(
                    "open_question 需要 url 参数",
                    selector=".s-post-summary h3 a.s-link",
                )
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            return ActResult(success=True, next_state="question_detail")

        elif action == "search":
            query = params.get("query", "")
            if not query:
                raise SelectorFailedError(
                    "search 需要 query 参数",
                    selector='[role="combobox"]',
                )
            searchbox = await page.query_selector('[role="combobox"]')
            if not searchbox:
                raise SelectorFailedError(
                    "找不到搜索框",
                    selector='[role="combobox"]',
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
