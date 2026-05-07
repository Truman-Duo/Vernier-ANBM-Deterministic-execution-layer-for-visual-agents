"""Unit tests for CLI repair command."""
import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from anbm.cli.__main__ import cli


@pytest.fixture
def mock_httpx(monkeypatch):
    """Mock httpx to return fake health check responses."""
    import httpx

    class MockResponse:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("Error", request=None, response=self)

    def mock_post(url, **kwargs):
        return MockResponse({
            "adapter_id": "test_adapter",
            "adapter_version": "1.0.0",
            "status": "degraded",
            "reason": "selector_changed",
            "detected_state": "unknown",
            "final_url": "https://example.com",
            "response_time_ms": 100,
            "selector_results": [
                {
                    "selector": "ol.grid_view",
                    "state": "list",
                    "found": False,
                    "candidates": [
                        {"selector": "div.new_list", "source": "css_similar", "similarity": 0.65},
                        {"selector": "ul.grid_list", "source": "css_similar", "similarity": 0.42},
                    ],
                    "similarity_scores": [0.65, 0.42],
                },
                {
                    "selector": "span.title",
                    "state": "list",
                    "found": True,
                    "candidates": [],
                    "similarity_scores": [],
                },
            ],
            "raw_error": None,
        })

    monkeypatch.setattr(httpx, "post", mock_post)


def _setup_temp_adapter():
    """Create a temp adapter dir and return (tmpdir, adapter_dir) paths."""
    tmpdir = tempfile.mkdtemp()
    adapter_dir = os.path.join(tmpdir, "test_adapter")
    os.makedirs(adapter_dir, exist_ok=True)

    handler_path = os.path.join(adapter_dir, "handler.py")
    with open(handler_path, "w", encoding="utf-8") as f:
        f.write(
            'async def extract_list(page):\n'
            '    el = await page.query_selector("ol.grid_view")\n'
            '    return el.text_content()\n'
        )

    manifest_path = os.path.join(adapter_dir, "manifest.json")
    manifest = {
        "id": "test_adapter",
        "version": "1.0.0",
        "states": {},
        "url_patterns": [],
        "action_idempotency": {},
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return tmpdir, adapter_dir


def _patch_repair_functions(monkeypatch, tmpdir, adapter_dir):
    """Patch repair module functions to use temp dir."""
    import anbm.cli.repair as repair_mod

    def mock_get_path(aid):
        return os.path.join(adapter_dir, "handler.py")

    def mock_read(aid):
        p = mock_get_path(aid)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
        return None

    def mock_write_handler(aid, content):
        p = mock_get_path(aid)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    def mock_write_manifest(aid, manifest):
        p = os.path.join(adapter_dir, "manifest.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

    def mock_load(aid):
        p = os.path.join(adapter_dir, "manifest.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return None

    monkeypatch.setattr(repair_mod, "_get_handler_path", mock_get_path)
    monkeypatch.setattr(repair_mod, "_read_handler", mock_read)
    monkeypatch.setattr(repair_mod, "_write_handler", mock_write_handler)
    monkeypatch.setattr(repair_mod, "_write_manifest", mock_write_manifest)
    monkeypatch.setattr(repair_mod, "_load_manifest", mock_load)

    return mock_read, mock_get_path


def test_dry_run_no_write(mock_httpx):
    """--dry-run 时展示诊断但不调用任何写操作。"""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["repair", "test_adapter", "--dry-run", "-u", "http://localhost:9999"],
    )
    assert result.exit_code == 0
    assert "dry-run" in result.output.lower() or "诊断" in result.output
    assert "写入完成" not in result.output


def test_repair_writes_on_confirm(mock_httpx, monkeypatch):
    """模拟用户确认，验证 handler.py 和 manifest.json 被正确修改。"""
    tmpdir, adapter_dir = _setup_temp_adapter()
    try:
        _patch_repair_functions(monkeypatch, tmpdir, adapter_dir)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "test_adapter", "-u", "http://localhost:9999"],
            input="y\n1\ny\n",
        )

        assert result.exit_code == 0
        assert "写入完成" in result.output

        handler_path = os.path.join(adapter_dir, "handler.py")
        with open(handler_path, encoding="utf-8") as f:
            content = f.read()
        assert "div.new_list" in content
        assert "ol.grid_view" not in content

        manifest_path = os.path.join(adapter_dir, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["version"] == "1.0.1"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_repair_restores_on_write_failure(mock_httpx, monkeypatch):
    """写入失败时从 .bak 恢复。"""
    tmpdir, adapter_dir = _setup_temp_adapter()
    try:
        import anbm.cli.repair as repair_mod

        original_handler = (
            'async def extract_list(page):\n'
            '    el = await page.query_selector("ol.grid_view")\n'
            '    return el.text_content()\n'
        )
        handler_path = os.path.join(adapter_dir, "handler.py")
        with open(handler_path, "w", encoding="utf-8") as f:
            f.write(original_handler)

        def mock_get_path(aid):
            return os.path.join(adapter_dir, "handler.py")

        def mock_read(aid):
            p = mock_get_path(aid)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return f.read()
            return None

        def mock_load(aid):
            p = os.path.join(adapter_dir, "manifest.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            return None

        def mock_write_handler_fail(aid, content):
            raise OSError("模拟写入失败")

        monkeypatch.setattr(repair_mod, "_get_handler_path", mock_get_path)
        monkeypatch.setattr(repair_mod, "_read_handler", mock_read)
        monkeypatch.setattr(repair_mod, "_load_manifest", mock_load)
        monkeypatch.setattr(repair_mod, "_write_handler", mock_write_handler_fail)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "test_adapter", "-u", "http://localhost:9999"],
            input="y\n1\ny\n",
        )

        assert "写入失败" in result.output or "恢复" in result.output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_repair_skips_all(mock_httpx, monkeypatch):
    """所有选择器都跳过时，不写入任何文件。"""
    tmpdir, adapter_dir = _setup_temp_adapter()
    try:
        import anbm.cli.repair as repair_mod

        def mock_load(aid):
            p = os.path.join(adapter_dir, "manifest.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            return None

        monkeypatch.setattr(repair_mod, "_load_manifest", mock_load)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "test_adapter", "-u", "http://localhost:9999"],
            input="y\n0\n",
        )

        assert result.exit_code == 0
        assert "未选择任何替换" in result.output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_bak_backup_survives_write_failure(mock_httpx, monkeypatch):
    """
    验证：写入 handler.py 中途抛异常时，.bak 文件存在，原 handler.py 内容未被破坏。

    场景：
    1. 创建临时目录，写入模拟 handler.py 内容
    2. repair.py 的写入阶段 mock 为在写入一半时抛出 IOError
    3. 断言：.bak 文件存在且内容与原始 handler.py 一致
    4. 断言：原 handler.py 内容未变（或已从 .bak 恢复，取决于实现）
    """
    tmpdir, adapter_dir = _setup_temp_adapter()
    try:
        import anbm.cli.repair as repair_mod

        original_handler = (
            'async def extract_list(page):\n'
            '    el = await page.query_selector("ol.grid_view")\n'
            '    return el.text_content()\n'
        )
        handler_path = os.path.join(adapter_dir, "handler.py")
        with open(handler_path, "w", encoding="utf-8") as f:
            f.write(original_handler)

        def mock_get_path(aid):
            return os.path.join(adapter_dir, "handler.py")

        def mock_read(aid):
            p = mock_get_path(aid)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return f.read()
            return None

        def mock_load(aid):
            p = os.path.join(adapter_dir, "manifest.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            return None

        def mock_write_handler_fail(aid, content):
            """模拟写入中途失败的场景：备份已创建，写入时抛异常。"""
            # 先写入部分内容模拟部分写入
            p = mock_get_path(aid)
            with open(p, "w", encoding="utf-8") as f:
                f.write("# partial write - corrupted\n")
            raise IOError("模拟写入中途失败")

        monkeypatch.setattr(repair_mod, "_get_handler_path", mock_get_path)
        monkeypatch.setattr(repair_mod, "_read_handler", mock_read)
        monkeypatch.setattr(repair_mod, "_load_manifest", mock_load)
        monkeypatch.setattr(repair_mod, "_write_handler", mock_write_handler_fail)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repair", "test_adapter", "-u", "http://localhost:9999"],
            input="y\n1\ny\n",
        )

        # 验证 .bak 文件存在且内容与原始 handler.py 一致
        bak_path = handler_path + ".bak"
        assert os.path.isfile(bak_path), ".bak 文件应存在"
        with open(bak_path, encoding="utf-8") as f:
            bak_content = f.read()
        assert bak_content == original_handler, ".bak 内容应与原始 handler.py 一致"

        # 验证 handler.py 内容未变或已从 .bak 恢复
        with open(handler_path, encoding="utf-8") as f:
            restored_content = f.read()
        assert restored_content == original_handler, "handler.py 内容应已恢复为原始内容"

        # 验证输出中包含恢复相关信息
        assert "写入失败" in result.output or "恢复" in result.output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
