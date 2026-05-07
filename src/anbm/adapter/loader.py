import importlib.util
import json
import logging
import os
import sys
import time

from anbm.adapter.base import BaseAdapter, AdapterNotFoundError

logger = logging.getLogger(__name__)

ADAPTERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
)


class AdapterLoader:

    def __init__(self):
        self._last_reload: dict[str, str] = {}

    def list_adapters(self) -> list[str]:
        """返回 adapters 目录下所有有效的 adapter ID 列表。"""
        if not os.path.isdir(ADAPTERS_DIR):
            return []
        result = []
        for entry in sorted(os.listdir(ADAPTERS_DIR)):
            manifest_path = os.path.join(ADAPTERS_DIR, entry, "manifest.json")
            if os.path.isfile(manifest_path):
                result.append(entry)
        return result

    def load_manifest(self, adapter_id: str) -> dict:
        manifest_path = os.path.join(ADAPTERS_DIR, adapter_id, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise AdapterNotFoundError(adapter_id)
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)

    def load_handler(self, adapter_id: str) -> BaseAdapter:
        handler_path = os.path.join(ADAPTERS_DIR, adapter_id, "handler.py")
        if not os.path.isfile(handler_path):
            raise AdapterNotFoundError(adapter_id)

        spec = importlib.util.spec_from_file_location(
            f"adapters.{adapter_id}.handler", handler_path
        )
        if spec is None or spec.loader is None:
            raise AdapterNotFoundError(adapter_id)

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        handler_class = getattr(module, "Handler", None)
        if handler_class is None:
            raise AdapterNotFoundError(
                f"Handler class not found in {adapter_id}"
            )

        return handler_class()

    def reload(self, adapter_id: str) -> BaseAdapter:
        """
        热重载指定 adapter 的 handler 模块。
        清除 import sys.modules 缓存后重新 load_handler。
        """
        module_name = f"adapters.{adapter_id}.handler"
        if module_name in sys.modules:
            del sys.modules[module_name]
        logger.info("Hot-reloaded handler for adapter: %s", adapter_id)
        self._last_reload[adapter_id] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime()
        )
        return self.load_handler(adapter_id)

    def get_last_reload_time(self, adapter_id: str) -> str | None:
        return self._last_reload.get(adapter_id)
