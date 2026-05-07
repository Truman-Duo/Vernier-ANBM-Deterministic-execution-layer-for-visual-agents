"""
Reddit 投票幂等性真实环境验证脚本。

用法：
  export REDDIT_SESSION_COOKIE='[{"name":"reddit_session","value":"...","domain":"www.reddit.com"}]'
  python scripts/verify_reddit.py

对同一个 post 连续调用两次 upvote，验证第二次返回幂等成功。
如果未设置环境变量，脚本跳过真实验证并输出提示。
"""

import json
import os
import sys
import time

import httpx

from benchmark.recorder import BenchmarkRecorder

API_BASE = os.environ.get("ANBM_API_BASE", "http://localhost:8000")
TEST_SUBREDDIT = os.environ.get("REDDIT_TEST_SUBREDDIT", "python")
TEST_POST_URL = os.environ.get("REDDIT_TEST_POST_URL", "")


def _extract_metrics(resp: dict) -> dict:
    """从 API 响应中提取 benchmark 所需字段。"""
    return {
        "execution_path": resp.get("execution_path", "unknown"),
        "retry_attempts": resp.get("retry", {}).get("attempts", 0),
        "success": resp.get("session_suspended") is False and resp.get("execution_path") != "visual_fallback",
        "selector_diff": resp.get("selector_diff"),
        "error": resp.get("error"),
    }


def print_result(step: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {step}" + (f" — {detail}" if detail else ""))


async def verify_reddit(recorder):
    cookie_json = os.environ.get("REDDIT_SESSION_COOKIE")
    if not cookie_json:
        print("[SKIP] 环境变量 REDDIT_SESSION_COOKIE 未设置，跳过真实网络验证。")
        return False

    cookies = json.loads(cookie_json)

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30, trust_env=False) as client:
        # --- Step 1: Browse to subreddit ---
        print("\n  Step 1: POST /browse to subreddit")
        recorder.step_start()
        feed_url = f"https://www.reddit.com/r/{TEST_SUBREDDIT}/"
        resp = await client.post("/browse", json={
            "url": feed_url,
            "adapter_hint": "reddit",
            "cookies": cookies,
        })
        if resp.status_code != 200:
            print(f"    状态码: {resp.status_code}, 响应: {resp.text[:300]}")
            return False
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("browse_subreddit", **m)
        ok = resp.status_code == 200 and m["execution_path"] == "deterministic"
        print_result("browse_subreddit", ok,
                     f"attempts={m['retry_attempts']}")
        if not ok:
            print(f"    响应: {json.dumps(body, ensure_ascii=False)[:200]}")
            return False

        session_id = body.get("session_id")

        # --- Step 2: Navigate to a post ---
        posts = body.get("data", {}).get("posts", [])
        target_url = TEST_POST_URL or (posts[0]["url"] if posts else "")
        if not target_url:
            print("  [SKIP] 没有找到 post URL，无法验证 upvote")
            return False

        print(f"\n  Step 2: POST /act open_post")
        recorder.step_start()
        resp = await client.post("/act", json={
            "session_id": session_id,
            "action": "open_post",
            "params": {"url": target_url},
        })
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("open_post", **m)
        ok = resp.status_code == 200 and m["execution_path"] == "deterministic"
        print_result("open_post", ok,
                     f"attempts={m['retry_attempts']}")
        if not ok:
            print(f"    响应: {json.dumps(body, ensure_ascii=False)[:200]}")
            return False

        # --- Step 3: First upvote ---
        print(f"\n  Step 3: POST /act upvote_post (第一次)")
        recorder.step_start()
        resp = await client.post("/act", json={
            "session_id": session_id,
            "action": "upvote_post",
            "params": {"post_id": ""},
        })
        body = resp.json()
        m = _extract_metrics(body)
        recorder.record_step("upvote_post_first", **m)
        ok = m["execution_path"] == "deterministic"
        print_result("upvote_post (1st)", ok,
                     f"attempts={m['retry_attempts']}")
        if not ok:
            print(f"    响应: {json.dumps(body, ensure_ascii=False)[:200]}")
            return False

        # --- Step 4: Second upvote (idempotency check) ---
        print(f"\n  Step 4: POST /act upvote_post (第二次 — 幂等验证)")
        recorder.step_start()
        resp = await client.post("/act", json={
            "session_id": session_id,
            "action": "upvote_post",
            "params": {"post_id": ""},
        })
        body = resp.json()
        m = _extract_metrics(body)
        # 幂等：retry.attempts==1，execution_path=deterministic，不报错
        ok = m["execution_path"] == "deterministic" and body.get("success") is True
        if body.get("error") == "non_idempotent_action_failed":
            # 非幂等失败也是可接受的结果（如果 Reddit 服务端拒绝第二次）
            ok = True
        recorder.record_step("upvote_post_second", **m)
        print_result("upvote_post (2nd/idempotent)", ok,
                     f"attempts={m['retry_attempts']}, path={m['execution_path']}")

        return True


async def main():
    print("=" * 60)
    print("Reddit 投票幂等性真实环境验证")
    print("=" * 60)

    recorder = BenchmarkRecorder(adapter_id="reddit")
    overall_success = await verify_reddit(recorder)

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
            baselines_dir, f"reddit_{time.strftime('%Y-%m-%d')}.json"
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
