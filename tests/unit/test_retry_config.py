"""Tests for retry_config environment variable overrides."""
import importlib
import os

import anbm.engine.retry_config as rc


def test_env_var_override():
    """设置环境变量后，extract 的 max_attempts 和 base_delay_ms 反映新值。"""
    original_max = rc.RETRY_CONFIGS["extract"].max_attempts
    original_delay = rc.RETRY_CONFIGS["extract"].base_delay_ms

    os.environ["ANBM_RETRY_EXTRACT_MAX"] = "5"
    os.environ["ANBM_RETRY_EXTRACT_DELAY"] = "2000"
    importlib.reload(rc)

    try:
        assert rc.RETRY_CONFIGS["extract"].max_attempts == 5
        assert rc.RETRY_CONFIGS["extract"].base_delay_ms == 2000
        assert rc.RETRY_CONFIGS["navigate"].max_attempts == 2
    finally:
        os.environ.pop("ANBM_RETRY_EXTRACT_MAX", None)
        os.environ.pop("ANBM_RETRY_EXTRACT_DELAY", None)
        importlib.reload(rc)


def test_non_idempotent_not_overridable():
    """非幂等操作不受环境变量覆盖，max_attempts 保持为 1。"""
    assert rc.RETRY_CONFIGS["act_non_idempotent"].max_attempts == 1


def test_no_env_var_uses_defaults():
    """环境变量不存在时使用默认值。"""
    for key in ["ANBM_RETRY_EXTRACT_MAX", "ANBM_RETRY_EXTRACT_DELAY"]:
        os.environ.pop(key, None)
    importlib.reload(rc)

    try:
        assert rc.RETRY_CONFIGS["extract"].max_attempts == 3
        assert rc.RETRY_CONFIGS["extract"].base_delay_ms == 1000
    finally:
        importlib.reload(rc)
