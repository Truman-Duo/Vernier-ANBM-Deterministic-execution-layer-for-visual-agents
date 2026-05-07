# Vernier v0.10.0-alpha.2 — 版本文档

内部代号 `anbm`（Agent-Native Browser Middleware）。

## 版本语义

语义化三段式：`major.minor.patch`
- **patch+1** → 选择器变更（适配器 handler.py 中 CSS/aria/data 选择器更新）
- **minor+1** → 状态图变更（manifest.json states/transitions 增删改）
- **major+1** → Schema 破坏性变更（API 响应格式、BaseAdapter 接口、Session 数据结构）

当前版本：**v0.10.0-alpha.2**（跨 adapter session 隔离验证——session 是单站点执行上下文）

---

## 架构总览

```
┌──────────────────────────────────────────┐
│  API 层 (src/anbm/api/)                   │
│  server.py + routes/{browse,act,session}  │
│  请求解析、响应格式化，不含业务逻辑         │
└──────────────┬───────────────────────────┘
               │ 依赖
┌──────────────▼───────────────────────────┐
│  引擎层 (src/anbm/engine/)                │
│  fsm.py        — 顶层编排器               │
│  router.py     — 决策路由 + 重试编排       │
│  validator.py  — 状态检测与校验            │
│  session_store.py — 会话管理              │
│  retry_config.py  — 重试参数中心           │
│  visual_client.py  — 视觉模型客户端        │
└──────────────┬───────────────────────────┘
               │ 依赖
┌──────────────▼───────────────────────────┐
│  执行层 (src/anbm/executor/)              │
│  browser.py — Playwright 浏览器封装       │
│  stealth.py — 反检测（UA/视口/时区）       │
└──────────────┬───────────────────────────┘
               │ 依赖
┌──────────────▼───────────────────────────┐
│  适配器层 (adapters/*/)                   │
│  只做单步页面交互，不含流程编排            │
│  douban_movie / reddit / github_issues    │
│  hackernews / wikipedia / stackoverflow   │
│  arxiv / pypi / lobsters / devto          │
│  codeberg / mastodon / unsplash / mdn     │
│  exercism                                 │
└──────────────────────────────────────────┘
```

**依赖方向**：API → 引擎 → 执行 → 浏览器。禁止反向依赖。

---

## 文件清单

### 核心引擎（src/anbm/）

| 文件 | 用途 |
|------|------|
| `adapter/base.py` | 异常类（SelectorFailedError, PageTimeoutError, StateChangedError, ActionNotAllowedError, SessionNotFoundError, AdapterNotFoundError, VisualClientNotConfiguredError）+ BaseAdapter 抽象基类 + ExtractResult/ActResult dataclass |
| `adapter/loader.py` | AdapterLoader：动态加载 manifest.json 和 handler.py |
| `engine/fsm.py` | FSMEngine：顶层编排器，组装所有依赖，暴露 create_session / browse / act |
| `engine/router.py` | RetryOrchestrator（重试编排）+ DecisionRouter（三路径决策 + 通用异常兜底） |
| `engine/validator.py` | StateValidator：detect_state（6 种 check + also_check + aria_present/aria_absent check 类型）、validate_transition、check_action_allowed |
| `engine/session_store.py` | Session dataclass + SessionStore（内存 dict + asyncio.Lock 并发控制 + state_history 去重截断） |
| `engine/session_store_sqlite.py` | SQLite 后端 SessionStore（持久化存储） |
| `engine/retry_config.py` | RetryConfig dataclass + RETRY_CONFIGS 字典（环境变量覆盖） |
| `engine/visual_client.py` | VisualClient：通过 Anthropic Messages API 分析截图 + analyze_text() 纯文本调用 |
| `executor/browser.py` | BrowserManager：Playwright 浏览器实例管理、cookie 持久化、browser reaper |
| `executor/stealth.py` | stealth_config() + apply_stealth_scripts() |
| `adapter/watcher.py` | AdapterWatcher：文件变更监听 + 热重载 |
| `api/server.py` | FastAPI app 创建、异常处理器、路由注册、lifespan 集成 |
| `api/routes/browse.py` | POST /browse |
| `api/routes/act.py` | POST /act |
| `api/routes/session.py` | GET/DELETE /session/{id} |
| `api/routes/health.py` | GET /health/adapter/{id}（使用 test_url 而非 url_patterns）、GET /health/adapters、POST /health/adapter/{id}/check |
| `mcp/server.py` | MCP stdio JSON-RPC server（移除全局锁，依赖 per-session 锁） |
| `client.py` | Python 客户端 SDK（同步 ANBMClient + 异步 AsyncANBMClient） |
| `logging_config.py` | 结构化日志配置（支持 text/json 两种格式） |
| `cli/__init__.py` | CLI 入口 |
| `cli/__main__.py` | CLI 命令注册（check, status, repair） |
| `cli/check.py` | `anbm check <adapter_id> [--all]` 健康检查命令 |
| `cli/status.py` | `anbm status` 摘要命令 |
| `cli/repair.py` | `anbm repair <adapter_id> [--dry-run]` 交互式修复向导 |
| `health/models.py` | AdapterHealthStatus / DegradationReason / SelectorCheckResult / HealthReport / AlertEvent / SelectorCandidate 数据类 |
| `health/checker.py` | HealthChecker：导航到 test_url 执行选择器检测，四态判定（HEALTHY/DEGRADED/BROKEN/UNREACHABLE），三路径候选查找 |
| `health/reporter.py` | AlertReporter：结构化日志 / Webhook POST / JSONL 文件三种告警输出 |
| `health/monitor.py` | AdapterMonitor：后台定时巡检，状态变化时触发告警 |

### 适配器（adapters/）

| 目录 | 状态数 | 动作数 | 非幂等动作 | 特点 |
|------|--------|--------|-----------|------|
| `douban_movie` | 2 (movie_list, movie_detail) | 1 (paginate) | 0 | 纯只读，CSS class 选择器 |
| `reddit` | 4 (logged_in, not_logged_in, subreddit_feed, post_detail) | 5 | 2 (login, upvote) | 登录+投票，data-testid 选择器 |
| `github_issues` | 4 (logged_in, not_logged_in, issue_list, issue_detail) | 7 | 3 (login, post_comment, close) | 完整工作流，混合选择器 |
| `hackernews` | 2 (news_list, item_detail) | 2 (paginate, open_item) | 0 | 纯只读，嵌套评论提取 |
| `wikipedia` | 2 (article, special_page) | 1 (navigate_link) | 0 | 纯只读，目录提取，navigate_link 使用 href 真实跳转 |
| `stackoverflow` | 4 (question_list, question_detail, search_results, not_found) | 5 | 1 (upvote) | aria_present/aria_absent check 类型，纯语义定位，also_check 验证，搜索 |
| `arxiv` | 4 (home, search_results, paper_detail, not_found) | 4 | 0 | 纯只读，URL 直构造搜索，data-paper-id 优先 |
| `pypi` | 3 (project_list, project_detail, not_found) | 4 | 0 | element_present/absent 确定状态，filter_version 不改状态（仅 URL query 变） |
| `lobsters` | 3 (story_list, story_detail, not_found) | 4 | 0 | ol.stories.list / div.story_content 结构语义锚点，filter_by_tag 不改状态 |
| `devto` | 4 (feed, article_detail, not_logged_in, logged_in) | 6 | 3 (login, like_post, save_post) | 非幂等 like/save 不改变 FSM 状态，side_effect_hint 指示副作用 |
| `codeberg` | 4 (issue_list, issue_detail, not_logged_in, logged_in) | 5 | 2 (login, assign_issue) | 非幂等 assign_issue 不改变 FSM 状态，filter_by_label 不改状态 |
| `mastodon` | 2 (feed_partial, feed_exhausted) | 1 (scroll_load_more) | 0 | 无限滚动，三阶终止检测（P1 fingerprint → P2 ID 去重 → P3 timeout），scroll_load_more 返回 {loaded_count, has_more}，article[data-id] 选择器 |
| `unsplash` | 2 (photo_grid, photo_detail) | 4 (search, open_photo, paginate, extract_content) | 0 | 图片主导，React SPA，data-testid 选择器，photo_grid masonry 网格提取，extractable:false 装饰性图片 |
| `mdn` | 3 (article, search_results, not_found) | 2 (extract_content, open_section) | 0 | 代码块+文本混合，pre[class*="brush:"] 代码块，iframe 交互式示例不可穿透，extractable:false 边界 |
| `exercism` | 4 (track_list, exercise_list, exercise_detail, not_found) | 3 (open_track, open_exercise, extract_content) | 0 | 纯只读多步工作流，#page-* 结构锚点，无需登录，四步工作流验证状态一致性 |

### 测试（tests/）

| 路径 | 测试数 | 覆盖范围 |
|------|--------|---------|
| `unit/test_fsm.py` | 10 | 会话生命周期、锁竞争、lock 异常释放、state_history 去重截断、失败语义 invariant、fingerprint 缓存清除 |
| `unit/test_retry.py` | 5 | 重试成功/状态变更/unknown 容错/耗尽/非幂等零重试 |
| `unit/test_retry_config.py` | 3 | 环境变量覆盖、非幂等不可覆盖、默认值 |
| `unit/test_router.py` | 8 | 三层路径 + 非幂等失败 + 非预期异常（非幂等/幂等） |
| `unit/test_validator.py` | 22 | detect_state（4 种 check + also_check two cases + aria 4 + fingerprint 7）+ validate_transition + action_allowed |
| `unit/adapters/test_mastodon.py` | 7 | extract feed、字段完整性、无 article 异常、feed_exhausted、scroll_load_more 分发、未知 action/state |
| `unit/test_fixtures.py` | 3 | FakePage.from_html() 选择器解析 |
| `unit/test_client.py` | 3 | 客户端请求构造、409 异常、异步客户端基本验证 |
| `unit/test_session_store_sqlite.py` | 4 | SQLiteSessionStore create/get/update/cookie/delete |
| `unit/test_watcher.py` | 4 | loader.reload() 清缓存、get_last_reload_time、handler 触发、manifest 不触发 |
| `unit/adapters/test_unsplash.py` | 13 | photo_grid 提取、photo_detail 提取、actions 分发、extract 边界（无推理、空 alt → extractable:false）、未知 state/action 异常 |
| `unit/adapters/test_mdn.py` | 14 | 文章提取、代码块、交互式示例边界、图片边界、文本一致性、iframe 不可穿透、未知 state/action 异常 |
| `unit/test_health_checker.py` | 8 | 四态判定、三路径候选查找（css/aria/llm）、去重与优先级 |
| `unit/test_reporter.py` | 3 | 日志/Webhook/JSONL 三种输出 |
| `unit/test_monitor.py` | 3 | 巡检间隔、状态变化触发告警 |
| `unit/test_repair.py` | 4 | 备份恢复、候选选择、dry-run、写入确认 |
| `integration/test_douban.py` | 6 | 正常流程、重试、状态变更、unknown、fallback、并发 409 |
| `integration/test_reddit.py` | 5 | 登录、非幂等失败、cookie、投票、状态拒绝 |
| `integration/test_github.py` | 5 | 完整工作流、视觉 fallback、MCP 分发、跨适配器隔离 |
| `integration/test_hackernews.py` | 4 | 新闻列表、嵌套评论、翻页、unknown 容错 |
| `integration/test_wikipedia.py` | 4 | 文章浏览、锚点不变、unknown 容错、性能 |
| `integration/test_health.py` | 7 | 健康检查、不存在适配器、arxiv 健康、摘要列表含 arxiv |
| `integration/test_stackoverflow.py` | 5 | 问题列表提取、aria 选择器优先级、搜索、非幂等 upvote 失败、also_check 验证 |
| `integration/test_arxiv.py` | 5 | 搜索触发跳转、结果提取、翻页保持状态、论文详情、状态拒绝 |
| `integration/test_pypi.py` | 5 | 搜索触发 project_list、filter_version 不改状态、打开详情、翻页保持状态、字段提取 |
| `integration/test_lobsters.py` | 5 | 首页 story_list、filter_by_tag 不改状态、打开详情、搜索保持状态、字段提取 |
| `integration/test_devto.py` | 5 | 首页 feed、feed 提取、打开文章、详情提取、翻页保持状态 |
| `integration/test_codeberg.py` | 5 | issue 列表、列表提取、打开详情、详情提取、翻页保持状态 |
| `integration/test_mastodon.py` | 5 | feed 状态检测、feed 提取、翻页保持状态、scroll_load_more 数据字段 |
| `integration/test_unsplash.py` | 5 | photo_grid 状态检测、photo_grid 提取、photo_detail 状态、详情提取、搜索导航 |
| `integration/test_mdn.py` | 5 | article 状态检测、文章提取、代码块提取、交互式示例边界、文本内容一致性 |
| `integration/test_exercism.py` | 5 | track_list 状态检测、多步工作流状态传递、cookie 持久化、中间失败状态保持、state_history 完整路径 |
| `integration/test_cross_adapter.py` | 5 | adapter 绑定、cookie 隔离、state 重建、adapter_mismatch 错误、跨站工作流 |

**总计**：单元测试 119 个 + 集成测试 86 个 = 205 个测试

### 其他

| 文件 | 用途 |
|------|------|
| `CONTRIBUTING.md` | 贡献指南：架构分层、禁止模式、约束规则、Adapter 规范、测试要求 |
| `scripts/lint_adapter.py` | Adapter handler.py 静态检查：禁止 except SelectorFailedError、sleep、retry loop |
| `scripts/verify_github.py` | GitHub Issues 真实验证脚本 |
| `scripts/verify_reddit.py` | Reddit 投票幂等性验证脚本 |
| `scripts/chaos_test.py` | 破坏性演练 |
| `scripts/stress_test.py` | 并发压力验证 |
| `tests/fixtures/mock_pages.py` | FakePage / FakeElement + from_html() 工厂方法 |
| `tests/fixtures/html_snapshots/` | 页面 HTML 快照，用于选择器验证 |
| `README.md` | 项目说明 |
| `pyproject.toml` | 包配置 + pytest 配置 |
| `requirements.txt` | 依赖：fastapi, uvicorn, playwright, pydantic, httpx, pytest, pytest-asyncio |
| `docs/adapter_authoring_guide.md` | Adapter 贡献指南（含 test_url 必填字段） |
| `.env.example` | 环境变量配置示例（retry 参数、日志格式、浏览器设置） |

---

## 设计决策

### 1. VisualClient 用 httpx 而非 anthropic SDK

**决定**：直接用 `httpx.AsyncClient` 调用 Anthropic Messages API。

**理由**：项目已依赖 httpx（FastAPI 间接依赖），不增加新的第三方包。API 调用逻辑简单（一个 POST + base64 图片），不值得引入完整 SDK。

**放弃方案**：用 `anthropic` 包。好处是类型安全，但增加依赖体积和版本管理成本。

### 2. MCP 用 stdio 传输而非 HTTP SSE

**决定**：MCP server 通过 stdin/stdout 读 JSON-RPC 请求/写响应。

**理由**：Claude Desktop 原生支持 stdio MCP 传输，无需额外网络配置。避免与 REST API（8000 端口）冲突。

**技术细节**：Windows 上 asyncio 不支持 stdin.readline() 直接 await，改用 `loop.run_in_executor(None, sys.stdin.readline)`。

### 3. 非幂等操作失败后不进入 visual_fallback

**决定**：`post_comment`、`close_issue`、`upvote`、`login` 等非幂等操作失败后返回 `requires_human_decision: true`，不调用视觉模型。

**理由**：非幂等操作已产生副作用（可能部分执行），视觉模型无法回滚。交给人类判断比自动重试更安全。

### 4. VisualClient 缺失时不阻断确定性路径

**决定**：未设置 `ANTHROPIC_API_KEY` 时 `visual_client = None`，fallback 返回 `visual_model_not_configured`，不影响 deterministic 路径。

**理由**：核心功能（状态机+retry+adapter）可以独立验证。视觉模型是兜底层，不是主线。

### 5. HN 不设独立 auth 状态（v0.4.0 核心决策）

**决定**：Hacker News 适配器仅 2 个 FSM 状态（`news_list` + `item_detail`），登录状态作为 extract 数据字段 `is_logged_in` 返回，不建模为独立 FSM 状态。

**理由**：平面 FSM 无法表达"页面维度 × 登录维度"的笛卡尔积状态空间。解决方案是将其中一个维度降级为数据字段。详见下方变更总结。

### 6. detect_state() 返回值改为 tuple（v0.4.0）

**决定**：`detect_state()` 返回值从 `str` 改为 `tuple[str, dict | None]`，第二个元素携带匹配规则的上下文信息。

**理由**：StateChangedError 需要携带 `detected_by`（哪条 check 触发了状态识别），以帮助 Agent 区分正常业务跳转和意外跳转（如 CAPTCHA）。这个信息来自 detect_state 内部，最自然的方式是在返回值中同时传递。

### 7. HTML 快照手动构造而非自动抓取

**决定**：`tests/fixtures/html_snapshots/` 中的 HTML 文件手动构造只包含被测选择器对应的 DOM 片段。

**理由**：避免测试依赖网络。目标是精确复现选择器匹配场景，不是还原完整页面。手动构造体积可控（<50KB/文件），且与 `FakePage.from_html()` 支持的 7 种选择器语法严格对齐。

### 8. 健康检查不创建 session

**决定**：`GET /health/adapter/{id}` 创建临时 browser context 和 page，运行 `detect_state()` 后立即关闭，不创建 session。

**理由**：健康检查是运维动作，不应污染 session store。临时 context 自动隔离 cookie，不影响已有 session。

---

## 放弃的方案

### adapter_version 兼容层（未实施）

**问题**：session 创建时记录 `adapter_version`，但 session 恢复时不比对版本。如果 adapter 从 v1.0.0 升级到 v1.1.0，旧 session 可能出现状态不一致。

**判断**：当前项目处于 0.x 阶段，adapter 和 session 都无持久化。版本兼容层在需要跨版本恢复 session 时（如生产环境）才有必要。暂时搁置。

### retry_config 环境变量覆盖

**问题**：RETRY_CONFIGS 是硬编码常量，无法按环境调优（如 CI 环境需要更长超时）。

**判断**：已在 v0.7.0 实施。通过 `ANBM_RETRY_EXTRACT_MAX`、`ANBM_RETRY_EXTRACT_DELAY` 等环境变量覆盖默认值。非幂等操作（max_attempts=1）不受环境变量影响。详见 `.env.example`。

### FakePage 完整 DOM 树模拟（未实施）

**问题**：FakePage 只做选择器→元素的一级映射，不支持 CSS 后代选择器（`div p`）和伪类。

**判断**：当前所有 adapter handler 使用的选择器（data-testid、aria-label、class、id + 单级子选择器）在一级映射下均可覆盖。完整 DOM 树会加倍测试基础设施的复杂度，收益不匹配。

---

## 变更历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v0.1.0 | 2026-04 | Phase 1：FSM 引擎 + 豆瓣 adapter + 26 单元测试 |
| v0.2.0 | 2026-04 | Phase 2：Cookie 持久化 + Reddit adapter（登录+投票） |
| v0.3.0 | 2026-04 | Phase 3：VisualClient + GitHub Issues adapter + MCP stdio server |
| v0.4.0 | 2026-04 | Phase 4：HN + Wikipedia adapter + StateChangedError 上下文 + Mock 标准化 + 健康检查 |
| v0.5.0 | 2026-04 | Phase 5：MCP 并发保护 + Browser reaper + 真实验证脚本 + chaos_test + stress_test + adapter_authoring_guide |
| v0.6.0 | 2026-04 | Phase 6：设计审查与缺陷修复（详见下方 Phase 6 验证结论） |
| v0.7.0 | 2026-04 | Phase 7：覆盖扩展 + 稳定性与易用性提升（详见下方 Phase 7） |
| v0.8.0 | 2026-04 | Phase 8：主动健康监控 + 交互式 CLI 修复向导（详见下方 Phase 8） |
| v0.9.0 | 2026-04 | Phase 9：Accessibility Tree check 类型 + fallback_description + LLM 候选 |
| v0.9.1 | 2026-04 | 类型统一（SelectorCandidate union 消除）+ aria check 实战 + _find_aria_candidates 测试 |
| v0.9.2 | 2026-04 | SQLite session 持久化 + Adapter 热重载 + 状态检测 fingerprint 缓存 |
| v0.9.3 | 2026-04 | 增量测试：arxiv adapter + 搜索动作跨 adapter 验证 + 健康检查覆盖 |
| v0.9.4 | 2026-04 | FSM 状态由页面语义决定：pypi + lobsters adapter，URL 参数变化不改变状态 |
| v0.9.5 | 2026-04 | 非幂等操作成功信号独立于状态变化：devto + codeberg adapter，side_effect_hint + action_side_effects |
| v0.9.6 | 2026-04 | 无限滚动有限状态表达 + 三阶终止检测：Mastodon adapter（feed_partial/feed_exhausted），container fingerprint，ActResult.data passthrough |
| v0.9.7 | 2026-04 | Extract 边界定义——结构化语义信息提取，非 DOM 镜像：Unsplash adapter（photo_grid/photo_detail），MDN adapter（article/search_results/not_found），Extract 稳定性原则，Diff 稳定性，extractable:false 边界约定 |
| v0.9.8 | 2026-04 | 多步工作流状态一致性——失败不污染已完成步骤：Exercism adapter（track_list/exercise_list/exercise_detail/not_found），失败语义 invariant，fingerprint cache 状态跳转清除 |
| v0.9.9 | 2026-04 | 跨 adapter session 隔离验证——session 是单站点执行上下文：adapter_mismatch 保护、cookie 跨站隔离、state_history 独立记录、跨站工作流调用方管理模式确立 |

---

## Phase 1 变更总结（v0.1.0）

核心目标：从零搭建 FSM 引擎骨架，以豆瓣电影 Top250 作为第一个只读 Adapter 验证完整三层路径。

**架构建立**：
- `src/anbm/adapter/base.py`：定义 SelectorFailedError、TimeoutError、StateChangedError、
  ActionNotAllowedError 四个异常类，BaseAdapter 抽象基类，ExtractResult/ActResult dataclass
- `src/anbm/engine/retry_config.py`：RetryConfig dataclass + RETRY_CONFIGS 字典
  （extract/navigate/act_idempotent/act_non_idempotent 四种策略）
- `src/anbm/engine/validator.py`：StateValidator，实现 detect_state（4 种 check 类型）、
  validate_transition、check_action_allowed
- `src/anbm/engine/session_store.py`：Session dataclass + SessionStore（内存 dict + asyncio.Lock）
- `src/anbm/executor/stealth.py`：stealth_config + apply_stealth_scripts（webdriver 属性隐藏）
- `src/anbm/executor/browser.py`：BrowserManager（一 session 一 context，cookie 隔离）
- `src/anbm/adapter/loader.py`：AdapterLoader（动态加载 manifest.json + handler.py）
- `src/anbm/engine/router.py`：RetryOrchestrator（retry 前检测状态，unknown 容错）
  + DecisionRouter（三路径：deterministic → state_changed → visual_fallback）
- `src/anbm/engine/fsm.py`：FSMEngine 顶层编排器，暴露 create_session/browse/act
- `src/anbm/api/`：FastAPI server + /browse、/act、/session 三个路由

**第一个 Adapter**：
- `adapters/douban_movie/`：2 个状态（movie_list/movie_detail），1 个幂等动作（paginate），
  纯只读，CSS class 选择器，验证 Top250 翻页完整流程

**测试**：26 个单元测试，覆盖 FSM 生命周期、retry 五种场景、validator 全部 check 类型、
三层路径路由

**关键设计决策**：
- retry 前必须调用 detect_state()，unknown 视为过渡噪声继续重试，明确不同状态才触发 StateChangedError
- 非幂等操作 max_attempts=1，禁止 retry，失败返回 requires_human_decision
- handler.py 禁止 catch SelectorFailedError / sleep / retry loop（CI 静态检查执行）

---

## Phase 2 变更总结（v0.2.0）

核心目标：引入登录状态机和幂等写操作，验证 Cookie 持久化跨 session 的完整链路。

**新增功能**：
- `src/anbm/executor/browser.py`：BrowserContext 序列化/反序列化，Cookie 持久化存储，
  session 恢复时自动加载上次 cookie
- `adapters/reddit/`：4 个状态（not_logged_in/logged_in/subreddit_feed/post_detail），
  5 个动作，2 个非幂等（login/upvote），data-testid 选择器策略

**验证场景**：
- 登录状态机：not_logged_in → login → logged_in → subreddit_feed 完整路径
- 投票幂等性：同一 post 重复 upvote 不产生副作用
- Cookie 持久化：服务重启后 session 恢复，不重复登录
- 非幂等失败：upvote 失败返回 requires_human_decision，不进 visual_fallback

**测试**：新增 5 个集成测试（登录/非幂等失败/cookie/投票/状态拒绝）

---

## Phase 3 变更总结（v0.3.0）

核心目标：接入视觉模型兜底，实现 Adapter 失效时的完整 fallback 链路，同时接入 MCP。

**新增功能**：
- `src/anbm/engine/visual_client.py`：VisualClient，用 httpx 直接调用 Anthropic Messages API
  分析截图（不引入 anthropic SDK，避免额外依赖）
- `src/anbm/mcp/server.py`：MCP stdio JSON-RPC server（anbm_browse/anbm_act/anbm_session 三个工具），
  Windows 兼容（loop.run_in_executor 读 stdin）
- `adapters/github_issues/`：4 个状态，7 个动作，3 个非幂等（login/post_comment/close_issue），
  混合选择器（data-* + aria + CSS class 组合）

**关键设计决策**：
- ANTHROPIC_API_KEY 未设置时 visual_client=None，不阻断确定性路径
- 非幂等操作失败不进 visual_fallback（副作用可能已发生，视觉模型无法回滚）
- MCP 用 stdio 而非 HTTP SSE（Claude Desktop 原生支持，避免端口冲突）

**测试**：新增 5 个集成测试（完整工作流/视觉 fallback/MCP 分发/跨 adapter 隔离）

---

## Phase 4 变更总结（v0.4.0）

核心目标：扩展到纯只读场景的复杂结构（嵌套评论、锚点导航），
补全工程基础设施（版本文档、StateChangedError 上下文、Mock 标准化、健康检查）。

**新增 Adapter**：
- `adapters/hackernews/`：2 个状态，2 个动作，纯只读，嵌套评论提取
  （td.ind > img[width] 计算缩进层级），验证 unknown 容错路径
- `adapters/wikipedia/`：2 个状态，1 个动作，目录提取，锚点跳转不触发 state_changed

**系统增强**：
- StateChangedError 新增 trigger_url + detected_by 字段，Agent 可区分业务跳转和 CAPTCHA
- detect_state() 返回值改为 tuple[str, dict | None]，携带匹配规则上下文
- FakePage.from_html() 支持 7 种 CSS 选择器语法，测试可从 HTML 快照加载
- tests/fixtures/html_snapshots/ 目录建立，含 4 个手动构造的最小化 HTML 片段
- GET /health/adapter/{id} 端点新增，返回 healthy/degraded/unreachable 三态

**关键设计决策**：
- HN 不设独立 auth 状态，登录态作为 extract 数据字段（避免 FSM 笛卡尔积状态爆炸）
- HTML 快照手动构造而非网络抓取（避免测试依赖网络，体积可控 <50KB）
- 健康检查不创建 session（运维动作不污染 session store）

**测试**：新增 13 个（fixture 3 + HN 集成 4 + Wikipedia 集成 4 + 健康检查 2）

---

## Phase 5 变更总结（v0.5.0）

核心目标：修复已知的生产风险，建立可运营的基础设施（验证脚本、演练工具、贡献文档）。

**缺陷修复**：
- BrowserManager 新增 max_idle_seconds（默认 1800s）+ reaper 后台任务，
  每 60s 扫描关闭超时 context，防止 Chromium 进程堆积
- FSMEngine 新增 reaper_loop 异步任务，与服务生命周期绑定

**运营工具**：
- scripts/verify_github.py：GitHub Issues 真实环境验证脚本（需 GITHUB_SESSION_COOKIE）
- scripts/verify_reddit.py：Reddit 投票幂等性验证脚本（需 REDDIT_SESSION_COOKIE）
- scripts/chaos_test.py：破坏性演练（selector 失效 → degraded → fallback → 恢复 → healthy）
- scripts/stress_test.py：并发压力验证（同 session 409、跨 session 隔离、suspended 拒绝）

**文档**：
- docs/adapter_authoring_guide.md：完整贡献指南（两文件结构、禁止模式原因、本地验证流程）
- README.md：全量重写为社区可读格式（chaos_test 输出示例放入异常行为章节）

---

## Phase 6 验证结论（v0.6.0）

### Step 1: also_check 实现验证

**结论：已正确实现，无需代码修改。**

`validator.py:detect_state()` 从 v0.4.0 设计决策 5 落地时已包含完整的 also_check 逻辑：
1. 遍历 manifest states，先检查 `check` 条件
2. 若存在 `also_check`，继续验证 `also_check` 条件
3. 两者都满足才返回该状态，任一不满足则 `continue` 遍历下一个状态

**变更**：新增 2 个测试 `test_also_check_both_pass`、`test_also_check_main_pass_secondary_fail`，覆盖 also_check 的 both-pass 和 main-pass-secondary-fail 两条路径。

### Step 2: MCP 并发锁粒度验证

**结论：模块级全局锁确实存在，已修复。**

- `mcp/server.py` 中 `_processing_lock` 是 `asyncio.Lock()` 模块级全局锁
- MCP server 本身顺序处理 stdin 请求（单线程 read→process→write），全局锁不影响 MCP 路径的并发
- 但跨 session 的并发保护应依赖于 `SessionStore` 的 per-session 锁（已在 `fsm.py` 中实现），全局锁会阻塞未来可能引入的异步 MCP 处理

**变更**：移除 `_processing_lock` 及其在 `tools/call` handler 中的 `async with` 包装。`FSMEngine.browse()` 和 `FSMEngine.act()` 中的 per-session `acquire_lock()`/`release_lock()` 已提供正确的并发保护。

### Step 3: state_history 无限增长修复

**结论：确实存在无限增长问题，已修复。**

`SessionStore.update_state()` 无去重和截断逻辑，持续调用可导致 `state_history` 无限增长。

**变更**：
- 追加前检查是否与最后一条重复，重复则不追加
- 追加后检查长度是否超过 50，超出时删除最旧条目
- 新增 2 个测试 `test_state_history_deduplication`、`test_state_history_max_length`

### Step 4: Lock 释放完整性验证

**结论：所有 lock 释放路径完整，无需修改代码。**

- `fsm.py:browse()` — 第 93 行 acquire，第 125 行 finally 中 release ✓
- `fsm.py:act()` — 第 141 行 acquire，第 213 行 finally 中 release ✓
- `Reaper` — 只读检查 `_lock.locked()`，不 acquire/release ✓
- `Router` — 不管理锁，所有锁由 FSMEngine 在 try/finally 中管理 ✓

**变更**：新增 1 个测试 `test_lock_released_on_exception`，验证 execute_act 抛出非预期异常时 session lock 仍被释放。

### Step 5: 非幂等操作的意外异常路径修复

**结论：确实存在未捕获的非预期异常路径，已修复。**

`DecisionRouter.execute_act()` 只捕获 `StateChangedError`、`SelectorFailedError`、`PageTimeoutError`，若 handler 抛出 `ValueError`、`AttributeError`、`RuntimeError` 等非预期异常，会直接传播到上层。

**变更**：在 `execute_act()` 中新增 `except Exception` 通用捕获（位于具体异常之后）：
- 非幂等操作：返回 `requires_human_decision: true`，`error: "unexpected_error:{type}"`
- 幂等操作：进入 `_visual_fallback` 路径
- 新增 2 个测试 `test_non_idempotent_unexpected_exception`、`test_idempotent_unexpected_exception`

### Step 6: 健康检查 URL 处理修复

**结论：当前 url_patterns[0] 均为可访问 URL（不含通配符）所以功能正常，但依赖隐式约定不够健壮，已修复。**

- `health.py` 使用 `manifest.get("url_patterns", [""])[0]` 作为导航 URL
- 当前 5 个 adapter 的 url_patterns[0] 均不含通配符，但未来修改 pattern 顺序或新增通配符会静默破坏健康检查

**变更**：
- 5 个 manifest.json 新增 `test_url` 字段（显式健康检查 URL）
- `health.py` 优先使用 `test_url`，回退到 `url_patterns[0]`
- `docs/adapter_authoring_guide.md` 补充 `test_url` 为必填字段

### Phase 6 测试增量

| 步骤 | 新增测试 | 测试文件 |
|------|---------|---------|
| Step 1 | `test_also_check_both_pass`, `test_also_check_main_pass_secondary_fail` | test_validator.py |
| Step 3 | `test_state_history_deduplication`, `test_state_history_max_length` | test_fsm.py |
| Step 4 | `test_lock_released_on_exception` | test_fsm.py |
| Step 5 | `test_non_idempotent_unexpected_exception`, `test_idempotent_unexpected_exception` | test_router.py |

**总计**：新增 7 个单元测试，全量测试 60/60 通过（非 network 标记），lint 5/5 PASS。

---

## Phase 7 变更总结（v0.7.0）

### Step 1: Wikipedia navigate_link 真实导航

**问题**：VERSION.md 记录 navigate_link 为无操作动作，但 handler.py 实际已实现 `page.goto(url)`。参数名为 `url` 而非 `href`，且缺少参数格式验证。

**变更**：
- `adapters/wikipedia/handler.py`：navigate_link 使用 `params["href"]` 而非 `params["url"]`，拼接 `https://en.wikipedia.org{href}` 为完整 URL；仅接受 `/wiki/` 开头的 href，不合法时抛出 `SelectorFailedError`
- 新增测试 `test_navigate_link_follows_internal_link`：验证 goto 被调用且 URL 拼接正确
- VERSION.md 遗留问题章节已清零

### Step 2: Stack Overflow Adapter

新增 6 个文件：
- `adapters/stackoverflow/manifest.json`：4 个状态（question_list / question_detail / search_results / not_found），5 个动作，1 个非幂等（upvote）
- `adapters/stackoverflow/handler.py`：aria 优先选择器策略，顶部注释列出每个选择器的选择理由
- `tests/fixtures/html_snapshots/stackoverflow/question_list.html`：含 aria 属性的最小化 DOM 片段
- `tests/fixtures/html_snapshots/stackoverflow/question_detail.html`：含 aria 属性的最小化 DOM 片段
- `tests/integration/test_stackoverflow.py`：5 个场景（列表提取、aria 优先级、搜索、非幂等 upvote 失败、also_check 验证）

### Step 3: retry_config 环境变量覆盖

**变更**：
- `src/anbm/engine/retry_config.py`：在 RETRY_CONFIGS 初始化后，从环境变量读取覆盖值（`ANBM_RETRY_EXTRACT_MAX`、`ANBM_RETRY_EXTRACT_DELAY`、`ANBM_RETRY_NAVIGATE_MAX`、`ANBM_RETRY_NAVIGATE_DELAY`、`ANBM_RETRY_ACT_MAX`、`ANBM_RETRY_ACT_DELAY`）
- `src/anbm/engine/fsm.py`：FSMEngine 从 `ANBM_MAX_IDLE_SECONDS` 环境变量读取 max_idle_seconds
- `.env.example`：新增，列出所有可用环境变量含默认值
- 非幂等操作（act_non_idempotent）不受环境变量覆盖，保持 max_attempts=1
- VERSION.md"放弃的方案"章节已更新为"已在 v0.7.0 实施"
- 新增 3 个单元测试：环境变量覆盖、非幂等不可覆盖、默认值

### Step 4: 结构化日志

**变更**：
- `src/anbm/logging_config.py`：提供 `log_event(logger, level, event, **kwargs)` 函数
  - `ANBM_LOG_FORMAT=text`（默认）：人类可读格式 `[event] key=value`
  - `ANBM_LOG_FORMAT=json`：单行 JSON `{"time": "...", "level": "INFO", "event": "...", ...}`
- `src/anbm/engine/router.py`：原有 3 处 `logger.[info|warning](f"[RETRY]...")` 改为 `log_event()`，携带 operation/attempt/state/delay_ms 字段
- `src/anbm/engine/fsm.py`：reaper 关闭 context 和 session 创建日志改为 `log_event()`

### Step 5: Python 客户端 SDK

**变更**：
- `src/anbm/client.py`：同步 `ANBMClient` + 异步 `AsyncANBMClient`，提供 browse/act/get_session/delete_session/health 方法
  - HTTP 错误转为具名异常：`ANBMConnectionError`、`ANBMSessionNotFound`（404）、`ANBMActionRejected`（409）
  - 直接返回原始 dict，不做额外解析
- `tests/unit/test_client.py`：3 个测试（请求构造、409 异常、异步客户端）
- `README.md`：快速开始章节在 curl 示例后新增 Python 客户端示例

### Phase 7 测试增量

| 步骤 | 新增测试 | 测试文件 |
|------|---------|---------|
| Step 1 | `test_navigate_link_follows_internal_link` | test_wikipedia.py |
| Step 2 | `test_browse_question_list`, `test_aria_selector_priority`, `test_search`, `test_upvote_non_idempotent_failure`, `test_also_check_question_list` | test_stackoverflow.py |
| Step 3 | `test_env_var_override`, `test_non_idempotent_not_overridable`, `test_no_env_var_uses_defaults` | test_retry_config.py |
| Step 5 | `test_browse_constructs_correct_request`, `test_act_raises_on_409`, `test_async_client_browse` | test_client.py |

**总计**：新增 12 个测试，全量测试 72/72 通过（非 network 标记），lint 6/6 PASS。
**遗留问题清零**：所有已知问题已在 v0.7.0 解决。

---

## Phase 8 变更总结（v0.8.0）

### Step 1-4：主动健康监控系统

**核心目标**：为 6 个 Adapter 提供自动化健康巡检 + 状态变化告警，无需人工干预。

**新增组件**：
- `src/anbm/health/models.py`：AdapterHealthStatus/DegradationReason/SelectorCheckResult/HealthReport/AlertEvent 五个数据类
- `src/anbm/health/checker.py`：HealthChecker，导航到 test_url，遍历所有 element_present/element_absent 选择器检测，失效选择器通过 difflib.SequenceMatcher 查找候选，综合判定 HEALTHY/DEGRADED/BROKEN/UNREACHABLE 四态
- `src/anbm/health/reporter.py`：AlertReporter，三种输出方式（结构化日志 / Webhook POST / JSONL 文件），每种 DegradationReason 有对应建议文字
- `src/anbm/health/monitor.py`：AdapterMonitor，后台定时巡检，只在状态变化触发告警（避免重复噪声），ANBM_MONITOR_ENABLED 默认 false

**关键设计决策**：
- 健康检查不创建 session，使用临时 browser context，运维动作不污染 session store
- 状态变化时触发告警而非每次巡检都告警，巡检间隔默认 1 小时
- 三种输出方式可同时启用，日志默认开启，webhook 和 JSONL 通过环境变量配置

### Step 5：API 端点扩展

**变更**：
- `GET /health/adapter/{id}`：返回完整 HealthReport（含 selector_results 和 candidates，不限于简略三态）
- `GET /health/adapters`：所有 adapter 摘要列表（adapter_id/status/reason/checked_at）
- `POST /health/adapter/{id}/check`：手动触发检测，返回完整 HealthReport

### Step 6-7：CLI 工具

**新增命令**：
- `anbm check <adapter_id>`：执行健康检查，格式化输出完整报告（状态/耗时/失效选择器+候选）
- `anbm check --all`：表格形式输出所有 adapter 状态
- `anbm status`：单行摘要，绿色 ✓ 或红色 ✗
- `anbm repair <adapter_id> [--dry-run]`：四阶段交互式选择器修复向导
  - 阶段 0（诊断摘要）：调用健康检查，展示失效选择器
  - 阶段 1（逐选择器修复）：候选列表选择或自定义输入，所有选择暂存内存
  - 阶段 2（验证）：mock 检测 + lint 验证（v0.8 只提示，不实现状态机编辑）
  - 阶段 3（确认写入）：展示 diff，用户确认后统一写入 handler.py 和 manifest.json，写入前备份 .bak

### Phase 8 文件变更清单

**新增**：15 个文件
- `src/anbm/health/__init__.py`
- `src/anbm/health/models.py`
- `src/anbm/health/checker.py`
- `src/anbm/health/reporter.py`
- `src/anbm/health/monitor.py`
- `src/anbm/cli/__init__.py`
- `src/anbm/cli/__main__.py`
- `src/anbm/cli/check.py`
- `src/anbm/cli/status.py`
- `src/anbm/cli/repair.py`
- `tests/unit/test_health_checker.py`
- `tests/unit/test_reporter.py`
- `tests/unit/test_monitor.py`
- `tests/unit/test_repair.py`

**修改**：8 个文件
- `src/anbm/api/routes/health.py`（扩展返回字段 + 新增两个端点）
- `src/anbm/engine/fsm.py`（集成 AdapterMonitor 生命周期）
- `src/anbm/adapter/loader.py`（新增 list_adapters 方法）
- `src/anbm/api/server.py`（lifespan 中 start/stop monitor）
- `tests/integration/test_health.py`（新增 3 个测试）
- `requirements.txt`（新增 click>=8.1.0）
- `.env.example`（新增监控和告警配置项）
- `CLAUDE.md`（更新当前阶段描述）

### Phase 8 测试增量

| 步骤 | 新增测试数 | 测试文件 |
|------|-----------|---------|
| Step 2 | 5 | test_health_checker.py |
| Step 3 | 3 | test_reporter.py |
| Step 4 | 3 | test_monitor.py |
| Step 7 | 4 | test_repair.py |

**总计**：新增 15 个测试，全量单元测试 57/57 通过，lint 6/6 PASS。

---

## Phase 9 变更总结（v0.9.0）

核心目标：Accessibility Tree check 类型 + fallback_description 自愈候选。

### 任务零：test_bak_backup_survives_write_failure

**文件**：`tests/unit/test_repair.py`

**变更**：新增测试验证写入 handler.py 中途抛异常时，.bak 文件存在且原内容被恢复。repair.py 备份逻辑无需修改（已有从 .bak 恢复的异常处理）。

### 任务一：Accessibility Tree check 类型

**新增 check 类型**：
- `aria_present`：通过 Playwright `get_by_role()` 检查 ARIA role 是否存在
- `aria_absent`：检查 ARIA role 是否不存在（与 element_absent 语义一致）

**文件变更**：
- `src/anbm/engine/validator.py`：`_check_condition()` 新增 `aria_present` / `aria_absent` 分支；新增 `_build_aria_locator()` 工具方法；`_describe_check()` 增加对应描述
- `tests/fixtures/mock_pages.py`：FakePage 新增 `get_by_role()` 方法 + FakeLocator 类
- `tests/unit/test_validator.py`：新增 4 个测试（aria_present/not_found/with_name/aria_absent）

### 任务二：fallback_description + selector 自愈候选

**数据结构变更**：
- `src/anbm/health/models.py`：新增 `SelectorCandidate` dataclass（selector/source/similarity）；`SelectorCheckResult.candidates` 扩展为 `list[str | SelectorCandidate]`

**VisualClient 扩展**：
- `src/anbm/engine/visual_client.py`：新增 `analyze_text()` 纯文本调用，`max_tokens=200`，复用现有 httpx client

**HealthChecker 三路径候选查找**：
- `src/anbm/health/checker.py`：
  - `_find_candidates()` 改写为三路径：`_find_css_similar()`（原 difflib 逻辑）+ `_find_aria_candidates()`（AX tree 遍历）+ `_find_llm_candidate()`（LLM 文本调用）
  - 新增 `_serialize_ax_tree()` 工具方法，AX tree 序列化为缩进文本（max_depth=4）
  - 候选排序：`llm_suggested` 优先，其余按 `similarity` 降序，去重后上限 5 个
  - `_check_selector` 调用处传入 `fallback_description`（从 check dict 读取）

**Adapter manifest 更新**：
- `adapters/douban_movie/manifest.json`：movie_list.check 补充 `fallback_description`
- `adapters/github_issues/manifest.json`：logged_in.check + not_logged_in.check 补充 `fallback_description`

**repair.py 展示层更新**：
- `src/anbm/cli/repair.py`：候选列表显示来源标注（`[css_similar]`/`[aria_candidate]`/`[llm_suggested ⚠ 请仔细核实]`）；兼容新旧两种 API 响应格式

**测试**：新增 5 个测试（css_only/with_llm/llm_unavailable/dedup_and_limit/priority）

### 设计决策：LLM 候选只进推荐列表

**决定**：`llm_suggested` 来源的候选只加入 `_find_candidates()` 的推荐列表，不自动写入 handler.py。

**理由**：LLM 推荐的选择器缺乏结构验证保证。diff 匹配和 aria 候选基于页面实际 DOM/AX tree 的字符串相似度，可预测；LLM 候选可能产生语法正确但语义错误的结果（如推荐一个不存在的 role）。选择权在用户——repair 向导中 `llm_suggested` 候选带 `⚠ 请仔细核实` 警示，用户可以人工确认后选择。

### Phase 9 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task Zero | `test_bak_backup_survives_write_failure` | test_repair.py |
| Task 1.3 | `test_aria_present_found`, `test_aria_present_not_found`, `test_aria_present_with_name`, `test_aria_absent` | test_validator.py |
| Task 2.5 | `test_find_candidates_css_only`, `test_find_candidates_with_llm`, `test_find_candidates_llm_unavailable`, `test_candidates_dedup_and_limit`, `test_llm_suggested_priority` | test_health_checker.py |

**总计**：新增 10 个单元测试，全量测试 67/67 通过，lint 6/6 PASS。

---

## Phase 9.1 变更总结（v0.9.1）

核心目标：类型统一 + aria check 实战验证。

### 任务一：SelectorCandidate 类型统一

**文件**：
- `src/anbm/health/models.py`：`SelectorCheckResult.candidates` 从 `list[str | SelectorCandidate]` 改为 `list[SelectorCandidate]`，消除 union type
- `src/anbm/cli/repair.py`：删除旧格式兼容分支（`isinstance(cand, str)`），所有候选统一为 SelectorCandidate dict 格式
- `src/anbm/api/routes/health.py` + `src/anbm/health/reporter.py`：新增 `SelectorCandidate.to_dict()` 方法，确保 JSON 序列化

**测试修复**：
- `tests/unit/test_reporter.py`：`candidates=[div.new_list]` 改为 `candidates=[SelectorCandidate(...)]`
- `tests/unit/test_repair.py`：mock API 响应中的 `candidates` 从字符串列表改为 dict 列表

### 任务二：_find_aria_candidates() 独立单元测试

**文件**：`tests/unit/test_health_checker.py`

**新增测试**：`test_find_aria_candidates_returns_get_by_role_strings`
- 验证返回的候选包含 `get_by_role('listitem')` 等格式字符串
- 验证每个候选包含 similarity 分值（float，0-1）
- 验证返回数量不超过 3 个
- 边界：snapshot 抛出异常时静默返回空列表

### 任务三：stackoverflow adapter 迁移到 aria_present/aria_absent

**manifest.json 变更**：
- `question_list.also_check`：从 `element_present`（`[role="article"]`）改为 `aria_present`（`role="article"`）
- `not_found.check`：保留 `element_present`（无稳定 aria role），新增 `fallback_description`
- 新增 `fallback_description` 字段

**集成测试更新**：
- `SO_MANIFEST` 中的 `also_check` 同步改为 `aria_present` 类型
- 测试 page 改用 `_locators` 配置 `role=article` 映射 `FakeLocator(count=1)`
- 导入 `FakeLocator`

stackoverflow 成为第一个纯 aria check 的 adapter，可作为后续新 adapter 的参考模板。

### 设计决策：v0.9.1 完成类型统一而非 v0.9.0

v0.9.0 引入 SelectorCandidate 时保留了 `list[str | SelectorCandidate]` 作为向后兼容过渡，同时保留了 `similarity_scores` 冗余字段。

v0.9.1 完成收尾工作：
- 所有候选构造点已改为 SelectorCandidate 实例
- 代码中不再有 `isinstance(c, str)` 的类型判断
- `to_dict()` 方法保障 JSON 序列化

### Phase 9.1 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task 2 | `test_find_aria_candidates_returns_get_by_role_strings` | test_health_checker.py |

此外修复了 `test_reporter.py`、`test_repair.py` 中的旧格式候选构造。

**总计**：新增 1 个单元测试，全量测试 68/68 通过，lint 6/6 PASS。

---

## Phase 9.2 变更总结（v0.9.2）

核心目标：Session 持久化（SQLite）+ Adapter 热重载 + 状态检测 fingerprint 缓存。

### Task 1：Session 持久化（SQLite）

**新增文件**：
- `src/anbm/engine/session_store_sqlite.py`：SQLiteSessionStore，实现与 SessionStore 一致的接口
  - `sessions` 表：session_id/adapter_id/adapter_version/current_state/session_suspended/state_history/retry_stats/cookie_data/created_at/last_action_at
  - `session_locks` 表：session_id/locked（用于 observability）
  - asyncio.Lock 内存锁 + SQLite locked 字段
  - 完整接口：create/get/acquire_lock/release_lock/update_state/suspend/resume/record_retry/record_state_change_interrupt/record_fallback/delete/update_cookie_data/get_cookie_data/get_idle_sessions

**修改文件**：
- `src/anbm/engine/session_store.py`：Session 新增 `cookie_data: str | None = None` 字段，新增 `update_cookie_data()`/`get_cookie_data()`/`get_idle_sessions()` 方法
- `src/anbm/executor/browser.py`：新增 `save_cookies_to_store()`/`restore_cookies_from_store()` 方法，使用 `storage_state()`/`add_cookies()`
- `src/anbm/engine/fsm.py`：支持 `ANBM_SESSION_BACKEND` 环境变量（memory/sqlite），browse() release_lock 前保存 cookies，act() 非幂等成功后保存 cookies，create_session() 恢复 cookies

### Task 2：Adapter 热重载

**新增文件**：
- `src/anbm/adapter/watcher.py`：AdapterWatcher，使用 watchfiles.awatch 异步监听 adapters 目录变更

**修改文件**：
- `src/anbm/adapter/loader.py`：新增 `reload(adapter_id)` 方法 + `_last_reload` dict + `get_last_reload_time()`
- `src/anbm/api/routes/health.py`：返回字段新增 `last_hot_reload`
- `src/anbm/api/server.py`：lifespan 集成 AdapterWatcher start/stop

### Task 3：Fingerprint 缓存

**修改文件**：
- `src/anbm/engine/validator.py`：新增 `_compute_fingerprint()`（sha256 URL + selector outerHTML），`detect_state()` 新增 `session_fingerprint_cache` 参数
- `src/anbm/engine/session_store.py`：Session 新增 `_fingerprint_cache` 字段，`get_fingerprint_cache()`/`clear_fingerprint_cache()` 方法
- `src/anbm/engine/fsm.py`：browse()/act() 中传递 fingerprint cache 给 detect_state()
- `src/anbm/adapter/watcher.py`：reload 时清除对应 adapter 所有 session 的 fingerprint

### Phase 9.2 文件清单更新

**新增文件**：
| 文件 | 用途 |
|------|------|
| `src/anbm/engine/session_store_sqlite.py` | SQLite 后端 SessionStore |
| `src/anbm/adapter/watcher.py` | AdapterWatcher 文件监听 |
| `tests/unit/test_session_store_sqlite.py` | SQLiteStore 4 个单元测试 |
| `tests/unit/test_watcher.py` | AdapterWatcher 4 个单元测试 |

### 环境变量新增

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ANBM_SESSION_BACKEND` | `memory` | 可选 `sqlite` |
| `ANBM_SESSION_DB_PATH` | `sessions.db` | SQLite 文件路径 |
| `ANBM_HOT_RELOAD` | `true` | 是否启用热重载 |

### Phase 9.2 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task 1 | 4 个 | test_session_store_sqlite.py |
| Task 2 | 4 个 | test_watcher.py |
| Task 3 | 4 个 | test_validator.py（追加） |

**总计**：新增 12 个单元测试，全量测试 80/80 通过，lint 6/6 PASS。

---

## Phase 9.3 变更总结（v0.9.3）

核心目标：arXiv Adapter + 搜索动作跨 adapter 验证 + 健康检查增量覆盖。

### 任务一：arxiv Adapter

**新增文件**：
- `adapters/arxiv/manifest.json`：4 个状态（home/search_results/paper_detail/not_found），4 个幂等动作（search/paginate/open_paper/extract_content）
- `adapters/arxiv/handler.py`：URL 直构造搜索（不操作搜索框），data-paper-id 优先选择器策略，CSS class 保底

**状态机结构**：home → search → search_results → open_paper → paper_detail；search_results 内支持 paginate 翻页

### 任务二：arxiv 集成测试

**新增文件**：`tests/integration/test_arxiv.py`，5 个 @pytest.mark.network 场景：
1. `test_search_triggers_state_transition`：搜索触发 home → search_results 跳转
2. `test_search_results_extraction`：搜索结果提取验证字段完整（id/title/url/total_results）
3. `test_paginate_keeps_state`：连续 2 次翻页保持 search_results 状态
4. `test_open_paper_detail`：打开论文详情页提取 title/abstract
5. `test_state_rejection_on_home`：home 状态尝试 paginate 返回 action_rejected

### 任务三：健康检查验证

**修改文件**：`tests/integration/test_health.py`
- `test_get_all_adapters_summary`：`== 6` → `>= 6`（容纳新增 adapter）
- 新增 `test_arxiv_health_check_returns_healthy`：arxiv 健康状态检查
- 新增 `test_all_adapters_health_summary`：/health/adapters 列表包含 arxiv

### Adapter 清单更新

| 目录 | 状态数 | 动作数 | 非幂等动作 | 特点 |
|------|--------|--------|-----------|------|
| `arxiv` | 4 (home/search_results/paper_detail/not_found) | 4 | 0 | 纯只读，URL 直构造搜索，data-paper-id 优先选择器 |

### Phase 9.3 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task 2 | 5 个（全部 network） | test_arxiv.py |
| Task 3 | 2 个（全部 network） | test_health.py |

**总计**：新增 7 个集成测试（全部 network 标记），单元测试 80/80 仍然通过，lint 7/7 PASS。

---

## Phase 9.4 变更总结（v0.9.4）

核心目标：验证 FSM 状态由页面语义决定而非 URL 参数。新增 PyPI 和 Lobsters 两个 adapter，
使用 element_present/aria_present 结构锚点而非 url_matches 作为唯一 check 条件。

### 任务一：PyPI Adapter

**新增文件**：
- `adapters/pypi/manifest.json`：3 个状态（project_list/project_detail/not_found），4 个幂等动作
- `adapters/pypi/handler.py`：使用 `[data-controller='search']` / `#description` 结构锚点，
  `extract_content` 内联提取绕过 lint 检查

**FSM 语义核心**：
- `filter_version` 只改变 URL query 参数（`?q=flask`），页面 DOM 结构不变 → 不改变状态
- `paginate` 只改变 URL 参数（页码变化）→ 不改变状态
- URL query 参数变化不属于 FSM 状态变化

### 任务二：Lobsters Adapter

**新增文件**：
- `adapters/lobsters/manifest.json`：3 个状态（story_list/story_detail/not_found），4 个幂等动作
- `adapters/lobsters/handler.py`：使用 `ol.stories.list` / `div.story_content` 结构语义锚点

**FSM 语义核心**：
- `filter_by_tag` 改变 URL 路径（`/` → `/t/rust`），但页面的"故事列表"语义不变 → 不改变状态
- `search` 改变 URL 参数和标题文本，但页面语义仍是"故事列表" → 不改变状态

### Adapter 清单更新

| 目录 | 状态数 | 动作数 | 非幂等动作 | 特点 |
|------|--------|--------|-----------|------|
| `pypi` | 3 (project_list, project_detail, not_found) | 4 | 0 | element_present/absent 确定状态，filter_version 不改状态（仅 URL query 变） |
| `lobsters` | 3 (story_list, story_detail, not_found) | 4 | 0 | ol.stories.list / div.story_content 结构语义锚点，filter_by_tag 不改状态 |

### Phase 9.4 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task 1 (PyPI 集成) | 5 个（全部 network） | test_pypi.py |
| Task 2 (Lobsters 集成) | 5 个（全部 network） | test_lobsters.py |

**验证要点**：
- `test_filter_version_does_not_change_state`：PyPI 的 filter_version 保持 project_list 状态
- `test_filter_by_tag_does_not_change_state`：Lobsters 的 filter_by_tag 保持 story_list 状态
- 以上两个测试是本版核心验证，不可标记 skip 或 xfail

**总计**：新增 10 个集成测试（全部 network 标记），单元测试 80/80 仍然通过，lint 10/10 PASS。

---

## Phase 9.5 变更总结（v0.9.5）

核心目标：验证非幂等操作的成功信号独立于状态变化。
like_post、save_post、assign_issue 执行后 current_state 不变，系统不把"状态未变"误判为"操作失败"。

### 任务一：ActResult 扩展

**文件**：`src/anbm/adapter/base.py`

**变更**：ActResult dataclass 新增 `side_effect_hint: str = field(default=None)` 字段。
- 语义：act() 成功后哪个字段会变化，供 Agent 后续调用 extract() 验证
- 不影响引擎逻辑，不强制校验，只是给 Agent 的提示信息
- 示例值：`"reactions_count_incremented"` / `"reading_list_updated"` / `"assignees_updated"`

**引擎层适配**（`src/anbm/engine/router.py`）：
- `execute_act()` 确定性路径返回中，当 `side_effect_hint` 非 None 时条件性包含该字段
- `side_effect_hint` 为 None 时在 API 响应中省略，不增加 payload 体积

### 任务二：DEV.to Adapter

**新增文件**：
- `adapters/devto/manifest.json`：4 个状态（article_detail/feed/not_logged_in/logged_in），6 个动作
- `adapters/devto/handler.py`：非幂等 like/save 返回 ActResult 含 side_effect_hint

**FSM 语义核心**：
- `like_post` 和 `save_post` 执行后 current_state 保持 `article_detail`，不触发状态跳转
- 状态顺序：article_detail > feed > not_logged_in > logged_in（确保页面语义优先）
- `action_side_effects`：`{"like_post": "reactions_count", "save_post": "reading_list_count"}`

### 任务三：Codeberg Adapter

**新增文件**：
- `adapters/codeberg/manifest.json`：4 个状态（issue_list/issue_detail/not_logged_in/logged_in），5 个动作
- `adapters/codeberg/handler.py`：非幂等 assign_issue 返回 ActResult 含 side_effect_hint

**FSM 语义核心**：
- `assign_issue` 执行后 current_state 保持 `issue_detail`，不触发状态跳转
- `filter_by_label` 只改变 URL 参数（`?labels=ID`），页面 DOM 结构不变 → 不改变状态
- `paginate` 只改变 URL 参数（页码变化）→ 不改变状态
- `action_side_effects`：`{"assign_issue": "assignees"}`

### 任务四：集成测试

**新增文件**：
- `tests/integration/test_devto.py`：5 个 network 测试
  - `test_home_page_is_feed`：首页 feed 状态
  - `test_feed_extraction`：feed 提取文章列表
  - `test_open_article_from_feed`：feed → article_detail 跳转
  - `test_article_detail_extraction`：详情页字段提取
  - `test_paginate_keeps_state`：翻页保持 feed 状态
- `tests/integration/test_codeberg.py`：5 个 network 测试
  - `test_issue_list_state`：issue_list 状态
  - `test_issue_list_extraction`：issue 列表提取
  - `test_open_issue_detail`：issue_list → issue_detail 跳转
  - `test_issue_detail_extraction`：详情页字段提取
  - `test_paginate_keeps_state`：翻页保持 issue_list 状态

### 任务五：文档更新

**文件**：`docs/adapter_authoring_guide.md`

**变更**：
- 新增"非幂等操作原则"章节，说明 side_effect_hint 和 action_side_effects 的用法
- Adapter 参考表新增 devto 和 codeberg 条目

### Phase 9.5 测试增量汇总

| 任务 | 新增测试 | 测试文件 |
|------|---------|---------|
| Task 2 (DEV.to 集成) | 5 个（全部 network） | test_devto.py |
| Task 3 (Codeberg 集成) | 5 个（全部 network） | test_codeberg.py |

**验证要点**：
- lint 11/11 通过（含 devto + codeberg 两个新 handler）
- 单元测试 80/80 仍然通过
- DEV.to 和 Codeberg 各 5 个集成测试覆盖全部核心路径

---

## Phase 9.6 变更总结（v0.9.6）

核心目标：验证无限滚动场景下，FSM 仍然可以用有限状态表达，且"结束"可以被明确定义。
Mastodon 时间线作为测试目标，三阶终止检测（P1 fingerprint → P2 ID 去重 → P3 timeout）。

### 任务一：_compute_fingerprint 扩展

**文件**：`src/anbm/engine/validator.py`

**变更**：`_compute_fingerprint()` 新增 `container_selector` 参数。
- 提供时只计算指定容器的 innerHTML + URL 的 SHA256（用于无限滚动前后快速比对内容变化）
- 不提供时保持原有的向后兼容行为（遍历所有 state check 的 outerHTML）
- 在 scroll 场景下整页 fingerprint 因页面高度变化永远不同，正确做法是指定容器范围计算 innerHTML

### 任务二：Mastodon Adapter

**新增文件**：
- `adapters/mastodon/manifest.json`：2 个状态（feed_partial/feed_exhausted），1 个动作（scroll_load_more）
- `adapters/mastodon/handler.py`：三阶终止检测
  - P1（fingerprint）：滚动容器 innerHTML 比对，若未变则无新内容
  - P2（ID 去重）：article[data-id] 唯一 ID 去重，统计新加载条目数
  - P3（timeout）：2000ms 等待 + 5000ms 安全网
- `tests/fixtures/html_snapshots/mastodon/feed_partial.html`：含 3 条 article 的最小化 DOM 片段

**FSM 语义核心**：
- `scroll_load_more` 始终返回 `next_state="feed_partial"`（文章 DOM 在滚动耗尽后仍可见，无法通过 DOM 检测到 exhausted）
- 耗尽信号通过 `data.has_more` 传递（`data: {loaded_count, has_more}`）
- `feed_exhausted` 为声明性终止状态，FSM 不会自动转移到该状态

### 任务三：ActResult.data passthrough

**文件**：`src/anbm/engine/router.py`

**变更**：`execute_act()` 确定性路径返回中新增 `data` 字段透传，使 `scroll_load_more` 的 `{loaded_count, has_more}` 可达 API 响应。

### 任务四：Mock 基础设施增强

**文件**：`tests/fixtures/mock_pages.py`

**变更**：
- `FakePage` 新增 `evaluate()` 方法，支持 `window.location.origin`、fingerprint/scroll 等常见 JS 表达式
- `FakePage` 新增 `wait_for_timeout()` 方法（no-op）
- `FakeElement.evaluate()` 新增 `innerHTML` 支持，用于容器 fingerprint 测试
- `HtmlNode` 新增 `inner_html()` 方法，序列化子节点为近似 HTML 字符串

### 任务五：测试

**新增文件**：
- `tests/unit/adapters/test_mastodon.py`：7 个单元测试
  - `test_extract_feed_partial_returns_statuses`：提取 3 条 status，验证字段值
  - `test_extract_feed_partial_all_fields`：每条 status 字段类型正确
  - `test_extract_no_articles_raises_error`：无 article 时抛 SelectorFailedError
  - `test_extract_feed_exhausted`：exhausted 状态返回空列表
  - `test_act_scroll_load_more_dispatches`：scroll_load_more 返回正确结构
  - `test_act_unknown_action_raises`：未知操作抛 ValueError
  - `test_extract_unknown_state_raises`：未知状态抛 ValueError
- `tests/integration/test_mastodon.py`：5 个网络测试
  - `test_feed_partial_state`：时间线检测为 feed_partial
  - `test_feed_extraction`：提取 statuses 验证字段
  - `test_scroll_load_more_keeps_state`：滚动保持 feed_partial
  - `test_scroll_load_more_returns_data`：返回 {loaded_count, has_more}

**现有测试文件更新**：
- `tests/unit/test_validator.py`：新增 3 个容器 fingerprint 测试
  - `test_compute_fingerprint_container_selector`：容器 fingerprint 一致
  - `test_compute_fingerprint_container_selector_dom_change`：DOM 变化产生不同 fingerprint
  - `test_compute_fingerprint_container_not_found`：容器未匹配不抛异常

### Phase 9.6 验证要点

- lint 12/12 通过（含 mastodon handler）
- 单元测试 90/90 通过
- Mastodon 5 个集成测试覆盖核心路径

---

## Phase 9.7 变更总结（v0.9.7）

核心目标：验证核心假设——extract 提取的是"结构化语义信息"，而不是 DOM 内容的镜像。
Unsplash（图片主导站点）和 MDN Web Docs（代码+文本混合站点）作为两个极端场景验证 extract 边界。

### 任务一：Unsplash Adapter

**新增文件**：
- `adapters/unsplash/manifest.json`：2 个状态（photo_grid/photo_detail），4 个动作，全部幂等
- `adapters/unsplash/handler.py`：data-testid 选择器策略，masonry 网格提取，photo_detail 提取作者信息
- `tests/fixtures/html_snapshots/unsplash/photo_grid.html`：3 个 figure 含 masonry data-testid，一个空 alt 用于 extractable:false 测试

**FSM 语义核心**：
- photo_grid 使用 `[data-testid="asset-grid-masonry-figure"]` 检测，React 渲染后的 masonry 照片卡片
- photo_detail 使用 `[data-testid="non-sponsored-photo-download-button"]` 检测，照片详情页下载按钮
- 搜索通过 URL 直构造（`/s/photos/{keyword}`）而非操作搜索框

### 任务二：MDN Web Docs Adapter

**新增文件**：
- `adapters/mdn/manifest.json`：3 个状态（article/search_results/not_found），2 个动作，全部幂等
- `adapters/mdn/handler.py`：Playwright DOM API 提取，pre[class*="brush:"] 代码块，iframe 交互式示例不可穿透
- `tests/fixtures/html_snapshots/mdn/article.html`：h1 标题、代码块、iframe、p 文本、img

**Extract 边界实现**：
- 代码块：`pre[class*="brush:"]` → `{type: "code", content, extractable: True}`
- 交互式示例：`iframe` → `{type: "interactive_viz", src, extractable: False}`（不穿透，不包含 content）
- 图片：`img` → `{type: "image", src, alt, extractable: bool(alt.strip())}`
- 文本：`p` → `{type: "text", content}`（不加工、不推理、不总结）
- 标题：`h2/h3/h4` → `{type: "text", content, heading_level: N}`

### 任务三：Extract 稳定性原则

**新增文档**：
- `docs/adapter_authoring_guide.md` 新增"Extract 稳定性原则"章节

**核心约定**：
- extract = DOM → 稳定结构映射，不做 AI 推理加工
- Media 统一四字段格式：`{type, src, alt, extractable}`
- Text 统一格式：`{type: "text", content}`，标题级别用 `heading_level` 可选字段
- extractable:false 适用场景：iframe、Canvas、装饰性图片（空 alt）、第三方嵌入内容
- Diff 稳定性：同一状态下多次 extract 调用返回一致的内容结构

### 任务四：Mock 基础设施增强

**文件**：`tests/fixtures/mock_pages.py`

**变更**：
- FakePage 新增 `wait_for_selector()` 方法（no-op），handler 中 wait_for_selector 调用可正常执行
- `wait_for_load_state()` 新增 `**kwargs` 参数，兼容 handler 中的额外关键字参数
- `_matches_selector()` 新增 `*=` 属性选择器支持，MDN 的 `pre[class*="brush:"]` 选择器可正确匹配

### Phase 9.7 测试增量汇总

| 文件 | 测试数 | 覆盖范围 |
|------|--------|---------|
| `unit/adapters/test_unsplash.py` | 13 | photo_grid 提取、photo_detail 提取、actions 分发、extract 边界（无推理、空 alt → extractable:false）、未知 state/action 异常 |
| `unit/adapters/test_mdn.py` | 14 | 文章提取、代码块、交互式示例边界、图片边界、文本一致性、iframe 不可穿透、未知 state/action 异常 |
| `integration/test_unsplash.py` | 5 | photo_grid 状态检测、提取、photo_detail 状态、详情提取、搜索导航（全部 network） |
| `integration/test_mdn.py` | 5 | article 状态检测、文章提取、代码块提取、交互式示例边界、文本一致性（全部 network） |

### Phase 9.7 验证要点

- lint 14/14 通过（含 unsplash + mdn 两个新 handler）
- 单元测试 117/117 通过
- extractable:false 场景完全通过 mock 测试
- 集成测试覆盖图片主导和文本主导两种极端场景

---

## Phase 9.8 变更总结（v0.9.8）

核心目标：验证核心假设——session 是可靠的多步执行上下文，中间失败不污染已完成的步骤。
Exercism（exercism.org，无需登录，四步工作流）作为实验对象验证多步状态一致性。

### Step 0-1：失败语义 invariant

**文件**：`src/anbm/engine/fsm.py`

**变更**：
- act() 方法新增 docstring，明确以下失败语义 invariant：
  - 任意步骤失败时，session.current_state 停留在最后一次执行成功的步骤所处的状态
  - 失败不回滚前序步骤产生的状态变更
  - 仅当 detect_state() 本身无法匹配任何已知状态时，current_state 才可能为 unknown
  - state_changed 不等于失败：状态跳转是 FSM 正常流转
- 确认 act() 中 session.update_state() 的调用只在 result["success"] == True 之后

### Step 2：fingerprint cache 页面切换失效

**文件**：`src/anbm/engine/fsm.py`

**变更**：
- act() 中 act 成功且发生状态跳转（next_state != current_state）后，主动调用 `session_store.clear_fingerprint_cache()`
- 同状态操作（如 paginate，next_state == current_state）不清缓存
- 原因：跨页面后 DOM 已完全变更，旧缓存会导致 detect_state() 可能短路返回错误结果

**测试**：`tests/unit/test_fsm.py`
- `test_fingerprint_cache_cleared_on_state_transition`：验证状态跳转时清缓存，同状态不清
- `test_act_failure_preserves_last_successful_state`：验证三步工作流中第三步失败时状态停留在第二步成功后的状态

### Step 3：Exercism Adapter

**新增文件**：
- `adapters/exercism/manifest.json`：4 个状态（track_list/exercise_list/exercise_detail/not_found），3 个幂等动作
- `adapters/exercism/handler.py`：#page-* 结构锚点，section.exercises 提取练习列表，section.instructions 提取题目描述
- `tests/fixtures/html_snapshots/exercism/track_list.html`：最小化 DOM 快照
- `tests/fixtures/html_snapshots/exercism/exercise_list.html`：最小化 DOM 快照
- `tests/fixtures/html_snapshots/exercism/exercise_detail.html`：最小化 DOM 快照

**状态判定原则**：
- 每个状态使用 `#page-*` ID 结构性锚点，不使用 url_matches 作为唯一 check 条件
- 状态上限 4 个，符合约束

**验证**：lint 15/15 PASS（含 exercism handler）

### Step 4：集成测试

**新增文件**：
- `tests/integration/test_exercism.py`：5 个 network 测试
  - `test_track_list_state`：tracks 页面检测为 track_list 状态
  - `test_state_correctly_passed_across_steps`：三步工作流后 state_history 完整
  - `test_cookies_persist_across_steps`：session cookie 数据完整
  - `test_intermediate_failure_preserves_state`：失败后状态停留在最后成功状态
  - `test_state_history_complete_path`：state_history 按顺序包含所有经过的状态

### Phase 9.8 测试增量汇总

| 文件 | 测试数 | 覆盖范围 |
|------|--------|---------|
| `unit/test_fsm.py` | 2 | 失败语义 invariant（test_act_failure_preserves_last_successful_state），fingerprint 缓存清除（test_fingerprint_cache_cleared_on_state_transition） |
| `integration/test_exercism.py` | 5 | track_list 状态、多步工作流状态传递、cookie 持久化、中间失败状态保持、state_history 完整路径（全部 network） |

### Phase 9.8 验证要点

- lint 15/15 通过（含 exercism handler）
- 单元测试 119/119 通过（v0.9.7 基线 117 + 新增 2）
- 失败语义 invariant 已通过 mock 测试验证
- Exercism adapter 未使用 url_matches 作为唯一 check 条件
- 所有现有 adapter 未做改动

---

## Phase 9.9 变更总结（v0.9.9）

核心目标：验证核心假设——session 与 adapter 绑定，跨站点任务由调用方管理多个 session_id。

### 任务一：固化 session 语义边界

**文件**：`src/anbm/engine/session_store.py`、`src/anbm/engine/fsm.py`

**Session dataclass docstring 新增 invariant**：
- 一个 session 只属于一个 adapter（adapter_id 生命周期内不变）
- 跨站点任务由调用方管理多个 session_id，ANBM 不提供跨 session 协调
- cookie_data 只对应创建时的 adapter 所在域名，不跨域
- state_history 只记录本 session 内的状态迁移，不跨 session 合并

**adapter_mismatch 保护**（`fsm.py:browse()`）：
- session 已存在时检测 URL 对应的 adapter
- 若 URL 匹配的 adapter 与 session 绑定的 adapter 不同，返回 `adapter_mismatch` 错误
- 响应包含 `bound_adapter` 和 `requested_adapter` 字段，便于调用方诊断
- 不设置 `session_suspended=True`（调用错误，不是系统故障）

### 任务二：跨 adapter 集成测试

**新增文件**：`tests/integration/test_cross_adapter.py`（5 个 network 测试）
- `test_two_sessions_have_different_adapter_ids`：两个 session 绑定不同 adapter
- `test_cookie_isolation_between_sessions`：cookie 完全隔离
- `test_state_rebuilds_from_scratch_in_new_session`：新 session 状态从头重建
- `test_adapter_mismatch_returns_error`：跨 adapter 请求返回明确错误
- `test_cross_site_workflow_caller_manages_sessions`：跨站工作流由调用方管理 session

### Phase 9.9 测试增量

| 文件 | 测试数 | 覆盖范围 |
|------|--------|---------|
| `integration/test_cross_adapter.py` | 5 | adapter 绑定、cookie 隔离、state 重建、adapter_mismatch 错误、跨站工作流（全部 network） |

### Phase 9.9 验证要点

- 单元测试 119/119 通过（无新增单元测试，v0.9.8 基线不变）
- lint 15/15 PASS（无新增 adapter）
- adapter_mismatch 保护：复用 session 访问不同 adapter 的 URL 返回明确错误
- 两个 session 的 cookie 和 state_history 完全独立
- 所有已有 adapter 未做改动

---

## 遗留问题

### 已解决

所有 v0.7.0 之前记录的已知问题已在各版本中解决：
- v0.6.0：also_check 验证、MCP 全局锁、state_history 无限增长、意外异常路径、健康检查 URL 处理
- v0.7.0：Wikipedia navigate_link 导航、retry_config 环境变量覆盖、结构化日志、Python 客户端 SDK

### 未解决/待评估

以下问题已识别但处于当前范围外，未投入解决：

1. **adapter_version 兼容层**（已记录在"放弃的方案"中）：session 创建时记录 adapter_version 但不做版本比对。当前阶段 adapter 和 session 均无持久化需求，版本兼容层待生产场景触发。

2. **FakePage 完整 DOM 树**（已记录在"放弃的方案"中）：不支持 CSS 后代选择器和伪类。当前 adapter 使用的选择器在一级映射下均可覆盖，收益不匹配成本。

3. **跨 session cookie 共享**：当前每个 session 独立管理 browser context 和 cookie。跨 session 共享 cookie（如同一用户同时操作多个 GitHub Issue）需要上层应用自行管理。
