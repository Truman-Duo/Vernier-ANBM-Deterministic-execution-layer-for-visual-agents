"""
Exercism Adapter
选择器选择理由：
- track_list state: #page-tracks — Exercism tracks 列表页的固定 ID
- exercise_list state: #page-exercises-index — 指定 track 的练习列表页固定 ID
- exercise_detail state: #page-exercise-show — 单个练习描述页固定 ID
- not_found state: #page-error — 404 页面固定 ID
- Exercism 使用 Ruby on Rails + Turbo + React，页面 ID 由 Rails 路由固定生成
- track 卡片: #page-tracks a[href^="/tracks/"] — track 列表中的链接
- 练习列表: section.exercises a[href*="/exercises/"] — 练习列表中的条目链接
- 练习描述: section.instructions — 练习题目描述区域
"""
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError
from urllib.parse import urlparse, urljoin


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "track_list":
            return await self._extract_track_list(page)
        if state == "exercise_list":
            return await self._extract_exercise_list(page)
        if state == "exercise_detail":
            return await self._extract_exercise_detail(page)
        if state == "not_found":
            return ExtractResult(data={}, state="not_found")
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "open_track":
            return await self._act_open_track(page, params)
        if action == "open_exercise":
            return await self._act_open_exercise(page, params)
        if action == "extract_content":
            return ActResult(success=True, next_state=page.state if hasattr(page, 'state') else "exercise_detail")
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_track_list(self, page):
        await page.wait_for_selector("#page-tracks", timeout=10000)

        track_links = await page.query_selector_all(
            '#page-tracks a[href^="/tracks/"]'
        )
        if not track_links:
            raise SelectorFailedError(
                "找不到 track 列表",
                selector='#page-tracks a[href^="/tracks/"]',
            )

        tracks = []
        seen = set()
        for link in track_links:
            href = await link.get_attribute("href") or ""
            if href in seen:
                continue
            seen.add(href)
            text = (await link.text_content()).strip()
            name = text.split("/")[0].strip() if "/" in text else text
            # 提取 slug: /tracks/python → python
            slug = href.replace("/tracks/", "").split("/")[0] if href else ""
            tracks.append({
                "type": "track",
                "name": name or slug,
                "slug": slug,
                "url": href,
                "extractable": True,
            })

        return ExtractResult(
            data={"tracks": tracks},
            state="track_list",
        )

    async def _extract_exercise_list(self, page):
        await page.wait_for_selector("#page-exercises-index", timeout=10000)

        exercises = []

        # 尝试从 section.exercises 中提取练习条目
        section = await page.query_selector("section.exercises")
        if section:
            links = await section.query_selector_all('a[href*="/exercises/"]')
            for link in links:
                href = await link.get_attribute("href") or ""
                text = (await link.text_content()).strip()
                if text and href:
                    exercises.append({
                        "type": "exercise",
                        "name": text,
                        "url": href,
                        "extractable": True,
                    })

        if not exercises:
            # 保底：从整个页面提取练习链接
            all_links = await page.query_selector_all(
                'a[href*="/exercises/"]'
            )
            seen = set()
            for link in all_links:
                href = await link.get_attribute("href") or ""
                # 只取当前 track 的练习（不跨 track）
                if href in seen or href.count("/exercises/") != 1:
                    continue
                seen.add(href)
                text = (await link.text_content()).strip()
                if text:
                    exercises.append({
                        "type": "exercise",
                        "name": text,
                        "url": href,
                        "extractable": True,
                    })

        return ExtractResult(
            data={"exercises": exercises},
            state="exercise_list",
        )

    async def _extract_exercise_detail(self, page):
        await page.wait_for_selector("#page-exercise-show", timeout=10000)

        blocks = []

        # 标题
        title_el = await page.query_selector("div.exercise-title")
        title = (await title_el.text_content()).strip() if title_el else ""

        # 题目描述 — section.instructions
        instructions = await page.query_selector("section.instructions")
        if instructions:
            # 文本段落
            for p in await instructions.query_selector_all("p"):
                text = (await p.text_content()).strip()
                if text:
                    blocks.append({"type": "text", "content": text})

            # 代码块
            for pre in await instructions.query_selector_all("pre"):
                text = (await pre.text_content()).strip()
                if text:
                    blocks.append({
                        "type": "code",
                        "content": text,
                        "extractable": True,
                    })

            # 标题 (h2, h3, h4)
            for tag in ("h2", "h3", "h4"):
                for h in await instructions.query_selector_all(tag):
                    text = (await h.text_content()).strip()
                    if text:
                        blocks.append({
                            "type": "text",
                            "content": text,
                            "heading_level": int(tag[1]),
                        })

        # 如果 instructions 内没有内容，尝试从 article.content 提取
        if not blocks:
            article = await page.query_selector("article.content")
            if article:
                for p in await article.query_selector_all("p"):
                    text = (await p.text_content()).strip()
                    if text:
                        blocks.append({"type": "text", "content": text})

        return ExtractResult(
            data={
                "title": title,
                "content_blocks": blocks,
            },
            state="exercise_detail",
        )

    async def _act_open_track(self, page, params: dict) -> ActResult:
        track = params.get("track", "") or params.get("name", "") or params.get("slug", "")
        if not track:
            raise SelectorFailedError(
                "open_track 需要 track/name/slug 参数", selector=None
            )
        url = urljoin(page.url, f"/tracks/{track}/exercises")
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="exercise_list")

    async def _act_open_exercise(self, page, params: dict) -> ActResult:
        exercise = params.get("exercise", "") or params.get("name", "") or params.get("slug", "")
        if not exercise:
            raise SelectorFailedError(
                "open_exercise 需要 exercise/name/slug 参数", selector=None
            )
        # 尝试使用完整 URL
        url = params.get("url", "")
        if not url:
            # 从当前 track URL 构造
            current_path = urlparse(page.url).path
            if "/exercises" in current_path:
                base = current_path.split("/exercises")[0]
            else:
                base = current_path.rstrip("/")
            url = urljoin(page.url, f"{base}/exercises/{exercise}")
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="exercise_detail")
