import difflib
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from anbm.adapter.loader import AdapterLoader
from anbm.engine.validator import StateValidator
from anbm.health.models import (
    AdapterHealthStatus,
    DegradationReason,
    HealthReport,
    SelectorCandidate,
    SelectorCheckResult,
)

logger = logging.getLogger(__name__)

LOGIN_KEYWORDS = ("login", "signin", "log-in", "sign-in", "auth")


class HealthChecker:
    """
    主动健康检查器。
    不创建 session，使用临时 browser context 独立运行。
    """

    def __init__(self, browser, adapter_loader: AdapterLoader, visual_client=None):
        self._browser = browser
        self._loader = adapter_loader
        self._validator = StateValidator()
        self.visual_client = visual_client

    async def check(self, adapter_id: str) -> HealthReport:
        manifest = self._loader.load_manifest(adapter_id)
        start = time.perf_counter()
        checked_at_ms = int(start * 1000)
        temp_context_id = f"health_{adapter_id}_{checked_at_ms}"

        page = await self._browser.get_page(temp_context_id)
        test_url = manifest.get("test_url") or manifest.get("url_patterns", [""])[0] or "about:blank"
        url_patterns = manifest.get("url_patterns", [])

        try:
            await page.goto(test_url, timeout=15000, wait_until="domcontentloaded")
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            final_url = page.url

            broken_url = False
            reason = None
            if url_patterns:
                matched = any(p.replace("*", "") in final_url for p in url_patterns)
                if not matched:
                    broken_url = True
                    parsed = urlparse(final_url)
                    if any(kw in parsed.netloc.lower() or kw in parsed.path.lower() for kw in LOGIN_KEYWORDS):
                        reason = DegradationReason.AUTH_REQUIRED
                    else:
                        reason = DegradationReason.URL_MOVED

            selector_results = []
            for state_name, state_def in manifest.get("states", {}).items():
                for check_key in ("check", "also_check"):
                    chk = state_def.get(check_key)
                    if chk is None:
                        continue
                    if chk.get("type") in ("element_present", "element_absent"):
                        selector = chk.get("selector", "")
                        el = await page.query_selector(selector)
                        found = el is not None
                        result = SelectorCheckResult(
                            selector=selector,
                            state=state_name,
                            found=found,
                        )
                        if not found:
                            fallback_description = chk.get("fallback_description")
                            candidates = await self._find_candidates(
                                page, selector, fallback_description
                            )
                            result.candidates = candidates[:5]
                            result.similarity_scores = [
                                c.similarity or 0 for c in candidates[:5]
                            ]
                        selector_results.append(result)

            detected_state, _ = await self._validator.detect_state(page, manifest)

            failed = [r for r in selector_results if not r.found]

            if broken_url:
                status = AdapterHealthStatus.BROKEN
            elif not failed:
                status = AdapterHealthStatus.HEALTHY
                reason = None
            elif detected_state == "unknown" and len(failed) < max(len(selector_results) // 2, 1):
                status = AdapterHealthStatus.DEGRADED
                reason = DegradationReason.SELECTOR_CHANGED
            else:
                status = AdapterHealthStatus.BROKEN
                if reason is None:
                    reason = DegradationReason.STRUCTURE_CHANGED

            return HealthReport(
                adapter_id=adapter_id,
                adapter_version=manifest.get("version", "0.0.0"),
                checked_at=datetime.now(timezone.utc),
                status=status,
                reason=reason,
                test_url=test_url,
                final_url=final_url,
                detected_state=detected_state,
                selector_results=selector_results,
                response_time_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            error_str = str(e)
            if "timeout" in error_str.lower():
                status = AdapterHealthStatus.UNREACHABLE
                reason = DegradationReason.SERVICE_DOWN
            else:
                status = AdapterHealthStatus.UNREACHABLE
                reason = DegradationReason.SERVICE_DOWN

            return HealthReport(
                adapter_id=adapter_id,
                adapter_version=manifest.get("version", "0.0.0"),
                checked_at=datetime.now(timezone.utc),
                status=status,
                reason=reason,
                test_url=test_url,
                final_url="",
                detected_state="unknown",
                selector_results=[],
                response_time_ms=elapsed_ms,
                raw_error=error_str,
            )

        finally:
            try:
                await self._browser.close_context(temp_context_id)
            except Exception:
                pass

    async def _find_candidates(
        self,
        page,
        original_selector: str,
        fallback_description: str | None = None,
    ) -> list[SelectorCandidate]:
        """
        返回候选列表，每个候选标注来源。
        候选总数上限 5 个，超过时 llm_suggested 优先，css_similar 截断。
        去重：selector 字符串完全相同的候选只保留第一个。
        """
        candidates: list[SelectorCandidate] = []

        # 路径一：css_similar（现有逻辑）
        css_candidates = await self._find_css_similar(page, original_selector)
        candidates.extend(css_candidates)

        # 路径二：aria_candidate
        aria_candidates = await self._find_aria_candidates(page, original_selector)
        for role_str, score in aria_candidates:
            candidates.append(SelectorCandidate(
                selector=role_str,
                source="aria_candidate",
                similarity=score,
            ))

        # 路径三：llm_suggested
        if fallback_description and self.visual_client is not None:
            llm_result = await self._find_llm_candidate(page, fallback_description)
            if llm_result:
                candidates.append(SelectorCandidate(
                    selector=llm_result,
                    source="llm_suggested",
                    similarity=None,
                ))

        # 排序：llm_suggested 排最前，其余按 similarity 降序
        # 去重：selector 完全相同的只保留第一个
        seen = set()
        result = []
        for c in sorted(candidates,
                        key=lambda x: (x.source != "llm_suggested", -(x.similarity or 0))):
            if c.selector not in seen and len(result) < 5:
                seen.add(c.selector)
                result.append(c)
        return result

    async def _find_css_similar(self, page, original_selector: str) -> list[SelectorCandidate]:
        """原有 difflib 相似度匹配逻辑，结果封装为 SelectorCandidate。"""
        candidates = []
        try:
            parts = original_selector.replace(".", " .").split()
            original_tag = ""
            for p in parts:
                p = p.strip()
                if p and not p.startswith(".") and not p.startswith("#") and not p.startswith("["):
                    original_tag = p

            all_elements = await page.query_selector_all("*")
            seen_selectors = set()

            for el in all_elements:
                try:
                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    class_list = await el.evaluate("el => Array.from(el.classList).join('.')")

                    if not tag or (original_tag and tag != original_tag):
                        continue

                    candidate = f"{tag}.{class_list}" if class_list else tag

                    if candidate in seen_selectors:
                        continue
                    seen_selectors.add(candidate)

                    score = difflib.SequenceMatcher(None, original_selector, candidate).ratio()
                    candidates.append(SelectorCandidate(
                        selector=candidate,
                        source="css_similar",
                        similarity=score,
                    ))
                except Exception:
                    continue

            candidates.sort(key=lambda x: -x.similarity)
        except Exception:
            pass

        return candidates

    async def _find_aria_candidates(
        self, page, original_selector: str
    ) -> list[tuple[str, float]]:
        """
        从 Accessibility Tree 里找与原 selector 语义相近的 aria 定位。

        实现策略：
        1. 调用 page.accessibility.snapshot() 获取 AX tree
        2. 遍历 tree 中的 role 节点
        3. 对于每个 role，构造 get_by_role(role) 的 Playwright 字符串表示
        4. 返回相似度分（基于 original_selector 与 role/name 的字符串重叠度），上限 3 个候选
        """
        try:
            snapshot = await page.accessibility.snapshot()
        except Exception:
            return []

        aria_candidates: list[tuple[str, float]] = []

        def walk(node):
            if not node:
                return
            role = node.get("role")
            name = node.get("name", "")
            if role:
                if name:
                    candidate = f"get_by_role('{role}', name='{name}')"
                else:
                    candidate = f"get_by_role('{role}')"
                score = difflib.SequenceMatcher(None, original_selector, role + name).ratio()
                aria_candidates.append((candidate, score))
            for child in node.get("children", []):
                walk(child)

        if snapshot:
            walk(snapshot)

        aria_candidates.sort(key=lambda x: -x[1])
        return aria_candidates[:3]

    async def _find_llm_candidate(
        self, page, fallback_description: str
    ) -> str | None:
        """
        条件：fallback_description 存在 + self.visual_client 不为 None。
        调用 visual_client.analyze_text() 获取 LLM 推荐的 selector。
        """
        if not self.visual_client:
            return None

        try:
            snapshot = await page.accessibility.snapshot()
        except Exception:
            return None

        ax_text = self._serialize_ax_tree(snapshot)
        if not ax_text:
            return None

        prompt = (
            f"页面的 Accessibility Tree 如下：\n\n{ax_text}\n\n"
            f"需要找到的元素描述：{fallback_description}\n\n"
            f"请返回一个能定位该元素的 CSS selector 或 Playwright get_by_role 调用。"
            f"只返回 selector 字符串本身，不要解释。如果无法确定，返回空字符串。"
        )
        response = await self.visual_client.analyze_text(prompt)
        response = response.strip()
        return response or None

    @staticmethod
    def _serialize_ax_tree(
        node: dict | None, max_depth: int = 4, current_depth: int = 0
    ) -> str:
        """
        将 page.accessibility.snapshot() 返回的树状 dict 序列化为缩进文本。
        每节点格式："{indent}{role}: {name}"
        超过 max_depth 时截断，避免 prompt 过长。
        node 为 None 时返回空字符串。
        """
        if node is None:
            return ""
        if current_depth >= max_depth:
            return ""
        indent = "  " * current_depth
        role = node.get("role", "")
        name = node.get("name", "")
        lines = []
        if role:
            if name:
                lines.append(f"{indent}{role}: {name}")
            else:
                lines.append(f"{indent}{role}")
        for child in node.get("children", []):
            child_text = HealthChecker._serialize_ax_tree(child, max_depth, current_depth + 1)
            if child_text:
                lines.append(child_text)
        return "\n".join(lines)
