"""Structured logging configuration.

用法：
    from anbm.logging_config import log_event

    log_event(logger, "INFO", "session_created", session_id=sid, adapter="hackernews")

环境变量 ANBM_LOG_FORMAT=json 时输出 JSON 格式（生产环境用），
默认（text）保持人类可读（与现有行为兼容）。
"""

import json
import logging
import os
from datetime import datetime, timezone

_LOG_FORMAT = os.environ.get("ANBM_LOG_FORMAT", "text")


def log_event(logger: logging.Logger, level: str, event: str, **kwargs):
    """输出结构化或文本格式的日志。"""
    if _LOG_FORMAT == "json":
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": logger.name,
            "event": event,
            **kwargs,
        }
        level_method = getattr(logger, level.lower(), logger.info)
        level_method(json.dumps(record, ensure_ascii=False, default=str))
    else:
        parts = [f"[{event}]"]
        for k, v in kwargs.items():
            parts.append(f"{k}={v}")
        msg = " ".join(parts)
        level_method = getattr(logger, level.lower(), logger.info)
        level_method(msg)
