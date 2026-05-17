"""
Unsplash Adapter
选择器选择理由：
- photo_grid state: [data-testid="photos-feed-route"] — React 渲染后的照片 feed（2026-05 更名，旧名 asset-grid-masonry-figure）
- photo_detail state: [data-testid="non-sponsored-photo-download-button"] — 照片详情页下载按钮
- 搜索输入: [data-testid="nav-bar-search-form-input"] — 导航栏搜索框
- Unsplash 使用 CSS-in-JS，class 名为哈希值，不可作为选择器
- 所有选择器使用 data-testid，由 Unsplash 内部测试框架维护，稳定性高
"""
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError
from urllib.parse import urlparse


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "photo_grid":
            return await self._extract_photo_grid(page)
        if state == "photo_detail":
            return await self._extract_photo_detail(page)
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "search":
            return await self._act_search(page, params)
        if action == "open_photo":
            return await self._act_open_photo(page, params)
        if action == "paginate":
            return await self._act_paginate(page)
        if action == "extract_content":
            return await self._act_extract_content(page, params)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_photo_grid(self, page):
        await page.wait_for_selector(
            '[data-testid="photos-feed-route"]', timeout=10000
        )

        figures = await page.query_selector_all(
            '[data-testid="photos-feed-route"]'
        )
        if not figures:
            raise SelectorFailedError(
                "找不到照片网格",
                selector="[data-testid='photos-feed-route']",
            )

        photos = []
        for fig in figures:
            img = await fig.query_selector("img")
            src = await img.get_attribute("src") if img else ""
            alt = await img.get_attribute("alt") if img else ""

            # data-href 在包裹 <a> 上，指向照片详情页
            link = await fig.query_selector("a[data-href]")
            photo_url = ""
            if link:
                photo_url = await link.get_attribute("data-href") or ""

            photos.append({
                "type": "image",
                "src": src,
                "alt": alt,
                "extractable": bool(alt.strip()) if alt else False,
                "photo_url": photo_url,
            })

        return ExtractResult(
            data={"photos": photos, "has_more": True},
            state="photo_grid",
        )

    async def _extract_photo_detail(self, page):
        await page.wait_for_selector(
            '[data-testid="non-sponsored-photo-download-button"]', timeout=10000
        )

        # 主照片 <img>（页面中最大的 unsplash 图片）
        main_img = await page.query_selector(
            "img[src*='images.unsplash.com'][src*='w=']"
        )
        src = await main_img.get_attribute("src") if main_img else ""
        alt = await main_img.get_attribute("alt") if main_img else ""

        # 获取作者/摄影师信息
        author = ""
        avatar = await page.query_selector(
            "[data-testid='user-avatar']"
        )
        if avatar:
            avatar_img = await avatar.query_selector("img")
            if avatar_img:
                author = await avatar_img.get_attribute("alt") or ""

        return ExtractResult(
            data={
                "type": "image",
                "src": src,
                "alt": alt,
                "extractable": bool(alt.strip()) if alt else False,
                "author": author,
            },
            state="photo_detail",
        )

    async def _act_search(self, page, params: dict) -> ActResult:
        keyword = params.get("keyword", "")
        if not keyword:
            raise SelectorFailedError(
                "search 需要 keyword 参数", selector=None
            )
        search_url = f"https://unsplash.com/s/photos/{keyword}"
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="photo_grid")

    async def _act_open_photo(self, page, params: dict) -> ActResult:
        url = params.get("url", "")
        if not url:
            raise SelectorFailedError(
                "open_photo 需要 url 参数", selector=None
            )
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="photo_detail")

    async def _act_paginate(self, page):
        # Unsplash 无限滚动 — 滚动到底部触发新内容加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        return ActResult(success=True, next_state="photo_grid")

    async def _act_extract_content(self, page, params: dict) -> ActResult:
        # extract_content 实际内容由 extract() 完成，
        # act() 仅确认页面状态，不做额外操作
        return ActResult(success=True, next_state="photo_detail")
