#!/usr/bin/env python3
"""
HackerNews verify 脚本。

使用方法：
    uvicorn anbm.api.server:app --port 8000 &
    python scripts/verify_hackernews.py

可重复运行，每次结果独立记录到 scripts/benchmark/results/。
"""

import sys
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from benchmark.recorder import BenchmarkRecorder

BASE_URL = "http://localhost:8000"
HN_URL = "https://news.ycombinator.com/news"


def _extract_metrics(resp: dict) -> dict:
    """从 API 响应中提取 benchmark 所需字段。"""
    return {
        "execution_path": resp.get("execution_path", "unknown"),
        "retry_attempts": resp.get("retry", {}).get("attempts", 0),
        "success": resp.get("session_suspended") is False and resp.get("execution_path") != "visual_fallback",
        "selector_diff": resp.get("selector_diff"),
        "error": resp.get("error"),
    }


def main():
    recorder = BenchmarkRecorder(adapter_id="hackernews")
    session_id = None
    overall_success = False

    with httpx.Client(timeout=60, trust_env=False) as client:
        # Step 1: browse 首页
        print("Step 1: browse 首页...")
        recorder.step_start()
        resp = client.post(f"{BASE_URL}/browse", json={
            "url": HN_URL,
            "adapter_hint": "hackernews",
        }).json()

        m = _extract_metrics(resp)
        session_id = resp.get("session_id")
        recorder.record_step("browse_news_list", **m)

        if not m["success"]:
            print(f"  [FAIL] browse 失败: execution_path={m['execution_path']}")
            if m["selector_diff"]:
                print(f"    失效 selector: {m['selector_diff'].get('failed_selector')}")
            output_path = recorder.save(overall_success=False)
            recorder.print_summary(output_path)
            sys.exit(1)

        stories = resp.get("data", {}).get("stories", [])
        print(f"  [OK] 提取到 {len(stories)} 条新闻，retry={m['retry_attempts']}")

        # Step 2-4: 连续翻页 3 次
        for i in range(1, 4):
            print(f"Step {i + 1}: paginate #{i}...")
            recorder.step_start()
            resp = client.post(f"{BASE_URL}/act", json={
                "session_id": session_id,
                "action": "paginate",
            }).json()

            m = _extract_metrics(resp)
            recorder.record_step(f"paginate_{i}", **m)

            if not m["success"]:
                print(f"  [FAIL] 翻页失败: execution_path={m['execution_path']}")
                if m["selector_diff"]:
                    print(f"    失效 selector: {m['selector_diff'].get('failed_selector')}")
            else:
                print(f"  [OK] 翻页成功，retry={m['retry_attempts']}")

        # Step 5: 打开第一条新闻的详情
        if stories:
            print("Step 5: open_item（打开第一条新闻）...")
            recorder.step_start()
            resp = client.post(f"{BASE_URL}/act", json={
                "session_id": session_id,
                "action": "open_item",
                "params": {"url": f"https://news.ycombinator.com/item?id={stories[0].get('id', '')}"},
            }).json()

            m = _extract_metrics(resp)
            recorder.record_step("open_item", **m)
            print(f"  {'[OK]' if m['success'] else '[FAIL]'} open_item: execution_path={m['execution_path']}, retry={m['retry_attempts']}")

        # 判断整体是否成功（所有步骤 success 为 True，即无 fallback/崩溃）
        all_steps = recorder._steps
        overall_success = all(s.success for s in all_steps)

    # 清理 session
    if session_id:
        with httpx.Client(timeout=10, trust_env=False) as client:
            client.delete(f"{BASE_URL}/session/{session_id}")

    output_path = recorder.save(overall_success=overall_success)
    recorder.print_summary(output_path)

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
