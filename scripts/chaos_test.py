"""
破坏性演练脚本 — 验证系统在 Adapter 失效时的行为。

模拟 douban_movie 适配器 selector 失效，验证：
1. 健康检查返回 degraded + detected_by
2. browse 重试 3 次后进入 visual_fallback
3. retry_stats.fallback_count 正确
4. 恢复后健康检查恢复正常

用法：
  # 启动服务（新终端）：
  #   uvicorn anbm.api.server:app --reload --port 8000
  # 运行本脚本：
  python scripts/chaos_test.py
"""

import json
import os
import shutil
import sys
import time

import httpx

HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "adapters", "douban_movie", "handler.py"
)
BACKUP_PATH = HANDLER_PATH + ".bak"
API_BASE = os.environ.get("ANBM_API_BASE", "http://localhost:8000")

# 被替换的关键选择器和目标值
TARGET_SELECTOR = "ol.grid_view div.item"
BROKEN_SELECTOR = ".js-broken-selector"


def print_separator(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_step(step: int, total: int, desc: str):
    print(f"\n--- Step {step}/{total}: {desc} ---")


def print_result(ok: bool, detail: str = ""):
    status = "[OK] PASS" if ok else "[FAIL]"
    print(f"  {status}" + (f" — {detail}" if detail else ""))


def backup_handler():
    """备份原始 handler.py。"""
    shutil.copy2(HANDLER_PATH, BACKUP_PATH)
    print(f"  备份已创建: {BACKUP_PATH}")


def break_selector():
    """将目标选择器替换为无效值。"""
    with open(HANDLER_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert TARGET_SELECTOR in content, f"在 handler.py 中未找到选择器 '{TARGET_SELECTOR}'"
    content = content.replace(TARGET_SELECTOR, BROKEN_SELECTOR)
    with open(HANDLER_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  选择器 '{TARGET_SELECTOR}' → '{BROKEN_SELECTOR}'")


def restore_handler():
    """从备份文件恢复 handler.py。"""
    if not os.path.isfile(BACKUP_PATH):
        print("  [WARN] 备份文件不存在，跳过恢复")
        return
    shutil.copy2(BACKUP_PATH, HANDLER_PATH)
    os.remove(BACKUP_PATH)
    print(f"  已从备份恢复: {HANDLER_PATH}")


async def health_check(client: httpx.AsyncClient, expected_status: str) -> bool:
    """调用健康检查端点并验证状态。"""
    resp = await client.get("/health/adapter/douban_movie")
    body = resp.json()
    actual = body.get("status")
    ok = actual == expected_status
    detail = f"status={actual}, detected_state={body.get('detected_state')}, detected_by={body.get('detected_by')}"
    print_result(ok, detail)
    return ok


async def main():
    print_separator("ANBM 破坏性演练 — Chaos Test")

    # === Setup ===
    total_steps = 7

    # Step 0: 备份
    print_step(0, total_steps, "备份原始 handler.py")
    backup_handler()

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30, trust_env=False) as client:
        try:
            # Step 1: 替换选择器
            print_step(1, total_steps, "破坏选择器 → 模拟 Adapter 失效")
            break_selector()

            # Step 2: 健康检查 → degraded
            print_step(2, total_steps, "GET /health/adapter/douban_movie → degraded")
            ok = await health_check(client, "degraded")
            if not ok:
                print("  [ABORT] 健康检查未返回 degraded，跳过后续步骤")
                return

            # Step 3: browse → visual_fallback (3 retries)
            print_step(3, total_steps, "POST /browse → visual_fallback (retry × 3)")
            resp = await client.post("/browse", json={
                "url": "https://movie.douban.com/top250",
                "adapter_hint": "douban_movie",
            })
            body = resp.json()
            path = body.get("execution_path")
            retry = body.get("retry", {})
            suspended = body.get("session_suspended")
            ok = (path == "visual_fallback"
                  and retry.get("attempts") == 3
                  and suspended is True)
            print_result(ok,
                         f"execution_path={path}, retry.attempts={retry.get('attempts')}, "
                         f"suspended={suspended}")
            if not ok:
                print(f"    响应: {json.dumps(body, ensure_ascii=False)[:300]}")

            # Step 4: 检查 retry_stats.fallback_count
            print_step(4, total_steps, "GET /session/{id} → fallback_count == 1")
            session_id = body.get("session_id", "")
            if session_id:
                resp = await client.get(f"/session/{session_id}")
                sbody = resp.json()
                fallback_count = sbody.get("retry_stats", {}).get("fallback_count", 0)
                ok = fallback_count == 1
                print_result(ok, f"fallback_count={fallback_count}")
            else:
                print_result(False, "没有 session_id")

            # Step 5: 恢复选择器
            print_step(5, total_steps, "恢复原始选择器")
            restore_handler()

            # Step 6: 健康检查 → healthy
            print_step(6, total_steps, "GET /health/adapter/douban_movie → healthy")
            ok = await health_check(client, "healthy")

            # Step 7: 清理备份
            print_step(7, total_steps, "清理备份文件")
            if os.path.isfile(BACKUP_PATH):
                os.remove(BACKUP_PATH)
                print("  备份已清理")

        except Exception as e:
            print(f"\n  [ERROR] {e}")
            restore_handler()
            raise

    print_separator("演练完成")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
