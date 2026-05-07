# Vernier — Deterministic Execution Layer for Visual Agents

状态机执行中间层，为视觉 Agent 提供多步任务的状态记忆与确定性路径（内部代号 `anbm`）。FSM 定义路径，retry 只是让路径更稳定，不替代路径判断。

视觉 Agent 在单步操作上已足够可靠，但多步任务链存在两个问题：无状态导致的错误累积，以及冗余的 Token 消耗。Vernier 作为中间层补足这两块——状态机记住多步之间发生了什么，确定性步骤走结构化路径不走视觉模型，分级重试让瞬态失败自动恢复、状态跳转立即上报、非幂等操作零重试。

## 快速开始

```bash
pip install -e .
playwright install chromium
uvicorn anbm.api.server:app --reload --port 8000

# 浏览 Hacker News 首页
curl -X POST http://localhost:8000/browse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://news.ycombinator.com/news","adapter_hint":"hackernews"}'
```

或用 Python 客户端 SDK：

```python
from anbm.client import ANBMClient

client = ANBMClient()
result = client.browse("https://news.ycombinator.com/news", adapter_hint="hackernews")
print(result["data"]["stories"][0]["title"])
```

## 三个 API

### POST /browse

导航到 URL，检测当前状态，提取结构化数据。

```json
{"url": "...", "adapter_hint": "douban_movie", "session_id": null}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `url` | string | 目标 URL |
| `adapter_hint` | string | 可选，指定 adapter（不指定则自动匹配） |
| `session_id` | string | 可选，复用已有 session（不指定则创建新 session） |

### POST /act

在当前 session 执行一个操作（翻页、打开链接、投票、发评论等）。

```json
{"session_id": "...", "action": "paginate", "params": {}}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | session ID |
| `action` | string | 操作名，必须被当前状态允许 |
| `params` | object | 可选，操作参数 |

### GET /session/{id}

查询 session 状态、历史、retry 统计。

### 响应字段

所有响应都包含以下三个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `execution_path` | string | `"deterministic"` \| `"state_changed"` \| `"visual_fallback"` |
| `retry` | object | `{"attempts": int, "succeeded": bool}` |
| `session_suspended` | bool | session 是否被挂起 |

| execution_path | 含义 | Agent 应做什么 |
|---|---|---|
| `deterministic` | 正常执行 | 继续下一步 |
| `state_changed` | 页面状态意外跳转 | 重新调用 `/browse` 同步后继续 |
| `visual_fallback` | Adapter 失效，已转视觉模型 | 读取 `fallback_result`，人工决策后调 `/browse` |

## 异常情况下的行为

Adapter 可能因网站改版导致 selector 失效。此时系统经过 3 次自动重试后进入 visual_fallback，session 被挂起，明确告知 Agent "Adapter 失效"，不会静默产生错误结果。

```
[Chaos Test 输出示例]
============================================================
  Vernier 破坏性演练 — Chaos Test
============================================================

--- Step 1/7: 破坏选择器 ---
  选择器 'ol.grid_view div.item' → '.js-broken-selector'

--- Step 2/7: GET /health/adapter/douban_movie ---
  [PASS] status=degraded

--- Step 3/7: POST /browse → visual_fallback ---
  [PASS] execution_path=visual_fallback, retry.attempts=3, suspended=True

--- Step 4/7: GET /session/{id} → fallback_count == 1 ---
  [PASS] fallback_count=1

--- Step 5/7: 恢复原始选择器 ---
  已从备份恢复

--- Step 6/7: GET /health/adapter/douban_movie → healthy ---
  [PASS] status=healthy
```

健康检查端点 `GET /health/adapter/{id}` 提供 adapter 实时状态（healthy / degraded / unreachable），运维可集成到监控系统。

## 已支持的网站

15 个 Adapter，覆盖社区论坛、开发工具、学术、媒体、社交五大类。

验证状态分为两级：
- **真实环境** — 已通过真实验证脚本在目标网站上跑通，确认当前选择器有效
- **单元测试** — 有完整的单元测试和集成测试覆盖，但最近未在真实环境重新验证

### 真实环境验证通过

| Adapter | 状态数 | 支持操作 | 最近验证 |
|---|---|---|---|
| `hackernews` | 2 | 浏览新闻列表、翻页、看评论 | 2026-05-07，5/5 deterministic |
| `github_issues` | 4 | 登录、浏览 Issues、发评论、关闭 Issue | 2026-05-07，3/3 deterministic |

### 真实环境验证受阻

| Adapter | 状态数 | 受阻原因 |
|---|---|---|
| `reddit` | 4 | 服务器端 TLS/HTTP 指纹检测屏蔽 headless Chromium |

### 单元测试覆盖（待真实环境验证）

| Adapter | 状态数 | 支持操作 | 集成测试 |
|---|---|---|---|
| `douban_movie` | 2 | 提取 Top250、翻页 | 6 个 |
| `wikipedia` | 2 | 浏览文章、提取目录 | 4 个 |
| `stackoverflow` | 4 | 浏览问题、搜索、upvote | 5 个 |
| `arxiv` | 4 | 搜索论文、翻页、看详情 | 5 个 |
| `pypi` | 3 | 搜索项目、筛选版本、翻页 | 5 个 |
| `lobsters` | 3 | 浏览故事、按标签筛选、搜索 | 5 个 |
| `devto` | 4 | 浏览文章、like、save | 5 个 |
| `codeberg` | 4 | 浏览 Issue、分配、筛选 | 5 个 |
| `mastodon` | 2 | 浏览时间线、无限滚动加载 | 5 个 |
| `unsplash` | 2 | 浏览照片墙、搜索、看详情 | 5 个 |
| `mdn` | 3 | 浏览文档、提取代码块 | 5 个 |
| `exercism` | 4 | 浏览 Track、练习题、详情 | 5 个 |

每个 Adapter 的详细能力见 `adapters/{id}/manifest.json`。验证脚本位于 `scripts/verify_*.py`，真实环境测试记录见 [TEST_LOG.md](TEST_LOG.md)。

## 开发新 Adapter

每个 Adapter 只需两个文件（`manifest.json` + `handler.py`），三小时可完成一个：

- `manifest.json` — 状态机定义、URL 匹配、幂等性声明（[字段说明](docs/adapter_authoring_guide.md#manifestjson-字段说明)）
- `handler.py` — `extract()` 和 `act()` 实现（[编写规则](docs/adapter_authoring_guide.md#handlerpy-规则)）

详见 [Adapter 贡献指南](docs/adapter_authoring_guide.md)。

## 项目边界

**Vernier 是**：状态机执行框架 + 社区维护的网站 Adapter + 视觉模型的确定性补充层。

**Vernier 不是**：自动适应网站改版的万能层 / 替代视觉模型的 AI 系统 / 反爬虫方案。

网站改版后对应 Adapter 需要手动更新。Adapter 失效时系统明确报错并通知 Agent，不会静默产生错误结果。

## License

MIT
