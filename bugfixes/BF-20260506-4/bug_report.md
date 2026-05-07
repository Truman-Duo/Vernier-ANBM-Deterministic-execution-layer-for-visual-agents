# BF-20260506-4：浏览器导航超时未捕获导致 500

**报告日期**：2026-05-06

**修复版本**：v0.10.0-alpha.2

**严重程度**：Major（网络慢时所有站点返回 500）

**状态**：已修复

---

## 现象

GitHub Issues 页面在 `domcontentloaded` 级别导航超时后返回 500：

```
playwright._impl._errors.TimeoutError: Page.goto: Timeout 90000ms exceeded.
  - navigating to "https://github.com/.../issues", waiting until "domcontentloaded"
```

此外，导航超时后 `detect_state()` 在已销毁的执行上下文中查询选择器，产生二次崩溃：

```
Error: Page.query_selector: Execution context was destroyed, most likely because of a navigation
```

---

## 根因

`FSMEngine.browse()` 中的 `page.goto()` 调用没有 try-except 包裹。当网络环境慢（如中国访问 GitHub）导致 `domcontentloaded` 也超时时：

1. `goto()` 抛出 `TimeoutError` → 冒泡到 API 层 → 500
2. 即使能继续执行，后续 `detect_state()` 可能在页面仍在导航时查询 DOM → "execution context destroyed" → 500

### 历史背景

| 阶段 | 修复 | 效果 |
|------|------|------|
| alpha.1 | `networkidle` 30s | GitHub 超时 |
| alpha.2 | 改为 `domcontentloaded` + 锚点等待 | 大部分场景改善 |
| alpha.2 验证 | 默认超时 30s→90s | GitHub 仍超时 |
| **当前** | **goto 超时未捕获 → 500** | **所有慢页面崩溃** |

---

## 解决方案

将 `page.goto()` 包裹在 try-except 中，超时后记录 warning，继续执行 `detect_state()`。即使页面未完全加载，`detect_state()` 可能返回 `"unknown"`，由 BF-20260506-3 的 guard 处理为优雅降级。

### 具体改动

`src/anbm/engine/fsm.py:141-145`：

```python
# 之前：
timeout = int(os.environ.get("ANBM_NAVIGATE_TIMEOUT", "90000"))
await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

# 之后：
timeout = int(os.environ.get("ANBM_NAVIGATE_TIMEOUT", "90000"))
try:
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
except Exception:
    logger.warning("goto(%s) 超时或失败，继续尝试 detect_state", url[:80])
```

### 验证标准

1. 设置 `ANBM_NAVIGATE_TIMEOUT=1`（1ms 强制超时），`/browse` 应返回 `execution_path: "state_unknown"`，不是 500
2. 正常网络下 `/browse` 行为不变（回归）

---

## 涉及文件

- `src/anbm/engine/fsm.py` — goto 调用加 try-except
