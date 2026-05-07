import re
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "article":
            title_el = await page.query_selector("h1#firstHeading")
            if not title_el:
                raise SelectorFailedError(
                    "找不到页面标题",
                    selector="h1#firstHeading",
                )
            title = (await title_el.text_content()).strip()

            content_el = await page.query_selector("div.mw-parser-output")
            summary = ""
            if content_el:
                first_p = await content_el.query_selector("p")
                if first_p:
                    summary = (await first_p.text_content()).strip()

            heading_els = await page.query_selector_all("h2")
            sections = []
            for h2 in heading_els:
                section_title = (await h2.text_content()).strip()
                sections.append({"level": 2, "title": section_title})

            infobox = {}
            infobox_el = await page.query_selector("table.infobox")
            if infobox_el:
                rows = await infobox_el.query_selector_all("tr")
                for tr in rows:
                    th = await tr.query_selector("th")
                    td = await tr.query_selector("td")
                    if th and td:
                        key = (await th.text_content()).strip()
                        value = (await td.text_content()).strip()
                        infobox[key] = value

            lang_els = await page.query_selector_all(
                "a.interlanguage-link-target"
            )
            language_links = []
            for a in lang_els:
                lang = await a.get_attribute("lang") or ""
                href = await a.get_attribute("href") or ""
                text = (await a.text_content()).strip()
                language_links.append({
                    "lang": lang,
                    "title": text,
                    "url": href,
                })

            return ExtractResult(
                data={
                    "title": title,
                    "summary": summary,
                    "sections": sections,
                    "infobox": infobox,
                    "language_links": language_links,
                },
                state="article",
            )

        elif state == "special_page":
            return ExtractResult(data={}, state="special_page")

        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "navigate_link":
            href = params.get("href", "")
            if not href or not href.startswith("/wiki/"):
                raise SelectorFailedError(
                    f"invalid navigate_link target: {href}",
                    selector="a[href^='/wiki/']",
                )
            url = f"https://en.wikipedia.org{href}"
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            return ActResult(success=True, next_state="article")

        raise ValueError(f"act() 不支持操作: {action}")
