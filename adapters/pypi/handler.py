"""
PyPI Adapter
选择器选择理由：
- project_list state: [data-controller='search'] — PyPI 搜索页的根容器，稳定 data-* 属性
- project_detail state: #description — PyPI 详情页固定 ID，长期稳定
- 条目容器: .package-snippet — 搜索结果每行容器
- 包名: .package-snippet__name — 包名链接，class 语义化命名
- 分页按钮: [aria-label='Next Page'] — 语义化 aria 标签
"""
from urllib.parse import quote

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "project_list":
            return await self._extract_project_list(page)
        elif state == "project_detail":
            return await self._extract_project_detail(page)
        elif state == "not_found":
            return ExtractResult(
                data={"projects": [], "total_results": 0, "query": ""},
                state="not_found",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "filter_version":
            return await self._act_filter_version(page, params)
        elif action == "open_project":
            return await self._act_open_project(page, params)
        elif action == "paginate":
            return await self._act_paginate(page, params)
        elif action == "extract_content":
            data = await self._extract_project_detail(page)
            return ActResult(success=True, next_state="project_detail", data=data.data)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_project_list(self, page):
        container = await page.query_selector("[data-controller='search']")
        if not container:
            raise SelectorFailedError(
                "找不到搜索容器",
                selector="[data-controller='search']",
            )

        snippets = await page.query_selector_all(".package-snippet")
        projects = []
        for sn in snippets:
            name_el = await sn.query_selector(".package-snippet__name")
            ver_el = await sn.query_selector(".package-snippet__version")
            desc_el = await sn.query_selector(".package-snippet__description")

            name = (await name_el.text_content()).strip() if name_el else ""
            version = (await ver_el.text_content()).strip() if ver_el else ""
            summary = (await desc_el.text_content()).strip() if desc_el else ""

            href = ""
            if name_el:
                href = await name_el.get_attribute("href") or ""
            url = f"https://pypi.org{href}" if href else ""

            projects.append({
                "name": name,
                "version": version,
                "summary": summary,
                "url": url,
            })

        total_results = await self._parse_total_results(page)
        query = await self._parse_query(page)
        return ExtractResult(
            data={"projects": projects, "total_results": total_results, "query": query},
            state="project_list",
        )

    async def _extract_project_detail(self, page):
        desc = await page.query_selector("#description")
        if not desc:
            raise SelectorFailedError(
                "找不到详情描述容器",
                selector="#description",
            )

        name_el = await page.query_selector(".package-header__name")
        name = (await name_el.text_content()).strip() if name_el else ""

        version = ""
        sidebar_els = await page.query_selector_all(".sidebar-section .sidebar-section__title")
        for title_el in sidebar_els:
            text = (await title_el.text_content()).strip().lower()
            if "version" in text:
                value_el = await title_el.evaluate("el => el.nextElementSibling")
                if value_el:
                    version = (await value_el.text_content()).strip()

        summary = ""
        summary_el = await page.query_selector(".package-description__summary")
        if summary_el:
            summary = (await summary_el.text_content()).strip()

        github_url = ""
        sidebar = await page.query_selector(".sidebar-section")
        if sidebar:
            gh_link = await sidebar.query_selector("a[href*='github.com']")
            if gh_link:
                github_url = await gh_link.get_attribute("href") or ""

        license_name = ""
        requires_python = ""
        sections = await page.query_selector_all(".sidebar-section")
        for sec in sections:
            title_el = await sec.query_selector(".sidebar-section__title")
            if not title_el:
                continue
            title_text = (await title_el.text_content()).strip().lower()
            value = ""
            value_el = await sec.query_selector(".sidebar-section__body")
            if value_el:
                value = (await value_el.text_content()).strip()
            if "license" in title_text:
                license_name = value
            elif "python" in title_text:
                requires_python = value

        return ExtractResult(
            data={
                "name": name,
                "version": version,
                "summary": summary,
                "github_url": github_url,
                "license": license_name,
                "requires_python": requires_python,
            },
            state="project_detail",
        )

    async def _act_filter_version(self, page, params: dict) -> ActResult:
        query = params.get("query", "")
        if not query:
            raise SelectorFailedError(
                "filter_version 需要 query 参数",
                selector=None,
            )
        search_url = f"https://pypi.org/search/?q={quote(query)}"
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="project_list")

    async def _act_open_project(self, page, params: dict) -> ActResult:
        name = params.get("name", "")
        url = params.get("url", "")
        if not url and name:
            url = f"https://pypi.org/project/{name}/"
        if not url:
            raise SelectorFailedError(
                "open_project 需要 name 或 url 参数",
                selector=None,
            )
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="project_detail")

    async def _act_paginate(self, page, params: dict) -> ActResult:
        direction = params.get("direction", "next")
        aria = "Next Page" if direction == "next" else "Previous Page"
        btn = await page.query_selector(f"[aria-label='{aria}']")
        if not btn:
            raise SelectorFailedError(
                f"找不到翻页按钮 ({direction})",
                selector=f"[aria-label='{aria}']",
            )
        await btn.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="project_list")

    async def _parse_total_results(self, page) -> int:
        try:
            text = await page.evaluate(
                "() => document.querySelector('.search-results__total')?.textContent || ''"
            )
            import re
            nums = re.findall(r"[\d,]+", text)
            if nums:
                return int(nums[-1].replace(",", ""))
        except Exception:
            pass
        return 0

    @staticmethod
    async def _parse_query(page) -> str:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(page.url)
        return parse_qs(parsed.query).get("q", [""])[0]
