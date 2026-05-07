import hashlib
import logging
import re

logger = logging.getLogger(__name__)


class StateValidator:
    """
    状态校验器。
    负责检测当前页面状态、验证状态转换、检查操作权限。
    """

    async def detect_state(
        self,
        page,
        manifest: dict,
        session_fingerprint_cache: dict | None = None,
    ) -> tuple[str, dict | None]:
        """
        遍历 manifest["states"]，检查 check/also_check 条件。
        如果提供 session_fingerprint_cache，用 fingerprint 加速检测。
        返回 (状态名, 匹配规则描述) 或 ("unknown", None)。
        """
        if session_fingerprint_cache is not None:
            fp = await self._compute_fingerprint(page, manifest)
            cached = session_fingerprint_cache.get(fp)
            if cached is not None:
                return cached

        for state_name, state_def in manifest.get("states", {}).items():
            check = state_def.get("check", {})
            if not await self._check_satisfied(page, check):
                continue
            also = state_def.get("also_check")
            if also and not await self._check_satisfied(page, also):
                continue
            detected_by = self._describe_check(check, page)
            result = (state_name, detected_by)

            if session_fingerprint_cache is not None:
                session_fingerprint_cache[fp] = result

            return result

        if session_fingerprint_cache is not None:
            session_fingerprint_cache[fp] = ("unknown", None)

        return "unknown", None

    @staticmethod
    async def _compute_fingerprint(
        page,
        manifest: dict,
        container_selector: str | None = None,
    ) -> str:
        """
        计算页面 fingerprint（sha256）。
        输入：page.url + 所有 selector/aria check 的 DOM 特征。
        输出：32 字符 hex 字符串。

        当 container_selector 指定时，只计算该容器的 innerHTML（用于无限滚动检测）。
        v0.9.2 的通用 fingerprint 计算整个页面的 check 选择器 outerHTML。
        在 scroll 场景下页面高度永远变化，整页 fingerprint 永远不同。
        正确做法是指定容器范围计算 innerHTML。
        """
        if container_selector:
            # 只计算指定容器的 innerHTML + URL，用于 scroll 前后比对
            raw = page.url
            container = await page.query_selector(container_selector)
            if container is not None:
                try:
                    html = await container.evaluate("el => el.innerHTML")
                    raw += "||" + html
                except Exception:
                    raw += "||<unavailable>"
            return hashlib.sha256(raw.encode()).hexdigest()[:32]

        # 向后兼容：原逻辑，遍历所有 state check 的 outerHTML
        parts = [page.url]
        for state_def in manifest.get("states", {}).values():
            for check_key in ("check", "also_check"):
                check = state_def.get(check_key)
                if not check:
                    continue
                ct = check.get("type")
                if ct in ("element_present", "element_absent"):
                    sel = check.get("selector", "")
                    el = await page.query_selector(sel)
                    if el is not None:
                        try:
                            html = await el.evaluate("el => el.outerHTML")
                            parts.append(f"{sel}={html}")
                        except Exception:
                            parts.append(f"{sel}=<exists>")
                    else:
                        parts.append(f"{sel}=")
                elif ct in ("aria_present", "aria_absent"):
                    role = check.get("role", "")
                    name = check.get("name", "")
                    parts.append(f"aria:{role}:{name}")
                # url_contains / url_matches — page.url already covers these
        raw = "||".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def validate_transition(self, page, manifest: dict, expected: str) -> bool:
        """验证页面实际状态是否与预期一致。"""
        actual, _ = await self.detect_state(page, manifest)
        return actual == expected

    def check_action_allowed(self, manifest: dict, current_state: str, action: str) -> bool:
        """检查操作在当前状态下是否被允许。"""
        allowed = manifest.get("states", {}).get(current_state, {}).get("allowed_actions", [])
        return action in allowed

    def get_idempotency(self, manifest: dict, action: str) -> bool:
        """默认 False（保守）。"""
        return manifest.get("action_idempotency", {}).get(action, False)

    async def _check_satisfied(self, page, check: dict) -> bool:
        """判断单个 check 条件是否满足。"""
        check_type = check.get("type")

        if check_type == "url_contains":
            return check["value"] in page.url

        elif check_type == "url_matches":
            return bool(re.search(check["pattern"], page.url))

        elif check_type == "element_present":
            el = await page.query_selector(check["selector"])
            return el is not None

        elif check_type == "element_absent":
            el = await page.query_selector(check["selector"])
            return el is None

        elif check_type == "aria_present":
            locator = self._build_aria_locator(page, check)
            return await locator.count() > 0

        elif check_type == "aria_absent":
            locator = self._build_aria_locator(page, check)
            return await locator.count() == 0

        else:
            logger.warning(f"未知的 check 类型: {check_type}")
            return False

    @staticmethod
    def _build_aria_locator(page, check: dict):
        """
        用 Playwright 原生 get_by_role 构造 aria locator。
        role 必填，name 可选（不填则只按 role 匹配）。
        """
        role = check["role"]
        name = check.get("name")
        if name:
            return page.get_by_role(role, name=name)
        return page.get_by_role(role)

    @staticmethod
    def _describe_check(check: dict, page) -> dict:
        """生成匹配规则的描述 dict，用于 StateChangedError.detected_by。"""
        check_type = check.get("type", "")
        info = {"check_type": check_type}
        if check_type == "url_contains":
            info["value"] = check.get("value", "")
            info["matched_value"] = page.url
        elif check_type == "url_matches":
            info["pattern"] = check.get("pattern", "")
            info["matched_value"] = page.url
        elif check_type in ("element_present", "element_absent"):
            info["selector"] = check.get("selector", "")
            info["matched_value"] = check.get("selector", "")
        elif check_type in ("aria_present", "aria_absent"):
            info["role"] = check.get("role", "")
            info["name"] = check.get("name", "")
        return info
