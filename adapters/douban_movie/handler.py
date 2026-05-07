from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "movie_list":
            items = await page.query_selector_all("ol.grid_view div.item")
            if not items:
                raise SelectorFailedError(
                    "找不到电影列表",
                    selector="ol.grid_view div.item",
                )

            movies = []
            for item in items:
                title_el = await item.query_selector(".title")
                rating_el = await item.query_selector(".rating_num")
                link_el = await item.query_selector("a")

                title = (
                    await title_el.text_content()
                ).strip() if title_el else ""
                rating = (
                    await rating_el.text_content()
                ).strip() if rating_el else ""
                url = (
                    await link_el.get_attribute("href") if link_el else ""
                )

                movies.append({
                    "title": title,
                    "rating": rating,
                    "url": url,
                })

            paginator = await page.query_selector(".paginator")
            pagination = {}
            if paginator:
                current = await paginator.query_selector(".thispage")
                if current:
                    pagination["current"] = int(
                        (await current.text_content()).strip()
                    )
                has_next = await paginator.query_selector(".next a")
                pagination["has_next"] = has_next is not None

            return ExtractResult(
                data={"movies": movies, "pagination": pagination},
                state="movie_list",
            )

        elif state == "movie_detail":
            title_el = await page.query_selector("h1 span")
            if not title_el:
                raise SelectorFailedError(
                    "找不到电影标题",
                    selector="h1 span",
                )
            rating_el = await page.query_selector(".rating_num")
            rating = (
                (await rating_el.text_content()).strip()
                if rating_el else ""
            )

            return ExtractResult(
                data={
                    "title": (await title_el.text_content()).strip(),
                    "rating": rating,
                },
                state="movie_detail",
            )

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "paginate":
            direction = params.get("direction", "next")
            if direction == "next":
                link = await page.query_selector(".paginator .next a")
            else:
                link = await page.query_selector(".paginator .prev a")

            if not link:
                raise SelectorFailedError(
                    f"找不到翻页按钮 ({direction})",
                    selector=f".paginator .{direction} a",
                )

            await link.click()
            await page.wait_for_load_state("networkidle")
            return ActResult(success=True, next_state="movie_list")

        raise ValueError(f"act() 不支持操作: {action}")
