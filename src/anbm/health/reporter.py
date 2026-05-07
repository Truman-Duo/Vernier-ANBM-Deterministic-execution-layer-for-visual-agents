import json
import logging
import os
from datetime import datetime, timezone

import httpx

from anbm.health.models import AlertEvent, DegradationReason

logger = logging.getLogger(__name__)

REASON_MESSAGES = {
    DegradationReason.SELECTOR_CHANGED: "建议运行 `anbm repair {id}` 更新选择器",
    DegradationReason.STRUCTURE_CHANGED: "建议运行 `anbm repair {id}` 重新审视状态机",
    DegradationReason.URL_MOVED: "检查 manifest 的 url_patterns 和 test_url",
    DegradationReason.SERVICE_DOWN: "网站可能宕机，暂无需操作",
    DegradationReason.AUTH_REQUIRED: "test_url 触发了登录墙，更换为无需登录的页面",
}


class AlertReporter:
    """
    告警输出器。
    通过环境变量配置三种输出方式，可同时启用多个。
    """

    def __init__(self):
        self.log_enabled = os.getenv("ANBM_ALERT_LOG", "true").lower() == "true"
        self.webhook_url = os.getenv("ANBM_ALERT_WEBHOOK", "").strip()
        self.file_path = os.getenv("ANBM_ALERT_FILE", "").strip()
        self._http_client = httpx.AsyncClient(timeout=10.0)

    async def emit(self, event: AlertEvent) -> None:
        tasks = []
        if self.log_enabled:
            tasks.append(self._log_event(event))
        if self.webhook_url:
            tasks.append(self._webhook_event(event))
        if self.file_path:
            tasks.append(self._file_event(event))
        for t in tasks:
            await t

    async def _log_event(self, event: AlertEvent) -> None:
        msg = self._format_message(event)
        logger.warning(
            "[ALERT] adapter=%s status=%s->%s reason=%s msg=%s",
            event.adapter_id,
            (event.previous_status.value if event.previous_status else "none"),
            event.current_status.value,
            event.reason.value if event.reason else "none",
            msg,
        )

    async def _webhook_event(self, event: AlertEvent) -> None:
        payload = self._to_json(event)
        try:
            resp = await self._http_client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Alert webhook failed: %s", e)

    async def _file_event(self, event: AlertEvent) -> None:
        payload = self._to_json(event)
        try:
            os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Alert file write failed: %s", e)

    def _format_message(self, event: AlertEvent) -> str:
        if event.reason:
            return REASON_MESSAGES.get(event.reason, "").format(id=event.adapter_id)
        return ""

    def _to_json(self, event: AlertEvent) -> dict:
        return {
            "adapter_id": event.adapter_id,
            "previous_status": event.previous_status.value if event.previous_status else None,
            "current_status": event.current_status.value,
            "reason": event.reason.value if event.reason else None,
            "message": self._format_message(event),
            "failed_selectors": [
                {
                    "selector": rs.selector,
                    "state": rs.state,
                    "candidates": [c.to_dict() for c in rs.candidates],
                }
                for rs in event.failed_selectors[:10]
            ],
            "triggered_at": event.triggered_at.isoformat(),
            "report": {
                "checked_at": event.report.checked_at.isoformat(),
                "response_time_ms": event.report.response_time_ms,
                "detected_state": event.report.detected_state,
            },
        }
