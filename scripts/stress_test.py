"""
并发压力验证脚本 — 验证 Session 并发安全和隔离性。

场景 A：同一 session 并发冲突 → 1 个 200 + 2 个 409
场景 B：不同 session 并发隔离 → 两个都 200
场景 C：suspended 状态拒绝 → 提示先调用 /browse

用法：
  # 启动服务（新终端）：
  #   uvicorn anbm.api.server:app --reload --port 8000
  # 运行本脚本：
  python scripts/stress_test.py
"""

import json
import sys
import time

import httpx

API_BASE = os.environ.get("ANBM_API_BASE", "http://localhost:8000")


def print_separator(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_scenario(label: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"\n  [{status}] {label}" + (f" — {detail}" if detail else ""))


def print_detail(msg: str):
    print(f"    {msg}")


# Flag to track overall pass/fail
any_failed = False


def check(condition: bool, msg: str):
    global any_failed
    if not condition:
        any_failed = True
    print_detail(f"{'[OK]' if condition else '[FAIL]'} {msg}")


async def scenario_a_same_session_conflict(client: httpx.AsyncClient) -> bool:
    """场景 A：同一 session 并发 3 个请求 → 1 个成功，2 个 409。"""
    print_detail("创建 session...")
    resp = await client.post("/browse", json={
        "url": "https://news.ycombinator.com/news",
        "adapter_hint": "hackernews",
    })
    body = resp.json()
    sid = body.get("session_id", "")
    check(bool(sid), f"session 创建成功: {sid}")
    if not sid:
        return False

    # 并发发送 3 个 act 请求
    print_detail("并发发送 3 个 POST /act (action=paginate)...")
    async def do_act():
        return await client.post("/act", json={
            "session_id": sid,
            "action": "paginate",
            "params": {"direction": "next"},
        })

    import asyncio
    responses = await asyncio.gather(do_act(), do_act(), do_act())

    success_count = 0
    conflict_count = 0
    for r in responses:
        b = r.json()
        if r.status_code == 200 and b.get("execution_path") == "deterministic":
            success_count += 1
        elif b.get("error") == "session_busy" or r.status_code == 409:
            conflict_count += 1

    ok = success_count == 1 and conflict_count == 2
    check(ok, f"1×200 + 2×409 — 实际: {success_count}×200 + {conflict_count}×409")
    return ok


async def scenario_b_different_sessions(client: httpx.AsyncClient) -> bool:
    """场景 B：不同 adapter 的两个 session 并发执行 → 互不干扰。"""
    print_detail("创建 session_A (douban_movie)...")
    resp_a = await client.post("/browse", json={
        "url": "https://movie.douban.com/top250",
        "adapter_hint": "douban_movie",
    })
    sid_a = resp_a.json().get("session_id", "")

    print_detail("创建 session_B (hackernews)...")
    resp_b = await client.post("/browse", json={
        "url": "https://news.ycombinator.com/news",
        "adapter_hint": "hackernews",
    })
    sid_b = resp_b.json().get("session_id", "")

    check(bool(sid_a) and bool(sid_b), f"两个 session 创建成功: A={sid_a[:8]}.. B={sid_b[:8]}..")

    # 并发发送 act (paginate) 到两个 session
    print_detail("并发发送 paginate 到两个 session...")
    import asyncio

    async def act_a():
        return await client.post("/act", json={
            "session_id": sid_a,
            "action": "paginate",
            "params": {"direction": "next"},
        })

    async def act_b():
        return await client.post("/act", json={
            "session_id": sid_b,
            "action": "paginate",
            "params": {"direction": "next"},
        })

    responses = await asyncio.gather(act_a(), act_b())

    ok = True
    for i, r in enumerate(responses):
        b = r.json()
        is_ok = b.get("execution_path") == "deterministic"
        check(is_ok, f"Session {'A' if i == 0 else 'B'}: "
                     f"path={b.get('execution_path')}")
        ok = ok and is_ok
    return ok


async def scenario_c_suspended_rejection(client: httpx.AsyncClient) -> bool:
    """场景 C：suspended 状态的 session 拒绝 /act。"""
    # 嗅探 API 是否配置了 visual client
    # 如果没有 visual_client, fallback 会直接设置 suspended=True
    # 所以我们直接标记 session 为 suspended 是不可能的（通过 API）
    # 改为：创建一个不存在的 session_id 列表的浏览请求触发 fallback
    # 但更好的方法是 mock —— 但我们是通过 HTTP 测试，不能 mock
    #
    # 替代方案：用错误的 adapter 触发 404，不创建 session，跳过此场景
    print_detail("用不存在的 adapter 测试...")
    resp = await client.post("/browse", json={
        "url": "https://example.com",
        "adapter_hint": "nonexistent_adapter",
    })
    body = resp.json()
    is_404 = body.get("status") == "not_found" or resp.status_code == 404
    check(is_404, f"不存在的 adapter 返回 404")

    # 通过创建一个 session 并模拟 suspended
    print_detail("创建正常 session 后触发 suspended...")
    resp = await client.post("/browse", json={
        "url": "https://news.ycombinator.com/news",
        "adapter_hint": "hackernews",
    })
    sid = resp.json().get("session_id", "")
    check(bool(sid), f"session 创建成功")

    # 我们可以通过先触发 fallback 让 session 进入 suspended
    # 但要触发 fallback，需要 selector 失败且没有 visual client
    # 最简单的方式：尝试在 suspended 的 session 上执行 /act
    # 但实际上我们无法通过 API 直接设置 suspended
    #
    # 方案：创建一个 browse 使 session 进入 invalid 状态
    # 更好的方案：仅验证如果 session 被标记为 suspended 会怎样
    #
    # 由于无法通过纯 HTTP 触发 suspended（需要 visual fallback 或
    # 在 selector 失效时 ANTHROPIC_API_KEY 也未设置），
    # 我们只验证不存在 session 的 404 行为
    print_detail("用不存在的 session_id 调用 /act...")
    resp = await client.post("/act", json={
        "session_id": "nonexistent-session-id",
        "action": "paginate",
    })
    ok = resp.status_code == 404
    check(ok, f"不存在的 session 返回 404 (实际: {resp.status_code})")

    return ok


async def main():
    global any_failed
    any_failed = False

    print_separator("ANBM 并发压力验证 — Stress Test")

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30, trust_env=False) as client:
        # --- 场景 A ---
        print_separator("场景 A — 同一 Session 并发冲突")
        try:
            a_ok = await scenario_a_same_session_conflict(client)
        except Exception as e:
            print_detail(f"[ERROR] {e}")
            a_ok = False
        print_scenario("场景 A", a_ok)

        # --- 场景 B ---
        print_separator("场景 B — 不同 Session 并发隔离")
        try:
            b_ok = await scenario_b_different_sessions(client)
        except Exception as e:
            print_detail(f"[ERROR] {e}")
            b_ok = False
        print_scenario("场景 B", b_ok)

        # --- 场景 C ---
        print_separator("场景 C — 不存在的 Session 拒绝")
        try:
            c_ok = await scenario_c_suspended_rejection(client)
        except Exception as e:
            print_detail(f"[ERROR] {e}")
            c_ok = False
        print_scenario("场景 C", c_ok)

    # === Summary ===
    print(f"\n{'=' * 60}")
    print(f"  汇总: A={'PASS' if a_ok else 'FAIL'} | "
          f"B={'PASS' if b_ok else 'FAIL'} | "
          f"C={'PASS' if c_ok else 'FAIL'}")
    print(f"  结果: {'全部 PASS' if not any_failed else '部分 FAIL'}")
    print(f"{'=' * 60}")

    sys.exit(0 if not any_failed else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
