# ANBM v0.10.0 方案实施状态核查 — 缺口清单

**生成时间**：2026-05-17  
**核查方法**：代码静态分析（grep + 文件审查）  
**参考文件**：TEST_PLAN_v0.10.0_beta1.md 第五部分

---

## T5.1 alpha1_fix1：LLM 推荐 selector → 人工确认 → 写入 adapter

**状态**：✅ 已完整实施

**证据**：
- `src/anbm/health/checker.py`:
  - `_find_candidates()` 实现三路径候选查找 (line 147)
  - `_find_aria_candidates()` CSS 形状匹配 + ARIA 扫描 (line 237)
  - `_find_llm_candidate()` 基于 Accessibility Tree 文本调用 visual_client (line 277)
  - 候选排序：`llm_suggested` 优先，其余按 similarity 降序 (line 188)
  - 上限 5 个候选 (line 155)
- `src/anbm/cli/repair.py`:
  - 候选列表展示，`llm_suggested` 带 ⚠ 警告标记 (line 154)
  - 选择后写入 adapter handler.py
  - 相似度偏低警告 (line 174)

**缺口**：无。但建议做一次人工端到端验证——故意破坏一个 adapter 的 selector，跑 repair 流程全程验证。

---

## T5.2 alpha1_fix2：二次确认机制（double-check）

**状态**：❌ 完全缺失

**证据**：
```bash
grep -rn "double.check\|unstable_state\|re_detect\|second.*detect" src/
```
输出为空——无一命中。

**含义**：`detect_state()` 只执行一次判断。没有"等 100ms → 再检测 → 不一致则 unstable_state → 强制 retry"的逻辑。SPA 局部加载（DOM 分片渲染）可能导致首次检测到的状态不准确。

**优先级建议**：**低**。当前 15 个 adapter 均为传统多页应用（非 SPA），此场景未触发实际 bug。建议在接入第一个 SPA 类型站点时评估。

---

## T5.3 alpha1_fix3：URL + DOM 双校验

**状态**：⚠️ 部分存在，缺失主动 URL 漂移检测

**证据**：
- `StateChangedError` 携带 `trigger_url=page.url` → ✅ 错误上报包含 URL（`src/anbm/engine/router.py:75`）
- manifest.json 中使用 `url_contains`/`url_matches` 作为 check 条件 → ✅ 状态检测阶段支持 URL 匹配（11 个 adapter 使用）
- act 后不主动对比 page.url 变化 → ❌ 缺失独立 URL 漂移检测

**含义**：URL check 只在 `detect_state()` 阶段使用。如果 act 执行后 DOM check 匹配到旧状态但 URL 已经跳转，系统不会捕获。当前实现依赖 DOM check 的准确性。

**优先级建议**：**中**。建议在 beta.1 增加：act 成功后对比 `page.url` 与当前 state 的 url_patterns，不一致时触发 `state_changed`。

---

## T5.4 alpha2_fix1：soft fallback（软降级）

**状态**：⚠️ 引擎层已实现，但未暴露为 API 参数

**证据**：
- `_visual_fallback(state_known=True)` → `session_suspended=False` → ✅ 引擎内部支持软降级
- `execute_extract()` 和幂等 `execute_act()` 传 `state_known=True` → ✅ 自动选择不 suspend
- 非幂等操作不进 fallback → ✅ 避免副作用回滚

**缺口**：Agent 无法**主动选择** soft/hard fallback 模式。当前 `state_known` 由 Router 自动决定，没有暴露为 API 参数或 adapter 配置。

**优先级建议**：**低**。当前自动化策略已覆盖主要场景。如果未来有"Agent 确信状态但仍想触发 fallback"的需求，再暴露 `fallback_mode` 参数。

---

## T5.5 alpha2_fix2：per-action retry policy

**状态**：❌ 完全缺失

**证据**：
```python
# src/anbm/engine/retry_config.py
RETRY_CONFIGS = {
    "extract": RetryConfig(max_attempts=3, ...),
    "navigate": RetryConfig(max_attempts=2, ...),
    "act_idempotent": RetryConfig(max_attempts=2, ...),
    "act_non_idempotent": RetryConfig(max_attempts=1, ...),
}
```

只有 4 种全局类型，不支持 adapter 单独定义。manifest.json 中也没有 `retry_policy` 字段。环境变量覆盖（`ANBM_RETRY_*`）是全局覆盖，非 per-adapter。

**优先级建议**：**推迟到 v0.11.0**。当前 15 adapter 规模下，4 类全局策略够用。当 adapter ≥ 20 且出现明显的 per-site 延迟/稳定性差异时重新评估。

---

## T5.6 alpha2_fix3：加载确认信号（spinner 消失 / network idle）

**状态**：❌ 引擎层缺失

**证据**：
- 引擎层（`src/anbm/engine/`、`src/anbm/executor/`）无 `loading`/`spinner`/`network.idle`/`load.*signal` 相关逻辑
- Mastodon adapter 的三阶终止检测（fingerprint + ID 去重 + timeout）是 adapter-specific 实现，未抽象为通用机制

**含义**：每个需要加载确认的 adapter 需要自行实现等待逻辑，没有统一抽象。

**优先级建议**：**推迟到 v0.11.0**。观察更多无限滚动/异步加载场景（如 Twitter、Tumblr、Instagram adapter）后，积累模式再提取通用方案。当前 Mastodon 的方案可作为参考实现。

---

## 汇总

| 方案 ID | 名称 | 状态 | beta.1 建议 |
|---------|------|------|------------|
| T5.1 | LLM 推荐 selector + 人工确认 | ✅ 已实施 | 端到端验证 |
| T5.2 | 二次确认（double-check） | ❌ 缺失 | 暂缓（无 SPA 场景） |
| T5.3 | URL + DOM 双校验 | ⚠️ 部分 | 建议增加 act 后 URL 漂移检测 |
| T5.4 | soft fallback 暴露为 API | ⚠️ 部分 | 暂缓（当前自动策略足够） |
| T5.5 | per-action retry policy | ❌ 缺失 | 推迟 v0.11.0 |
| T5.6 | 加载确认信号 | ❌ 缺失 | 推迟 v0.11.0 |

**beta.1 优先行动**：
1. T5.3：增加 act 后 URL 漂移检测（中优先级，工作量小）
2. T5.1：做一次端到端 repair 流程验证（确认现有实现可用）
3. T5.2/T5.4/T5.5/T5.6：均推迟或暂缓
