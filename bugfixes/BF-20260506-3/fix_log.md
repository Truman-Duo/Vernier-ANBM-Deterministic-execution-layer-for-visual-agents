# BF-20260506-3 修复日志

## 策略

1. 写自动化测试（mock 层）→ 运行 → 记录失败
2. 修复 `fsm.py` → 运行 → 记录结果
3. 重复直到全部通过

---

## Attempt 1：写测试，验证 bug 可复现 ✅（测试正确检测到 bug）

**测试文件**：`tests/unit/test_bf_20260506_3.py`

### 测试结果（修复前）

| 测试 | 结果 | 说明 |
|------|------|------|
| `test_browse_unknown_state_returns_graceful_response` | ❌ FAILED | 模拟 detect_state→unknown，browse 抛 ValueError: extract() 不支持状态: unknown |
| `test_browse_normal_url_still_works` | ✅ PASSED | 回归测试不变 |
| `test_browse_no_path_url_triggers_unknown` | ❌ FAILED | 真实 detect_state + 无路径 URL，同 500 |

### 根因确认

```
fsm.py:142  detect_state → "unknown"
fsm.py:143  update_state → "unknown"
fsm.py:145  execute_extract("unknown") → handler ValueError → 500
```

### 修复方案

在 `FSMEngine.browse()` 中 `detect_state()` 和 `execute_extract()` 之间插入 guard：

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
        "message": f"导航到 {url} 后无法识别页面状态。session 已挂起。",
        "url": url,
    }
```

---

## Attempt 2：应用修复，验证全部通过 ✅（2026-05-06）

| 测试 | 结果 | 说明 |
|------|------|------|
| `test_browse_unknown_state_returns_graceful_response` | ✅ PASSED | 模拟 unknown → state_unknown 优雅降级 |
| `test_browse_normal_url_still_works` | ✅ PASSED | 回归测试通过 |
| `test_browse_no_path_url_triggers_unknown` | ✅ PASSED | 真实 URL 不匹配 → state_unknown 优雅降级 |

**修改文件**：`src/anbm/engine/fsm.py`（在第 143 行和 145 行之间插入 18 行 guard）

**完整回归测试**：129/129 passed（全部单元测试），零回归

---

## Attempt 3：alpha.1 真实环境验证 ✅（2026-05-06）

在真实 Playwright 浏览器中验证：

| 测试 | 结果 |
|------|------|
| POST /browse `https://news.ycombinator.com` | ✅ 200，`current_state: "unknown"`，`execution_path: "state_unknown"`，不抛 500 |
| verify_hackernews.py session 创建 | ✅ 正常 |
| verify_hackernews.py 状态识别 | ⚠️ 返回 `unknown`（根 URL 不匹配 manifest url_matches 模式，属于 manifest 覆盖范围问题，非引擎缺陷） |

### 分析

- **引擎层修复验证通过**：unknown 状态不再导致 500，返回 200 + 优雅降级
- **遗留问题**：HackerNews 根 URL `https://news.ycombinator.com` 在 manifest 中只有 `/(news|newest|...)` 模式匹配，不包含无路径变体。属于 adapter manifest 覆盖范围问题，非引擎缺陷
- **建议**：在 `manifest.json` 的 `states.news_list.check` 中增加根 URL 匹配，或确认网站是否应自动重定向到 `/news`

---
