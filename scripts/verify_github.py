"""
GitHub Issues 真实环境验证脚本。

用法：
  export GITHUB_TEST_REPO="owner/repo"
  export GITHUB_SESSION_COOKIE='[{"name":"user_session","value":"...","domain":"github.com"}]'
  python scripts/verify_github.py

如果未设置环境变量，脚本跳过真实验证并输出提示。
"""

import json
import os
import sys
import time

import httpx

from benchmark.recorder import BenchmarkRecorder

API_BASE = os.environ.get("ANBM_API_BASE", "http://localhost:8000")


def _extract_metrics(resp: dict) -> dict:
    """从 API 响应中提取 benchmark 所需字段。"""
    return {
        "execution_path": resp.get("execution_path", "unknown"),
        "retry_attempts": resp.get("retry", {}).get("attempts", 0),
        "success": resp.get("session_suspended") is False and resp.get("execution_path") != "visual_fallback",
        "selector_diff": resp.get("selector_diff"),
        "error": resp.get("error"),
    }


def require_env(name: str) -> str | None:
    val = os.environ.get(name)
    if not val:
        print(f"[SKIP] 环境变量 {name} 未设置，跳过真实网络验证。")
    return val


def print_result(step: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {step}" + (f" — {detail}" if detail else ""))


async def verify_github(recorder):
    repo = require_env("GITHUB_TEST_REPO")
    cookie_json = require_env("GITHUB_SESSION_COOKIE")
    if not repo or not cookie_json:
        return False

    cookies = json.loads(cookie_json)

    async with httpx.AsyncClient(base_url=API_BASE, timeout=120, trust_env=False) as client:
        # --- Step 1: Browse to issue list ---
        print("\n  Step 1: POST /browse to issue list")
        recorder.step_start()
        url = f"https://github.com/{repo}/issues"
        resp = await client.post("/browse", json={
            "url": url,
            "adapter_hint": "github_issues",
            "cookies": cookies,
        })
        if resp.status_code != 200:
            print(f"    状态码: {resp.status_code}, 响应: {resp.text[:300]}")
            return False
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("browse_issue_list", **m)
        ok = resp.status_code == 200 and m["execution_path"] == "deterministic"
        print_result("browse_issue_list", ok,
                     f"attempts={m['retry_attempts']}")
        if not ok:
            print(f"    响应: {json.dumps(body, ensure_ascii=False)[:200]}")
            return False

        session_id = body.get("session_id")
        assert body.get("current_state") == "issue_list", \
            f"expected issue_list, got {body.get('current_state')}"

        # --- Step 2: Open an issue ---
        print("\n  Step 2: POST /act open_issue")
        issues = body.get("data", {}).get("issues", [])
        if not issues:
            print("  [SKIP] 没有找到 issue")
            return False

        issue_url = issues[0].get("url", "")
        recorder.step_start()
        resp = await client.post("/act", json={
            "session_id": session_id,
            "action": "open_issue",
            "params": {"url": issue_url},
        })
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("open_issue", **m)
        ok = resp.status_code == 200 and m["execution_path"] == "deterministic"
        print_result("open_issue", ok,
                     f"attempts={m['retry_attempts']}")
        if not ok:
            print(f"    响应: {json.dumps(body, ensure_ascii=False)[:200]}")
            return False

        # --- Step 3: Extract issue content ---
        print("\n  Step 3: POST /browse (extract issue detail)")
        recorder.step_start()
        resp = await client.post("/browse", json={
            "session_id": session_id,
            "url": issue_url,
        })
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("extract_content", **m)
        ok = resp.status_code == 200 and m["execution_path"] == "deterministic"
        data = body.get("data", {})
        print_result("extract_content", ok,
                     f"attempts={m['retry_attempts']}")
        if ok and data:
            print(f"    title:  {data.get('title', '')[:80]}")
            print(f"    state:  {data.get('state', '')}")
            print(f"    comments: {len(data.get('comments', []))}")

        # --- Step 4: Session summary ---
        print(f"\n  Session: {session_id}")
        return True


async def main():
    print("=" * 60)
    print("GitHub Issues 真实环境验证")
    print("=" * 60)

    recorder = BenchmarkRecorder(adapter_id="github_issues")
    overall_success = await verify_github(recorder)

    # 计算整体是否成功（所有步骤 deterministic，无 fallback）
    all_steps = recorder._steps
    overall_success = overall_success and all(
        s.execution_path == "deterministic" for s in all_steps
    ) if all_steps else False

    # 保存旧版 baseline（兼容）
    if all_steps:
        baseline = {
            "date": time.strftime("%Y-%m-%d"),
            "adapter_version": "1.0.0",
            "operations": [
                {"action": s.step_name, "attempts": s.retry_attempts}
                for s in all_steps
            ],
            "fallback_count": sum(
                1 for s in all_steps if s.execution_path == "visual_fallback"
            ),
        }
        baselines_dir = os.path.join(
            os.path.dirname(__file__), "..", "docs", "baselines"
        )
        os.makedirs(baselines_dir, exist_ok=True)
        path = os.path.join(
            baselines_dir, f"github_issues_{time.strftime('%Y-%m-%d')}.json"
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        print(f"\n  Baseline 已保存: {path}")

    output_path = recorder.save(overall_success=overall_success)
    recorder.print_summary(output_path)

    print("\n" + "=" * 60)
    if overall_success:
        print("结果: 全部 PASS")
    else:
        print("结果: 部分 FAIL（详情见上）")
    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
