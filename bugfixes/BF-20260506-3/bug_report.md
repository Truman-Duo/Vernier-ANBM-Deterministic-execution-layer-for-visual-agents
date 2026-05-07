# BF-20260506-3：适配器状态识别失败导致 /browse 返回 500

**报告日期**：2026-05-06

**修复版本**：v0.9.9

**严重程度**：Major（阻塞部分网站测试）

**状态**：已修复

---

## 现象

请求 Hacker News 返回 500：

```json
POST /browse {"url": "https://news.ycombinator.com"}
-> 500 Internal Server Error
```

错误日志：

```
File "adapters\hackernews\handler.py", line 137, in extract
    raise ValueError(f"extract() 不支持状态: {state}")
ValueError: extract() 不支持状态: unknown
```

---

## 根因（已修正）

### 执行链路

```
FSMEngine.browse()
├── page.goto("https://news.ycombinator.com")
├── detect_state(page, manifest)
│   └── url_matches 模式: /(news|newest|ask|show|jobs|front|newcomments)(\?.*)?$
│   └── https://news.ycombinator.com (无路径) -> 不匹配任何已知状态
│   └── 返回 "unknown"
├── session_store.update_state(session_id, "unknown")   <- 状态已设为 unknown
├── execute_extract(page, session, adapter, manifest)
│   └── adapter.extract(page, "unknown")                <- 传入了 unknown！
│       └── handler.py 无 unknown 分支 -> ValueError
│
└── ValueError 不是 SelectorFailedError/PageTimeoutError
    -> execute_with_retry 不处理 -> execute_extract 不处理
    -> FSMEngine.browse 不处理 -> API 层 500
```

### 核心缺陷

**`FSMEngine.browse()`** 在 `detect_state()` 返回 `"unknown"` 后，未做任何保护判断，直接将 `"unknown"` 状态喂给 `execute_extract()`。handler.py 不知道如何处理 `unknown` 状态，抛 `ValueError`，且该异常不在引擎的异常处理链中（`execute_with_retry` 只处理 `SelectorFailedError`/`PageTimeoutError`），最终冒泡到 API 层变为 500。

### 错误根源位置

`src/anbm/engine/fsm.py:142-145`

```python
current_state, _ = await self.validator.detect_state(page, manifest, fp_cache)
await self.session_store.update_state(session_id, current_state)
# <- 缺少：if current_state == "unknown": 处理分支
result = await self.router.execute_extract(page, session, adapter, manifest)
```

---

## 解决方案

在 `FSMEngine.browse()` 中，`detect_state` 返回 `"unknown"` 时，跳过 `execute_extract`，直接返回错误响应并挂起 session，**不**让 handler 层承担状态未知的降级责任。

### 具体改动

`fsm.py` `browse()` 方法中，在 `detect_state` 和 `execute_extract` 之间插入 guard：

```python
if current_state == "unknown":
    await self.session_store.suspend(session_id)
    return {
        "session_id": session_id,
        "current_state": "unknown",
        "execution_path": "state_unknown",
        "retry": {"attempts": None, "succeeded": False},
        "session_suspended": True,
        "adapter": session.adapter_id,
        "adapter_version": session.adapter_version,
        "error": "state_not_recognized",
        "message": "导航到 {url} 后无法识别页面状态。session 已挂起。",
        "url": url,
    }
```

### 验证标准

1. 用 `FakePage(url="https://news.ycombinator.com")` 模拟无路径 URL，`/browse` 应返回 `execution_path: "state_unknown"`，不是 500（通过）
2. 正常 URL（如 `/news`）原有行为不受影响（回归通过）

---

## 测试结果

| 测试 | 结果 |
|------|------|
| `test_browse_unknown_state_returns_graceful_response` | PASSED |
| `test_browse_normal_url_still_works` | PASSED |
| `test_browse_no_path_url_triggers_unknown` | PASSED |
| 完整单元测试套件 | 129/129 PASSED |

---

## 测试日志

见 [fix_log.md](fix_log.md)
