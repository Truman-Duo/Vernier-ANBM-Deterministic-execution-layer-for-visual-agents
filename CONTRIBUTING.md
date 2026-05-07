# Vernier (anbm) — 贡献指南

Vernier 是一个开源的**状态机执行中间层**，为视觉 Agent 提供多步任务的状态记忆与确定性路径。
**核心原则：FSM 定义路径，retry 只是让路径更稳定，不替代路径判断。**

---

## 📦 环境搭建

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # 编辑 .env 填入 ANTHROPIC_API_KEY（可选，不填则视觉兜底不可用）
```

启动服务：

```bash
python run_direct.py
```

运行测试：

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v --timeout=60
python scripts/lint_adapter.py
```

---

## 🏗 架构分层

层与层之间**严格单向依赖**：`API → 引擎 → 执行 → 浏览器`，禁止反向依赖。

| 层 | 目录 | 职责 |
|----|------|------|
| API 层 | `src/api/` | 只做请求解析和响应格式化，不含业务逻辑 |
| 引擎层 | `src/engine/` | FSM、Router、Retry、Validator、Session |
| 执行层 | `src/executor/` | Playwright 封装，不含任何业务判断 |
| Adapter 层 | `adapters/*/` | 只做单步页面交互，不含流程编排 |

---

## 🚫 绝对禁止（违反导致构建失败）

### handler.py 中禁止出现

```python
except SelecterFailedError    # retry 逻辑在 RetryOrchestrator，handler 不处理
except TimeoutError           # 同上
await self.act(               # handler 不跨方法编排
await self.extract(           # 同上
session.current_state =       # handler 不修改状态
time.sleep(                   # 重试等待由 RetryOrchestrator 管理
asyncio.sleep(                # 同上
for _ in range(               # handler 不写 retry loop
while True                    # 同上
while attempt                 # 同上
```

CI 通过 `scripts/lint_adapter.py` 静态检查以上模式，违反则构建失败。

### RetryOrchestrator 强制约束

- retry 前**必须**调用 `detect_state()`
- `detect_state()` 返回明确不同状态 → 抛 `StateChangedError`（携带 `attempts_before_change`）
- `detect_state()` 返回 `"unknown"` → 视为过渡噪声，**继续** retry，不触发 StateChangedError
- `max_attempts=1`（非幂等操作）→ **不调用** `detect_state()`，直接失败

### 非幂等操作

- `max_attempts` 必须为 `1`，禁止任何 retry
- 失败后返回 `requires_human_decision: true`，不进入 visual_fallback
- 示例：post_comment、submit_form、close_issue
- handler 中成功的非幂等操作应设置 `ActResult.side_effect_hint`，向 Agent 提示哪个字段将变化
- manifest.json 中必须声明 `action_side_effects` 字段

---

## 📐 设计规范

### StateChangedError 语义

```python
# 正确：由 RetryOrchestrator 抛出
raise StateChangedError(
    message=...,
    new_state=current_state,
    attempts_before_change=attempt + 1
)

# 禁止：handler.py 中直接抛出 StateChangedError
```

state_changed **不等于** session suspended：`state_changed` → `session.suspended = False`，FSM 正常流转。

### Fallback 的 state_known 语义

`_visual_fallback` 的 `state_known` 参数决定 `session_suspended` 的值：

| state_known | suspend | 使用场景 |
|-------------|---------|---------|
| `True` | 不 suspend | `detect_state()` 已成功确认状态，仅是选择器失效 |
| `False`（默认） | suspend | 状态本身不可信，Agent 需调 `/browse` 重新同步 |

调用约束：
- `execute_extract()` → 始终传 `state_known=True`
- 幂等 `execute_act()` → 始终传 `state_known=True`
- 非幂等操作不进入 `_visual_fallback`

### Session 并发控制

同一 session 在任意时刻只允许一个活跃执行流。`SessionStore` 内部维护 `asyncio.Lock`。
并发请求返回 **409 Conflict**，不排队，不等待。

### Retry 参数集中管理

所有 retry 参数只能在 `src/engine/retry_config.py` 中定义。业务代码中禁止硬编码 sleep 或重试次数。

| 类型 | max_attempts | base_delay_ms |
|------|-------------|---------------|
| extract | 3 | 1000 |
| navigate | 2 | 2000 |
| act_idempotent | 2 | 1500 |
| act_non_idempotent | 1 | 0 |

### API 响应必含字段

```json
{
  "retry": { "attempts": int, "succeeded": bool },
  "session_suspended": bool,
  "execution_path": "deterministic" | "state_changed" | "visual_fallback"
}
```

不含这三个字段的响应是不完整的响应。

### Fallback 闭环

进入 `_visual_fallback` 前**必须**调用 `session_store.record_fallback()`。fallback 后不自动执行任何操作，只返回截图和视觉模型分析结果给 Agent。

---

## 🔌 Adapter 规范

- 每个 action 必须在 `manifest.json` 的 `action_idempotency` 中声明 `true/false`
- 状态数量上限：6 个/Adapter（防止状态爆炸）
- 选择器优先级：`aria_present/aria_absent > data-* > aria role/text > CSS class`
- `extract()` 和 `act()` 方法里找不到元素，统一抛 `SelectorFailedError`，不 return None
- 每个适配器需包含 `manifest.json`（状态机定义）和 `handler.py`（实际交互逻辑）
- 详细编写指南见 [docs/adapter_authoring_guide.md](docs/adapter_authoring_guide.md)

---

## 🧪 测试要求

### 单元测试必覆盖场景（以 test_retry.py 为例）

- `test_retry_succeeds_on_second_attempt`：第一次失败，第二次成功
- `test_retry_aborts_on_state_change`：失败后 detect_state 返回不同状态
- `test_retry_continues_on_unknown_state`：detect_state 返回 unknown，继续重试
- `test_retry_exhausted_raises`：连续失败至耗尽
- `test_non_idempotent_no_retry`：max_attempts=1，不重试

### 实现顺序

按此顺序实现，每层完成后运行相关测试再继续：

```
1. src/adapter/base.py
2. src/engine/retry_config.py
3. src/engine/validator.py
4. src/engine/session_store.py
5. src/executor/stealth.py
6. src/executor/browser.py
7. src/adapter/loader.py
8. src/engine/router.py
9. src/engine/fsm.py
10. src/api/
11. adapters/*/
12. tests/
13. scripts/lint_adapter.py
```

---

## 📝 Commit 规范

参考根目录 `.gitmessage` 和 `commit-config.json`：

```
[ANBM-XXX] <type>(<scope>): <subject>

type:   feat / fix / docs / refactor / test / chore / perf / style
scope:  core / adapter / api / executor / health / cli / mcp / client / scripts / tests / docs / config
```

详见 `.gitmessage` 模板（需 `git config commit.template .gitmessage` 启用）。

---

## 📄 License

MIT
