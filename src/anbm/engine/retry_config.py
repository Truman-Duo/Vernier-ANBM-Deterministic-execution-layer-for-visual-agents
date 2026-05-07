import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    max_attempts: int
    base_delay_ms: int
    backoff_multiplier: float
    jitter_ms: int


RETRY_CONFIGS = {
    "extract": RetryConfig(
        max_attempts=3,
        base_delay_ms=1000,
        backoff_multiplier=2.0,
        jitter_ms=200,
    ),
    "navigate": RetryConfig(
        max_attempts=2,
        base_delay_ms=2000,
        backoff_multiplier=1.5,
        jitter_ms=300,
    ),
    "act_idempotent": RetryConfig(
        max_attempts=2,
        base_delay_ms=1500,
        backoff_multiplier=1.0,
        jitter_ms=100,
    ),
    "act_non_idempotent": RetryConfig(
        max_attempts=1,
        base_delay_ms=0,
        backoff_multiplier=1.0,
        jitter_ms=0,
    ),
}

# 环境变量覆盖表： (config_key, attr, env_var)
_ENV_OVERRIDES = [
    ("extract", "max_attempts", "ANBM_RETRY_EXTRACT_MAX"),
    ("extract", "base_delay_ms", "ANBM_RETRY_EXTRACT_DELAY"),
    ("navigate", "max_attempts", "ANBM_RETRY_NAVIGATE_MAX"),
    ("navigate", "base_delay_ms", "ANBM_RETRY_NAVIGATE_DELAY"),
    ("act_idempotent", "max_attempts", "ANBM_RETRY_ACT_MAX"),
    ("act_idempotent", "base_delay_ms", "ANBM_RETRY_ACT_DELAY"),
]


def _apply_env_overrides():
    """从环境变量读取覆盖值，应用到 RETRY_CONFIGS。
    非幂等操作（act_non_idempotent）不受环境变量覆盖，保持 max_attempts=1。
    """
    for config_key, attr, env_var in _ENV_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is not None:
            try:
                val = int(raw)
                setattr(RETRY_CONFIGS[config_key], attr, val)
                logger.info(
                    "[RETRY_CONFIG] %s.%s overridden to %s via %s",
                    config_key, attr, val, env_var,
                )
            except (ValueError, KeyError) as e:
                logger.warning(
                    "[RETRY_CONFIG] invalid override %s=%s: %s",
                    env_var, raw, e,
                )


_apply_env_overrides()
