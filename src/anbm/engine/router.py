import asyncio
import base64
import logging
import random

from anbm.adapter.base import (
    SelectorFailedError,
    PageTimeoutError,
    StateChangedError,
)
from anbm.engine.retry_config import RETRY_CONFIGS, RetryConfig
from anbm.engine.validator import StateValidator
from anbm.engine.session_store import SessionStore, Session
from anbm.logging_config import log_event

logger = logging.getLogger(__name__)


class RetryOrchestrator:
    """
    执行带 retry 的操作。
    retry 的前提条件：状态未改变。
    handler.py 中禁止出现任何 retry 代码。
    """

    def __init__(self, validator: StateValidator):
        self.validator = validator

    async def execute_with_retry(
        self,
        operation_fn,
        config: RetryConfig,
        operation_name: str,
        page,
        manifest: dict,
        expected_state: str,
        retryable_exceptions=(SelectorFailedError, PageTimeoutError),
    ):
        """
        执行操作，按 config 策略 retry。
        每次 retry 前调用 detect_state() 确认状态未变。
        若 detect_state() 返回 'unknown'，视为不稳定观测，继续重试。
        """
        last_error = None
        for attempt in range(config.max_attempts):
            try:
                result = await operation_fn()
                log_event(
                    logger, "INFO", "retry_success",
                    operation=operation_name,
                    attempt=attempt + 1,
                )
                return result, {"attempts": attempt + 1, "succeeded": True}
            except retryable_exceptions as e:
                last_error = e
                if attempt >= config.max_attempts - 1:
                    raise

                if config.max_attempts == 1:
                    raise

                current_state, detected_by = await self.validator.detect_state(page, manifest)

                if current_state == "unknown":
                    log_event(
                        logger, "INFO", "retry_unknown_state",
                        operation=operation_name,
                        attempt=attempt + 1,
                    )
                elif current_state != expected_state:
                    raise StateChangedError(
                        f"状态从 '{expected_state}' 变为 '{current_state}'，终止 retry",
                        new_state=current_state,
                        attempts_before_change=attempt + 1,
                        trigger_url=page.url,
                        detected_by=detected_by,
                    )

                delay = (
                    config.base_delay_ms * (config.backoff_multiplier ** attempt)
                    + random.uniform(0, config.jitter_ms)
                )
                log_event(
                    logger, "WARNING", "retry_failure",
                    operation=operation_name,
                    attempt=attempt + 1,
                    max_attempts=config.max_attempts,
                    state=current_state,
                    delay_ms=round(delay),
                )
                await asyncio.sleep(delay / 1000)

            except Exception:
                raise

        raise last_error


class DecisionRouter:
    """
    核心路由：确定性路径 → retry（状态未变） → fallback，三层递进。
    StateChangedError 触发时，重新进入 FSM 分支而非 fallback。
    """

    def __init__(
        self,
        retry: RetryOrchestrator,
        session_store: SessionStore,
        visual_client=None,
    ):
        self.retry = retry
        self.session_store = session_store
        self.visual_client = visual_client

    async def execute_extract(self, page, session: Session, adapter, manifest) -> dict:
        config = RETRY_CONFIGS["extract"]
        try:
            result, retry_info = await self.retry.execute_with_retry(
                lambda: adapter.extract(page, session.current_state),
                config=config,
                operation_name=f"extract:{session.adapter_id}:{session.current_state}",
                page=page,
                manifest=manifest,
                expected_state=session.current_state,
            )
            await self.session_store.record_retry(
                session.session_id, succeeded=retry_info["succeeded"]
            )
            return {
                "execution_path": "deterministic",
                "data": result.data,
                "retry": retry_info,
                "session_suspended": False,
                "selector_diff": None,
            }

        except StateChangedError as e:
            await self.session_store.record_state_change_interrupt(session.session_id)
            return {
                "execution_path": "state_changed",
                "data": None,
                "previous_state": session.current_state,
                "new_state": e.new_state,
                "trigger_url": e.trigger_url,
                "detected_by": e.detected_by,
                "retry": {"attempts": e.attempts_before_change, "succeeded": False},
                "message": f"操作中途状态跳转至 '{e.new_state}'，请重新调用 /browse 同步后继续。",
                "session_suspended": False,
                "selector_diff": None,
            }

        except (SelectorFailedError, PageTimeoutError) as e:
            # retry 耗尽，进入 fallback
            # state_known=True：进入 execute_extract 时 detect_state 已确认状态，状态可信
            failed_selector = e.selector if isinstance(e, SelectorFailedError) else None
            await self.session_store.record_fallback(session.session_id)
            return await self._visual_fallback(
                page, session, str(e),
                state_known=True,
                failed_selector=failed_selector,
            )

    async def execute_act(
        self, page, session: Session, action, params, adapter, manifest, is_idempotent
    ) -> dict:
        config = (
            RETRY_CONFIGS["act_idempotent"]
            if is_idempotent
            else RETRY_CONFIGS["act_non_idempotent"]
        )
        try:
            result, retry_info = await self.retry.execute_with_retry(
                lambda: adapter.act(page, action, params),
                config=config,
                operation_name=f"act:{session.adapter_id}:{action}",
                page=page,
                manifest=manifest,
                expected_state=session.current_state,
            )
            await self.session_store.record_retry(
                session.session_id, succeeded=retry_info["succeeded"]
            )
            return {
                "execution_path": "deterministic",
                "success": result.success,
                "next_state": result.next_state,
                "retry": retry_info,
                "session_suspended": False,
                "selector_diff": None,
                **({"data": result.data} if result.data else {}),
                **({"side_effect_hint": result.side_effect_hint} if result.side_effect_hint else {}),
            }

        except StateChangedError as e:
            await self.session_store.record_state_change_interrupt(session.session_id)
            return {
                "execution_path": "state_changed",
                "success": False,
                "previous_state": session.current_state,
                "new_state": e.new_state,
                "trigger_url": e.trigger_url,
                "detected_by": e.detected_by,
                "retry": {"attempts": e.attempts_before_change, "succeeded": False},
                "message": f"操作中途状态跳转至 '{e.new_state}'，请重新调用 /act 或 /browse。",
                "session_suspended": False,
                "selector_diff": None,
            }

        except (SelectorFailedError, PageTimeoutError) as e:
            if not is_idempotent:
                return {
                    "execution_path": "deterministic",
                    "success": False,
                    "retry": {"attempts": 1, "succeeded": False},
                    "error": "non_idempotent_action_failed",
                    "requires_human_decision": True,
                    "message": f"写操作失败（不安全 retry）: {e}",
                    "session_suspended": False,
                    "selector_diff": None,
                }
            # 幂等操作 retry 耗尽，state_known=True（理由同 execute_extract）
            failed_selector = e.selector if isinstance(e, SelectorFailedError) else None
            await self.session_store.record_fallback(session.session_id)
            return await self._visual_fallback(
                page, session, str(e),
                state_known=True,
                failed_selector=failed_selector,
            )

        except Exception as e:
            error_type = type(e).__name__
            if not is_idempotent:
                return {
                    "execution_path": "deterministic",
                    "success": False,
                    "retry": {"attempts": 1, "succeeded": False},
                    "error": f"unexpected_error:{error_type}",
                    "requires_human_decision": True,
                    "message": f"非预期异常 ({error_type}): {e}",
                    "session_suspended": False,
                    "selector_diff": None,
                }
            await self.session_store.record_fallback(session.session_id)
            return await self._visual_fallback(
                page, session, f"{error_type}: {e}",
                state_known=True,
            )

    async def _visual_fallback(
        self,
        page,
        session,
        error_context: str,
        state_known: bool = False,
        failed_selector: str | None = None,
    ) -> dict:
        """
        视觉兜底：截图 + 调用视觉模型。
        不自动执行任何操作，只返回分析结果给 Agent。

        state_known=True：detect_state 已确认状态，session 不 suspend。
        state_known=False（默认）：状态不可信，session 标记为 suspended。
        """
        screenshot = await page.screenshot(type="jpeg", quality=80)
        screenshot_b64 = base64.b64encode(screenshot).decode()

        selector_diff = {
            "failed_selector": failed_selector,
            "error_context": error_context,
        } if failed_selector else None

        if not self.visual_client:
            return {
                "execution_path": "visual_fallback",
                "fallback_result": None,
                "selector_diff": selector_diff,
                "retry": {"attempts": None, "succeeded": False},
                "error": "visual_model_not_configured",
                "session_suspended": not state_known,
                "message": (
                    "Adapter 数据选择器失效，未配置视觉模型。"
                    + ("session 已挂起，请调用 /browse 重新同步。" if not state_known
                       else "session 状态仍有效，可继续操作或调用 /browse 重新提取。")
                ),
            }

        response = await self.visual_client.analyze(screenshot_b64, error_context)
        return {
            "execution_path": "visual_fallback",
            "fallback_result": {
                "screenshot_base64": screenshot_b64,
                "visual_model_response": response,
            },
            "selector_diff": selector_diff,
            "retry": {"attempts": None, "succeeded": False},
            "session_suspended": not state_known,
            "message": (
                "Adapter 数据选择器失效，已转视觉模型分析。"
                + ("session 已挂起，需调用 /browse 重新同步后继续。" if not state_known
                   else "session 状态仍有效，视觉分析结果供参考。")
            ),
        }
