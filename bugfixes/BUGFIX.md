# Vernier (anbm) — 缺陷修复日志

本文件为缺陷摘要索引，每个 bug 的完整报告和修复日志在 `BF-YYYYMMDD-N/` 子目录中。

各阶段的真实环境测试结果见 [TEST_LOG.md](../TEST_LOG.md)。

---

## 缺陷列表

| ID | 报告日期 | 严重程度 | 状态 | 摘要 | 详细 |
|----|----------|----------|------|------|------|
| [BF-20260506-1](#bf-20260506-1) | 2026-05-06 | Critical | 已修复 | POST /browse 不传 session_id 返回 404 | [完整报告](bugfixes/BF-20260506-1/bug_report.md) |
| [BF-20260506-2](#bf-20260506-2) | 2026-05-06 | Critical | 已修复 | Windows 下 Playwright 因事件循环类型不匹配无法启动 | [完整报告](bugfixes/BF-20260506-2/bug_report.md) |
| [BF-20260506-3](#bf-20260506-3) | 2026-05-06 | Major | 已修复 | detect_state 返回 unknown 后 browse 未降级导致 500 | [完整报告](bugfixes/BF-20260506-3/bug_report.md) · [修复日志](bugfixes/BF-20260506-3/fix_log.md) |
| [BF-20260506-4](#bf-20260506-4) | 2026-05-06 | Major | 已修复 | 浏览器导航超时未捕获导致 500 | [完整报告](bugfixes/BF-20260506-4/bug_report.md) |
| [BF-20260507-1](#bf-20260507-1) | 2026-05-07 | Medium | 已分析 | GitHub 选择器正确（空仓库问题）；Reddit 被服务器端 headless 封锁 | [完整报告](bugfixes/BF-20260507-1/bug_report.md) |
| [BF-20260507-2](#bf-20260507-2) | 2026-05-07 | Low | 已修复 | 验证脚本及基准工具边界情况崩溃 | [完整报告](bugfixes/BF-20260507-2/bug_report.md) |

---

## BF-20260506-1：POST /browse 不传 session_id 时返回 404

**根因**：`create_session()` 既分配 session 又导航，而后续 `browse()` 再次导航，两次导航使用不同的 browser context key，导致 session 查找失败。

**修复**：分离职责——`create_session()` 只做纯分配（不导航），首次导航统一由 `browse()` 执行。

**涉及文件**：`src/anbm/engine/fsm.py`、`src/anbm/api/routes/browse.py`、6 个集成测试文件

**验证**：单元测试 126/126 通过

→ [完整报告](bugfixes/BF-20260506-1/bug_report.md)

---

## BF-20260506-2：Windows + Python 3.12 下 Playwright 浏览器启动失败

**根因**：Windows 默认 `SelectorEventLoop` 不支持子进程，Playwright 需要 `ProactorEventLoop`。uvicorn 0.46.0 的 `loop="asyncio"` 参数在 `--reload` 模式下未生效。

**修复**：新建 `run_direct.py`，在 `asyncio.run()` 之前设置 `WindowsProactorEventLoopPolicy`，完全接管事件循环生命周期。

**涉及文件**：`run_direct.py`（新增）

**验证**：健康检查 200、/browse 正常返回、验证脚本全部 PASS

→ [完整报告](bugfixes/BF-20260506-2/bug_report.md) · [修复日志](bugfixes/BF-20260506-2/fix_log.md)

---

## BF-20260506-3：detect_state 返回 unknown 后 browse 未降级导致 500

**根因**：`FSMEngine.browse()` 中 `detect_state()` 返回 `"unknown"` 后，仍将该状态传入 `execute_extract()`，handler 不处理 `unknown` 状态抛 `ValueError`，该异常不在引擎的异常处理链中（`execute_with_retry` 只捕获 `SelectorFailedError`/`PageTimeoutError`），最终冒泡到 API 层变为 500。

**修复**：在 `browse()` 的 `detect_state` 与 `execute_extract` 之间插入 guard，`unknown` 时直接返回 `state_unknown` 响应并挂起 session。

**涉及文件**：`src/anbm/engine/fsm.py`

**验证**：3 项专项测试 + 完整单元测试 129/129 通过

→ [完整报告](bugfixes/BF-20260506-3/bug_report.md) · [修复日志](bugfixes/BF-20260506-3/fix_log.md)

---

## BF-20260506-4：浏览器导航超时未捕获导致 500

**根因**：`FSMEngine.browse()` 中 `page.goto()` 调用无 try-except，网络慢时 `domcontentloaded` 也超时，异常冒泡到 API 层变为 500。

**修复**：将 `goto()` 包入 try-except，超时后记录 warning 并继续执行 `detect_state()`，由 BF-20260506-3 的 guard 处理为优雅降级。

**涉及文件**：`src/anbm/engine/fsm.py`

**验证**：强制超时（1ms）返回 `state_unknown` 而非 500

→ [完整报告](bugfixes/BF-20260506-4/bug_report.md)

---

## BF-20260507-1：Adapter 提取选择器与目标网站当前 UI 不匹配

**根因**：分两个不同原因——GitHub 选择器 `[role="listitem"]` 正确，测试仓库无 issue 导致空状态；Reddit 在服务器端屏蔽 headless Chromium（TLS/HTTP 指纹检测），返回纯 CSS 403 页面，非选择器问题。

**修复**：
- GitHub：无需修改选择器，使用有 issue 的仓库即可验证通过（✅ 3/3 deterministic）
- Reddit：当前无可行绕过方案。Reddit 在传输层阻止 headless 浏览器，非选择器能解决。
  - 已尝试：`channel="chrome"`、增强 stealth、session cookie、old.reddit.com → 均无效
- API 层新增 AF-20260507：`/browse` 接口支持 `cookies` 参数，供 verify 脚本传入 session cookie

**涉及文件**：`adapters/github_issues/handler.py`、`adapters/reddit/handler.py`、`src/anbm/api/routes/browse.py`、`src/anbm/engine/fsm.py`、`src/anbm/executor/browser.py`

**验证**：GitHub verify ✅ 3/3 PASS；Reddit 标记为 headless 限制，非 blocking

→ [完整报告](bugfixes/BF-20260507-1/bug_report.md)

---

## BF-20260507-2：验证脚本及基准工具边界情况崩溃

**根因**：recorder.py 在 `total=0` 时除零；httpx 客户端超时 30s 与服务端处理时间不匹配；Reddit 默认 subreddit `r/test` 已不可用。

**修复**：recorder 加除零保护；httpx 超时 30→120s；默认 subreddit 改为 `python`；两个 verify 脚本增加 HTTP 状态码检查。

**涉及文件**：`scripts/benchmark/recorder.py`、`scripts/verify_github.py`、`scripts/verify_reddit.py`

**验证**：无步骤时 recorder 显示 "N/A" 而非崩溃

→ [完整报告](bugfixes/BF-20260507-2/bug_report.md)

---

## 格式规范

每条修复记录的文件结构：

```
bugfixes/
  BUGFIX.md          # 缺陷摘要索引（本文件）
  BF-YYYYMMDD-N/
    bug_report.md    # 现象 · 根因 · 修复 · 验证标准
    fix_log.md       # 逐步修复过程（每次尝试的记录）
```

`bugfixes/BUGFIX.md` 维护所有 bug 的摘要索引，每个条目指向对应的子目录。
