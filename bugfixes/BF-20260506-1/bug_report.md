# BF-20260506-1：POST /browse 不传 session_id 时返回 404

**报告日期**：2026-05-06

**修复版本**：v0.10.0-alpha.1

**严重程度**：Critical（所有 verify 脚本均无法运行）

**状态**：已修复

---

## 现象

```json
POST /browse {"url": "https://news.ycombinator.com"}
-> 404 {"error": "session_not_found"}
```

---

## 根因

`FSMEngine.create_session()` 使用临时 key `adapter_id + "_pending"` 创建浏览器上下文并导航到 URL，而后续 `FSMEngine.browse()` 使用真实 `session_id` 查找上下文——这是不同的 key，导致：

1. `create_session()` 创建了第一个浏览器上下文（key=`hackernews_pending`），导航到目标 URL，检测状态，创建 session
2. `browse()` 用真实 `session_id` 调用 `session_store.get()` 时 session 存在（上一步已创建），但随后 `browser.get_page(session_id)` 创建第二个浏览器上下文
3. 两次导航、两个独立浏览器上下文，网络空闲事件和上下文竞争可能导致 session 查找失败

整体流程实际做了两次页面导航（一次在 create_session，一次在 browse），而预期的行为是一次。

---

## 修复文件

| 文件 | 变更 |
|------|------|
| `src/anbm/engine/fsm.py` | `create_session()` 不再导航，仅做 adapter 解析 + session 分配。首次导航统一由 `browse()` 执行。Cookie 恢复逻辑从 `create_session()` 移至 `browse()`。 |
| `src/anbm/api/routes/browse.py` | 使用两步分离的清晰流程：resolve session -> unified browse。`session_id` 为 `None` 时调用 `create_session()`（纯分配），有值时调用 `session_store.get()` 验证存在。 |
| `tests/integration/test_*.py` | 6 个文件：`create_session()` 返回类型从 `dict` 改为 `Session` 对象 |

---

## 修复后的流程

```
POST /browse {url, session_id: null}
  -> create_session(url)        # 纯分配，不导航
    -> resolve adapter
    -> allocate session record
    -> return Session
  -> browse(session_id, url)    # 统一处理导航
    -> restore cookies
    -> goto(url)
    -> detect_state()
    -> execute_extract()

POST /browse {url, session_id: "xxx"}
  -> session_store.get(session_id)   # 验证存在
  -> browse(session_id, url)         # 统一处理导航
```

---

## 验证

- 单元测试 126/126 通过
- lint 检查全部 PASS
- 集成测试中 `create_session()` 调用方已全部适配新返回类型
