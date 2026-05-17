# Vernier (anbm) 工程日志

## 项目起源

ANBM（Agent-Native Browser Middleware）诞生于一个观察：视觉语言模型（如 Claude）在单步浏览器操作上已经足够可靠——它能看懂页面、点击按钮、填写表单。但一旦进入多步任务链（搜索→翻页→打开详情→提取数据→回到列表→打开下一个），问题就出现了：

1. **无状态**：模型不记得自己做过什么，每步都在重新理解上下文，方向错误时无法回溯
2. **Token 浪费**：每步都走视觉模型意味着每步都要传输和处理整页截图，成本高、延迟大
3. **错误累积**：第 1 步的微小偏差在第 5 步被放大，而模型无法区分"已出错"和"正常"

ANBM 的核心理念是：**FSM（有限状态机）定义路径，retry 只是让路径更稳定，不替代路径判断。** 确定性步骤走结构化路径不走视觉模型，视觉模型仅作为兜底层使用。

---

## 开发阶段

### Phase 1（v0.1.0）：从零搭建 FSM 引擎

**时间**：2026-04

建立了完整的三层架构骨架：API 层（FastAPI 路由）→ 引擎层（FSM/Router/Validator/Session）→ 执行层（Playwright 浏览器封装）。定义了核心异常体系（SelectorFailedError、StateChangedError 等）和 BaseAdapter 接口。

第一个适配器 douban_movie 验证了完整链路：导航→状态检测→数据提取→翻页操作。PASS。

**关键决策**：
- retry 前必须检测状态，状态变了立刻上报，不闷头重试
- 非幂等操作零重试，失败直接交给人判断
- handler.py 禁止 catch 选择器异常和写 retry 循环（CI 静态检查）

**测试基线**：26 单元测试

---

### Phase 2（v0.2.0）：登录与 Cookie 持久化

引入 Reddit 适配器，验证了登录状态机（未登录→登录→已登录）和 Cookie 跨 session 保持。非幂等操作（upvote）失败后返回 `requires_human_decision` 而非自动重试的语义得到验证。

---

### Phase 3（v0.3.0）：视觉模型兜底

接入 Anthropic Messages API 做截图分析，当所有确定性路径都走不通时作为最终 fallback。同时接入 MCP stdio server，使 Claude Desktop 可以直接调用 ANBM。

关键设计：未配置 API Key 时不阻断确定性路径；非幂等操作失败不进入视觉 fallback（已产生的副作用无法回滚）。

---

### Phase 4（v0.4.0）：扩展到复杂页面结构

Hacker News（嵌套评论）和 Wikipedia（文章目录+锚点导航）验证纯只读场景的复杂结构提取能力。建立了 HTML 快照测试基础设施和健康检查端点。

**核心决策**：HN 不单独设置"登录"状态。页面类型（列表/详情）和登录状态是正交维度，平面 FSM 无法表达笛卡尔积——将登录态降级为 extract 数据字段。

---

### Phase 5（v0.5.0）：可运营性

修复了生产风险（Chromium 进程泄漏），建立了真实验证脚本、破坏性演练工具、并发压力测试，编写了完整的 Adapter 贡献指南。此阶段之后项目具备了基本的可运营性。

---

### Phase 6（v0.6.0）：设计审查

对已有实现进行了 6 项审查，修复了 4 个真实问题：
- MCP 模块级全局锁（移除，依赖 per-session 锁）
- state_history 无限增长（去重+截断至 50 条）
- 非幂等操作意外异常路径（通用异常捕获）
- 健康检查 URL 隐式依赖（test_url 显式声明）

---

### Phase 7（v0.7.0）：覆盖扩展

新增 Stack Overflow 适配器（第一个 aria 选择器实战），retry 参数环境变量可覆盖，结构化日志（text/json 双格式），Python 客户端 SDK。Wikipedia 的 navigate_link 从无操作修复为真实跳转。

**遗留问题清零**。

---

### Phase 8（v0.8.0）：健康监控与自助修复

建立了主动健康监控系统（四态判定：HEALTHY/DEGRADED/BROKEN/UNREACHABLE）+ 交互式 CLI 修复向导（四阶段：诊断→候选选择→验证→写入）。新增 15 个文件，是单版本变更量最大的阶段。

---

### Phase 9（v0.9.0~v0.9.9）：渐进验证

这是最长的迭代周期，分为 10 个小版本，每个聚焦一个具体假设：

#### v0.9.0：Accessibility Tree check 类型
新增 `aria_present`/`aria_absent` 两种状态检测方式，基于 Playwright `get_by_role()`。selector 失效时通过三路径（CSS 相似度 / ARIA 候选 / LLM 推荐）查找替代选择器。LLM 推荐的选择器只进候选列表，不自动写入。

#### v0.9.1：类型统一
SelectorCandidate union type（`str | SelectorCandidate`）统一为单一类型。Stack Overflow 成为第一个纯 aria check 的适配器。

#### v0.9.2：持久化与热重载
SQLite session 持久化——服务重启后 session 可恢复。AdapterWatcher 监听文件变更自动重载，开发时无需重启服务。Fingerprint 缓存避免同一状态下重复执行 DOM 查询。

#### v0.9.3：arXiv 搜索验证
纯只读适配器，搜索动作用于验证跨 adapter 的动作模式一致性。URL 直构造搜索（不碰搜索框）——这是一个可复用的搜索实现模式。

#### v0.9.4：FSM 状态语义验证
**核心验证**：FSM 状态由页面 DOM 语义决定，不是由 URL 参数决定。
- PyPI：`filter_version` 只改变 URL query 参数，不改变状态
- Lobsters：`filter_by_tag` 改变 URL 路径（`/` → `/t/rust`），但"故事列表"语义不变 → 不改变状态

#### v0.9.5：非幂等操作信号
**核心验证**：非幂等操作执行后 FSM 状态不变，系统不把"状态未变"误判为"操作失败"。
- DEV.to：`like_post` 和 `save_post` 后仍处于 `article_detail`
- Codeberg：`assign_issue` 后仍处于 `issue_detail`
- 引入 `side_effect_hint` 向 Agent 指示哪个数据字段将变化

#### v0.9.6：无限滚动有限状态表达
Mastodon 适配器，2 个状态表达无限滚动场景。`feed_partial`（还有内容）和 `feed_exhausted`（已耗尽）。三阶终止检测：
- P1：容器 fingerprint 比对（内容是否变化）
- P2：article[data-id] 去重统计
- P3：安全超时

`feed_exhausted` 是声明性终止状态——FSM 不会自动转移到该状态，由调用方判断。

#### v0.9.7：Extract 边界定义
**核心验证**：extract 提取的是结构化语义信息，不是 DOM 内容的镜像。
- Unsplash（图片主导）：Photo Grid → masonry 网格 + extractable:false 装饰性图片
- MDN（代码+文本混合）：代码块、交互式示例（iframe 不可穿透）、Text/Media 统一格式

确立了 Extract 稳定性原则：同一状态下多次 extract 结构一致；不做 AI 推理加工；不做 DOM 结构镜像。

#### v0.9.8：多步工作流状态一致性
**核心验证**：session 是可靠的多步执行上下文，中间失败不污染已完成的步骤。
- Exercism 工作流：track_list → open_track → exercise_list → open_exercise → exercise_detail
- 第三步失败时 current_state 停留在第二步成功后的状态
- fingerprint cache 在状态跳转时自动清除

#### v0.9.9：跨 adapter session 隔离
**核心验证**：session 与 adapter 绑定，跨站点任务由调用方管理多个 session_id。
- adapter_mismatch 保护：复用 session 访问不同适配器的 URL 返回明确错误
- Cookie 和 state_history 完全隔离
- 跨站工作流原型：PyPI 获取项目信息 → 新 session 跳转到 GitHub Issues

---

### Phase 10（v0.10.0-beta.1）：Adapter 腐烂修复与验证体系建立

**时间**：2026-05-17

核心目标：修复真实环境验证中发现的选择器腐烂问题，建立系统化的选择器新鲜度追踪。

#### Bridge 验证系统

Cowork 因 VM 沙箱阻断外部网络，自建了一套 Chrome 扩展验证系统：
- `bridge_server.py`：Python stdlib HTTP 中继（localhost:8765）
- `.bridge/extension/`：Chrome MV3 扩展（content.js DOM 扫描 + popup 控制面板）
- 工作流：打开目标网站 → 扩展扫描 DOM → 快照写入 `.bridge/sites/` → 分析 → 写验证任务 → 执行 → 结果写入 `.bridge/results/`

Bridge 有 5 个已知 bug（详见 VERIFICATION_HANDOFF.md），最严重的是 content.js JSON 转义问题。

#### Adapter 腐烂修复

**PyPI**（5 个选择器失效）：
- 状态检测：`[data-controller='search']` → `url_contains /search/` + `also_check .package-snippet`
- 包名：`.package-snippet__name` → `.package-snippet__title`
- 版本号：`.package-snippet__version` 已从列表页移除 → handler 中 version 字段置空
- 翻页：`[aria-label='Next Page']` → `.button-group--pagination a.button-group__button`
- 结果总数：`.search-results__total` 已移除 → JS 从 aria-label 提取 + 回退计数

**Stack Overflow**（7 个选择器失效）：
- 卡片容器：`[role="article"]` → `.s-post-summary`
- 投票数：`[itemprop="upvoteCount"]` → `.s-post-summary--stats-item__emphasized .s-post-summary--stats-item-number`
- 回答数：`[aria-label$="answers"]` → `.s-post-summary--stats-item.has-answers .s-post-summary--stats-item-number`
- 翻页：`[rel="next"]` → JS 查找 `.s-pagination .is-selected` 的下一个 sibling
- 搜索框：`[role="searchbox"]` → `[role="combobox"]`
- 404 检测：`[data-se-page='404']` → `element_absent .s-post-summary`

#### 选择器新鲜度追踪

全部 15 个 manifest.json 新增 `last_verified` 字段：

| 状态 | 数量 | Adapter |
|------|------|---------|
| 已验证（有日期） | 7 | HN、GitHub (05-07), Lobsters (05-17), PyPI、SO (05-17), douban_movie、Reddit-blocked (05-07) |
| 部分验证（null + note） | 2 | arxiv、wikipedia |
| 未验证（null） | 6 | devto、codeberg、mastodon、unsplash、mdn、exercism |

#### 方案缺口更新

| 方案 | 状态 | beta.1 行动 |
|------|------|------------|
| T5.1 LLM selector + 人工确认 | ✅ 已实施 | 端到端 repair 验证（待做） |
| T5.2 double-check | ❌ 缺失 | 暂缓 |
| **T5.3 URL 漂移检测** | ⚠️ 部分 | **beta.1 优先实施** |
| T5.4 soft fallback | ⚠️ 部分 | 暂缓 |
| T5.5 per-action retry | ❌ 缺失 | 推迟 v0.11.0 |
| T5.6 加载确认信号 | ❌ 缺失 | 推迟 v0.11.0 |

#### 测试基线

- 单元测试：126/126 PASS
- Lint：15/15 PASS
- 集成测试：未执行（需网络 + 启动服务）

### 核心系统

| 维度 | 能力 |
|------|------|
| 状态检测 | 6 种 check 类型（element_present/absent、url_contains/matches、aria_present/absent）+ also_check 组合 |
| 执行路径 | 三层：deterministic（正常）→ state_changed（状态跳转）→ visual_fallback（视觉兜底） |
| 重试策略 | 4 类（extract/navigate/act_idempotent/act_non_idempotent），参数环境变量可覆盖 |
| 会话管理 | 内存 / SQLite 双后端，per-session asyncio.Lock 并发控制，state_history 去重截断 |
| 健康监控 | 四态判定，三路径候选查找，日志/Webhook/JSONL 告警输出 |
| CLI | 健康检查 + 状态摘要 + 交互式修复向导 |
| 热重载 | 文件变更自动重载（ANBM_HOT_RELOAD） |
| 日志 | 结构化日志（text/json 双格式），log_event() 统一接口 |
| SDK | Python 同步+异步客户端 |

### 适配器覆盖（15 个）

| 类型 | 适配器 | 数量 |
|------|--------|------|
| 社区/论坛 | Hacker News、Reddit、Lobsters、DEV.to | 4 |
| 开发工具 | GitHub Issues、Codeberg、Stack Overflow、PyPI、MDN Web Docs | 5 |
| 学术 | arXiv、Wikipedia、Exercism | 3 |
| 媒体 | 豆瓣电影、Unsplash | 2 |
| 社交 | Mastodon | 1 |

### 测试覆盖

- **单元测试**：126 个
- **集成测试**：86 个（全部 @pytest.mark.network）
- **对应网站**：15 个适配器各有 4-7 个集成测试
- **lint**：15/15 PASS（适配器静态检查）
- **工具**：破坏性演练脚本、并发压力测试、真实验证脚本

---

## 未解决的问题

### 技术上已识别但未实施的

| 问题 | 影响 | 原因 |
|------|------|------|
| adapter_version 兼容 | session 恢复时不做版本比对，adapter 升级可能导致老 session 状态不一致 | 0.x 阶段，无持久化需求 |
| FakePage DOM 模拟 | 单元测试中不支持 CSS 后代选择器和伪类 | 当前选择器在一级映射下均可覆盖，收益不匹配成本 |
| 跨 session cookie 共享 | 无法在同一 user 下同时操作多个相同站点的 session | 当前是特性而非缺陷——cookie 隔离防止了跨域泄漏 |

### 架构边界

以下能力被明确定义为**非目标**：
- 自动适应网站改版（Adapter 失效时明确报错，不静默失败）
- 替代视觉模型做语义理解（extract 不推理、不总结、不翻译）
- 跨站点任务编排（这是调用方/Agent 的职责）
- 反爬虫绕过（ANBM 不做任何对抗性操作）

### 设计约束

- 适配器状态数上限 6 个——超过时需将正交维度降级为数据字段
- 一个 session 只属于一个 adapter——跨站任务由调用方管理多个 session_id
- 非幂等操作零重试——失败直接交给人判断，不进视觉 fallback
- 选择器优先级：aria > data-testid > CSS class——aria 在网站改版中最稳定
