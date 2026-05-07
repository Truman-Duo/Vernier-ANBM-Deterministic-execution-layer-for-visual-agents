import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SelectorFailedError(Exception):
    """选择器找不到元素。可 retry（若幂等且状态未变）。"""

    def __init__(self, message: str, selector: str = None):
        self.selector = selector
        super().__init__(message)


class PageTimeoutError(Exception):
    """页面操作超时。可 retry（若幂等且状态未变）。"""


class StateChangedError(Exception):
    """
    retry 过程中检测到状态跳转。
    由 RetryOrchestrator 抛出，由 DecisionRouter 处理。
    handler.py 中禁止抛出此异常。
    """

    def __init__(
        self,
        message: str,
        new_state: str,
        attempts_before_change: int,
        trigger_url: str = "",
        detected_by: dict | None = None,
    ):
        self.new_state = new_state
        self.attempts_before_change = attempts_before_change
        self.trigger_url = trigger_url
        self.detected_by = detected_by or {}
        super().__init__(message)


class ActionNotAllowedError(Exception):
    """操作不在 allowed_actions 中。由 FSM 引擎层处理，不在 handler 中出现。"""


class SessionNotFoundError(Exception):
    """Session 不存在。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session '{session_id}' not found")


class AdapterNotFoundError(Exception):
    """Adapter 资源缺失。"""

    def __init__(self, adapter_id: str):
        self.adapter_id = adapter_id
        super().__init__(f"Adapter '{adapter_id}' not found")


class VisualClientNotConfiguredError(Exception):
    """VisualClient 未配置（ANTHROPIC_API_KEY 未设置）。"""


@dataclass
class ExtractResult:
    data: dict
    state: str


@dataclass
class ActResult:
    success: bool
    next_state: str
    data: dict = field(default=None)
    side_effect_hint: str = field(default=None)
    # 语义：act() 成功后哪个字段会变化，供 Agent 后续调用 extract() 验证
    # 示例："like_count_incremented" / "reactions_count_incremented" / "assignee_set"
    # 不影响引擎逻辑，不强制校验，只是给 Agent 的提示信息


class BaseAdapter(ABC):

    @abstractmethod
    async def extract(self, page, state: str) -> ExtractResult:
        ...

    @abstractmethod
    async def act(self, page, action: str, params: dict) -> ActResult:
        ...

    async def _get_text(self, element, selector: str) -> str:
        el = await element.query_selector(selector)
        if not el:
            raise SelectorFailedError(f"找不到元素: {selector}", selector=selector)
        return (await el.text_content()).strip()

    async def _get_href(self, element, selector: str) -> str:
        el = await element.query_selector(selector)
        if not el:
            raise SelectorFailedError(f"找不到链接: {selector}", selector=selector)
        return await el.get_attribute("href")
