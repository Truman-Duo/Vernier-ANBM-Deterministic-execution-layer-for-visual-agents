# Adapter 贡献指南

## 什么是 Adapter

Adapter 是 Vernier 中负责**单步页面交互**的模块。每个 Adapter 对应一个网站，封装了该网站特定页面的**状态检测**、**数据提取**和**操作执行**逻辑。

Adapter **不做**流程编排（翻页循环、重试、状态跳转判断）——这些由引擎层的 `RetryOrchestrator` 和 `DecisionRouter` 处理。

---

## 快速开始（以 HN Adapter 为例）

一个 Adapter 只需两个文件：

```
adapters/hackernews/
├── manifest.json   # 状态机定义、URL 匹配、幂等性声明
└── handler.py      # extract() 和 act() 实现
```

### 1. 创建目录

```bash
mkdir adapters/your_site
```

### 2. 编写 manifest.json

FSM 状态**必须由页面 DOM 语义决定，而非 URL 参数**。选择器应使用 `element_present` / `aria_present` 等结构锚点：

```json
{
  "id": "pypi",
  "name": "PyPI",
  "version": "1.0.0",
  "url_patterns": ["https://pypi.org/search/*", "https://pypi.org/project/*"],
  "states": {
    "project_list": {
      "check": { "type": "element_present", "selector": "[data-controller='search']" },
      "also_check": { "type": "element_absent", "selector": "#description" },
      "allowed_actions": ["filter_version", "open_project", "paginate"]
    },
    "project_detail": {
      "check": { "type": "element_present", "selector": "#description" },
      "also_check": { "type": "element_absent", "selector": "[data-controller='search']" },
      "allowed_actions": ["extract_content"]
    }
  },
  "transitions": {
    "project_list": { "filter_version": "project_list", "open_project": "project_detail", "paginate": "project_list" },
    "project_detail": { "extract_content": "project_detail" }
  },
  "action_idempotency": {
    "filter_version": true,
    "open_project": true,
    "paginate": true,
    "extract_content": true
  }
}
```

**核心原则**：URL query 参数变化（`?q=flask`、`?page=2`）、URL 路径变化但页面语义不变（`/` → `/t/rust`），都不构成 FSM 状态变化。只有页面 DOM 结构发生根本性变化（从列表页跳到详情页）才触发状态转移。

### 3. 编写 handler.py

```python
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError

class Handler(BaseAdapter):
    async def extract(self, page, state: str) -> ExtractResult:
        if state == "news_list":
            rows = await page.query_selector_all("tr.athing")
            if not rows:
                raise SelectorFailedError("找不到新闻列表行", selector="tr.athing")
            # ... 提取数据
            return ExtractResult(data={...}, state="news_list")
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "paginate":
            link = await page.query_selector("a.morelink")
            if not link:
                raise SelectorFailedError("找不到翻页链接", selector="a.morelink")
            await link.click()
            return ActResult(success=True, next_state="news_list")
        raise ValueError(f"act() 不支持操作: {action}")
```

### 4. 添加 HTML 快照用于测试

在 `tests/fixtures/html_snapshots/your_site/` 中创建仅包含被测选择器对应 DOM 的 HTML 片段文件（< 50KB），用于 `FakePage.from_html()` 单元测试。

### 5. 运行 lint 确认通过

```bash
python scripts/lint_adapter.py
```

---

## manifest.json 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一标识符，用于 API 的 `adapter_hint` |
| `name` | string | 是 | 人类可读名称 |
| `version` | string | 是 | 语义化版本，selector 变更 → patch+1 |
| `url_patterns` | string[] | 是 | URL 匹配模式（`*` 通配符），用于自动识别 |
| `test_url` | string | 是 | 健康检查使用的直接可访问 URL（不应含通配符） |
| `states` | object | 是 | 状态定义，**最多 6 个** |
| `transitions` | object | 是 | 状态转移矩阵 |
| `action_idempotency` | object | 是 | 每个 action 的幂等性声明 |
| `output_schema` | object | 否 | extract 返回字段的文档 |

### 状态数上限 6 个

`detect_state()` 按 manifest 中 states 的遍历顺序逐一匹配。状态数过多会导致：
- 检测延迟线性增长（每个状态都要执行 check）
- 复杂页面可能误匹配到优先级过高的状态

超过 6 个时，考虑将正交维度降级为 extract 数据字段（如 HN 的 `is_logged_in`），而非新建状态。

### action_idempotency 的影响

| 幂等 | max_attempts | 失败后行为 |
|------|-------------|-----------|
| `true` | 2 | retry 2 次，耗尽后进入 visual_fallback |
| `false` | 1 | 不 retry，返回 `requires_human_decision: true` |

非幂等操作（发评论、投票、关闭 Issue）失败后**不**进入 visual_fallback——操作可能部分执行，视觉模型无法回滚。必须交给人类判断。

### also_check 的使用场景

当页面类型（URL 匹配）和登录状态（元素存在性）是两个正交维度时，使用 `also_check`：

```json
{
  "check": { "type": "element_present", "selector": "div.story_content" },
  "also_check": { "type": "element_absent", "selector": "ol.stories.list" }
}
```

这样在保持状态数 ≤ 6 的前提下，精准控制两个互斥状态不会被同时匹配。详见 VERSION.md 设计决策 5。

---

## handler.py 规则

### 禁止清单

以下模式在 handler.py 中**严格禁止**，CI 的 `lint_adapter.py` 会静态检查：

| 禁止模式 | 原因 |
|---------|------|
| `except SelectorFailedError` | 选择器异常应由 RetryOrchestrator 处理，handler 不应吞掉 |
| `except PageTimeoutError` | 超时应由 RetryOrchestrator 的重试逻辑处理 |
| `await self.act()` | handler 不跨方法编排——engine 层决定调用顺序 |
| `await self.extract()` | 同上，handler 只实现单步操作 |
| `session.current_state =` | handler 不修改 FSM 状态——由 DecisionRouter 管理 |
| `time.sleep()` | 重试等待由 RetryOrchestrator 管理 |
| `asyncio.sleep()` | 同上 |
| `for _ in range()` | handler 不写 retry loop |
| `while True` / `while attempt` | 同上 |

### 选择器优先级

```
data-* 属性 > aria role/text > CSS class > 标签名
```

**原因**：
- `data-*` 是专为测试/自动化设计的属性，改版频率最低
- `aria-*` 是无障碍标准，改动有流程约束
- CSS class 频繁随前端框架重构变化，稳定性最差

### 找不到元素统一抛 SelectorFailedError

```python
# 正确
el = await page.query_selector('[data-testid="title"]')
if not el:
    raise SelectorFailedError("找不到标题", selector='[data-testid="title"]')

# 错误 — 不 return None，这样调用方不知道是"没找到"还是"数据为空"
if not el:
    return None
```

`SelectorFailedError` 会被 `RetryOrchestrator` 捕获并触发重试或 fallback。返回 `None` 则静默失败，丢失重试机会。

---

## 本地验证流程

### 1. 用 HTML 快照写单元测试

```python
from tests.fixtures.mock_pages import FakePage

# 用 DOM 片段创建 FakePage
page = FakePage.from_html("""
  <div data-testid="issue-title">Fix login bug</div>
  <div data-testid="issue-body">Users cannot log in</div>
""", url="https://github.com/owner/repo/issues/1")

# 测试选择器匹配
title_el = await page.query_selector('[data-testid="issue-title"]')
assert (await title_el.text_content()) == "Fix login bug"
```

HTML 快照文件放在 `tests/fixtures/html_snapshots/{adapter_id}/` 目录下。只包含被测选择器对应的 DOM 片段（< 50KB），不包含完整页面。

### 2. 用真实验证脚本测网络

```bash
# 设置凭证（根据 adapter 需要）
export GITHUB_SESSION_COOKIE='[{"name":"user_session","value":"...","domain":"github.com"}]'

# 运行验证
python scripts/verify_github.py
```

真实验证脚本在 `scripts/verify_{site}.py`，它们通过 HTTP 调用运行中的 API 服务进行端到端验证。

### 3. 确认 lint 通过

```bash
python scripts/lint_adapter.py
```

---

## 非幂等操作原则

v0.9.5 引入非幂等操作的成功信号独立于状态变化的验证机制。核心设计：**非幂等操作执行后 FSM 状态不变，系统不把"状态未变"误判为"操作失败"**。

### side_effect_hint

非幂等操作成功后，handler 应在返回的 `ActResult` 中设置 `side_effect_hint` 字段，向 Agent 提示哪个数据字段将因本次操作而变化：

```python
# like_post 后，reactions_count 将增加
return ActResult(
    success=True,
    next_state="article_detail",  # 状态不变
    side_effect_hint="reactions_count_incremented",
)

# assign_issue 后，assignees 列表将更新
return ActResult(
    success=True,
    next_state="issue_detail",  # 状态不变
    side_effect_hint="assignees_updated",
)
```

`side_effect_hint` 不影响引擎逻辑，不强制校验。它只是给 Agent 的提示，Agent 可以据此决定是否调用 `extract()` 验证副作用是否生效。

### action_side_effects

在 `manifest.json` 中记录每个非幂等操作影响的数据字段：

```json
{
  "action_side_effects": {
    "like_post": "reactions_count",
    "save_post": "reading_list_count",
    "assign_issue": "assignees"
  }
}
```

`action_side_effects` 是文档性质字段，引擎层不强制执行。它为 Agent 和开发者提供快速参考——当某个操作执行后，哪个 extract 字段会变化。

### 状态不变是正常情况

like、save、assign_issue 等非幂等操作只修改页面上的数据（点赞数、收藏状态、指派对象），不改变页面的整体语义结构。所以 FSM 状态理应保持不变：

- `article_detail → like_post → article_detail`（点赞后仍在文章详情页）
- `issue_detail → assign_issue → issue_detail`（指派后仍在 issue 详情页）

FSM 状态由**页面 DOM 语义结构**决定，而非由页面上的数据变化决定。

---

## Extract 稳定性原则

v0.9.7 引入 Extract 边界定义，核心原则：**extract 提取的是"结构化语义信息"，而不是 DOM 内容的镜像**。

### 核心原则

extract = DOM → 稳定结构映射。不做推理、不做语义解读：

```
输入：DOM 树
处理：选择器匹配 → 类型分类 → 字段映射
输出：{ type, src, alt, extractable, content } 等结构化字段
边界：不穿透 iframe，不解析 canvas，不推理图片内容
```

### Media 内容格式

所有媒体类型统一使用四字段格式：

```python
{
    "type": "image",            # 媒体类型标识
    "src": "https://...",       # 资源 URL
    "alt": "description",       # 替代文本（可能为空）
    "extractable": True,        # 是否能进一步提取
}
```

- `extractable: True` — alt 文本非空，可被下游使用的
- `extractable: False` — alt 为空（如装饰性图片），或内容不可穿透（iframe、canvas）

### Text 内容格式

文本块统一格式：

```python
{
    "type": "text",
    "content": "段落文字...",
}
```

标题级别信息通过可选字段表达：

```python
{
    "type": "text",
    "content": "章节标题",
    "heading_level": 2,  # h2 → 2, h3 → 3, h4 → 4
}
```

### extractable: false 的边界

以下内容的 `extractable` 必须为 `false`：

| 场景 | 类型 | 原因 |
|------|------|------|
| iframe 交互式示例 | `interactive_viz` | 不穿透 iframe，不提取内部内容 |
| Canvas/WebGL | `interactive_viz` | 像素内容无法结构化提取 |
| 装饰性图片（空 alt） | `image` | 无文本描述，无法语义化 |
| 第三方嵌入内容 | `interactive_viz` | 跨域限制，不可控 |

### Diff 稳定性

同一状态下多次 extract 调用返回的内容结构必须一致：

```python
# 两次 extract 返回的 content_blocks 结构相同
resp1 = await client.post(f"http://localhost:8000/browse/{sid}", json={"url": URL})
resp2 = await client.post(f"http://localhost:8000/browse/{sid}", json={"url": URL})

# 字段类型一致
assert isinstance(resp1.json()["data"]["title"], str)
assert isinstance(resp2.json()["data"]["title"], str)
```

- 不做 AI 推理加工（不总结、不翻译、不补全）
- 不做 DOM 结构镜像（不保留嵌套层级、不保留样式信息）
- 只做类型分类 + 字段映射

### 实现建议

1. **优先使用 Playwright DOM API**（`query_selector_all`、`text_content`、`get_attribute`），而非 `page.evaluate()`。DOM API 返回的数据天然是结构化的，而 evaluate 返回的 JS 对象可能在序列化过程中丢失类型信息。
2. **对每个 extract 返回的 block 做类型分类**，而非简单遍历所有 DOM 元素。不同类型的 block 使用不同的选择器路径。
3. **不要拼接或加工文本内容**。`text_content()` 的原始返回值就是最终值，不做 strip() 以外的任何处理。
4. **多个 extract 调用产生相同的结构**。确保遍历顺序稳定（如按 DOM 顺序），不做排序或去重。

---

## 多步工作流状态一致性

v0.9.8 验证的核心假设：**session 是可靠的多步执行上下文，中间失败不污染已完成的步骤**。

### 失败语义 invariant

当多步工作流中某一步失败时：

1. **失败不回滚**：session.current_state 停留在最后一次执行成功的步骤所处的状态
2. **无副作用残留**：失败步骤不会污染 state_history
3. **Agent 可继续**：基于 current_state 可以决定从当前状态继续还是重新开始
4. **lock 已释放**：异常传播后 finally 块确保 session lock 被释放

### 示例：四步工作流

```python
# 工作流：browse → act(open_track) → act(open_exercise) → extract
resp = await client.post("/browse", json={"url": tracks_url, "adapter_hint": "exercism"})
sid = resp.json()["session_id"]
# → current_state = "track_list"

# 第二步成功
await client.post(f"/act/{sid}", json={"action": "open_track", "params": {"track": "python"}})
# → current_state = "exercise_list"

# 第三步失败（不存在的 exercise）
resp = await client.post(f"/act/{sid}", json={
    "action": "open_exercise", "params": {"exercise": "nonexistent"}
})
# → current_state 仍为 "exercise_list"（失败不改变状态）
```

### fingerprint cache 跨页面失效

跨页面导航后（如从 track_list → exercise_list），旧页面的 DOM fingerprint 缓存已失效。

**自动清除**：引擎层在 act() 发生状态跳转（next_state != current_state）时主动清除 fingerprint cache。

**无需手动处理**：Adapter handler 开发者不需要关心缓存逻辑，引擎层自动管理。

### 设计要点

1. **state_history 不可篡改**：已成功执行的状态不可被后续失败移除
2. **current_state 是信任锚点**：Agent 可以信任 current_state 反映的是最后一次成功的状态
3. **visual_fallback 不影响状态**：即使进入 visual_fallback（session_suspended=True），current_state 保持不变

---

## 常见问题排查

### selector 失效了怎么办

1. **健康检查确认**：`GET /health/adapter/{id}` — 如果返回 `status: "degraded"`，说明所有状态都检测不到
2. **chaos_test 模拟**：`python scripts/chaos_test.py` 验证系统在 selector 失效时的行为是否符合预期
3. **对比 HTML 快照**：打开浏览器 DevTools，对比真实页面 DOM 与 `tests/fixtures/html_snapshots/` 中的快照，找出差异

修复 selector 后更新 `manifest.json` 的 `version`（patch+1），同时更新 html_snapshot 文件。

### unknown 频率过高意味着什么

如果 `detect_state()` 频繁返回 `"unknown"`，说明页面在加载过程中处于过渡状态。解决方案：

```python
# 在 act() 的页面导航操作后加 wait_for_load_state
await page.goto(url, wait_until="networkidle")
# 或者
await link.click()
await page.wait_for_load_state("networkidle")
```

### 状态数超过 6 个时怎么重构

平面 FSM 无法表达"页面维度 × 登录维度"的笛卡尔积状态空间。解决方案：**将其中一个维度降级为数据字段**。

以 HN 为例，有 `news_list` / `item_detail` 两个页面状态，加上登录/未登录就是 4 个组合。但因为 HN 允许未登录浏览，所以登录状态降级为 extract 返回的 `is_logged_in` 字段：

```python
# extract() 末尾
logout_el = await page.query_selector("a#logout")
is_logged_in = logout_el is not None
return ExtractResult(data={
    "stories": stories,
    "is_logged_in": is_logged_in,  # 数据字段而非 FSM 状态
}, state="news_list")
```

当后续增加写操作时，使用 `also_check` 在页面状态上附加 auth 条件，而非并列独立状态。

---

## 完整 Adapter 参考

| Adapter | 状态数 | 动作数 | 非幂等 | 特点 |
|---------|--------|--------|--------|------|
| douban_movie | 2 | 1 | 0 | 纯只读，CSS class 选择器 |
| reddit | 4 | 5 | 2(login, upvote_post) | 登录+投票，data-testid 选择器 |
| github_issues | 4 | 7 | 3(login, post_comment, close) | 完整工作流，混合选择器 |
| hackernews | 2 | 2 | 0 | 纯只读，嵌套评论提取 |
| wikipedia | 2 | 1 | 0 | 纯只读，目录提取 |
| pypi | 3 | 4 | 0 | 纯只读，结构锚点定状态，filter_version 不改状态 |
| lobsters | 3 | 4 | 0 | 纯只读，结构语义锚点，filter_by_tag 不改状态 |
| devto | 4 | 6 | 3(login, like_post, save_post) | 非幂等 like/save 不改状态，side_effect_hint 指示副作用 |
| codeberg | 4 | 5 | 2(login, assign_issue) | 非幂等 assign_issue 不改状态，filter_by_label 不改状态 |
| exercism | 4 | 3 | 0 | 纯只读多步工作流，#page-* 结构锚点，无需登录 |

选择与你的目标网站最相似的一个作为起点。

---

## 选择器类型优先级

从 v0.9.0 开始，推荐的选择器优先级（从高到低）：

1. `aria_present` / `aria_absent`  — 语义稳定，首选（改版不会轻易破坏可访问性语义）
2. `data-*` 属性的 `element_present`  — 次选（data-testid 等测试属性相对稳定）
3. CSS class 的 `element_present`  — 可用（class 是样式副产品，改版风险最高）

`url_contains` / `url_matches` 不受此排序影响，按需使用。

---

## fallback_description 编写指南

`fallback_description` 是 manifest.json 中 check 条件的可选字段，用于描述目标元素的语义和位置关系。当 selector 失效时，HealthChecker 和 repair 向导会用这个描述辅助查找替代选择器。

### 编写原则

1. **说语义，不说 HTML 结构**（不要写"在第三个 div 里的 span"）
2. **说位置关系**（"紧跟排名序号之后"、"位于页面顶部导航栏"）
3. **说视觉特征**（"包含封面图、标题、评分"）
4. **长度控制在 50 字以内**

### 示例

**不好的描述**：
```
"class 为 v 的 span 元素"
```

**好的描述**：
```
"电影中文标题文字，通常紧跟在排名序号之后"
```

### 哪些 check 需要加

- `element_present` 和 `element_absent` 类型的 check / also_check 建议补充
- `url_contains` / `url_matches` 不需要

---

## Session 语义边界

session 是**单站点执行上下文**，而不是跨站点任务的容器。

### 核心约束

- 一个 session 只绑定一个 adapter，生命周期内 `adapter_id` 不变
- cookie 只在该 adapter 对应的域名范围内有效，不跨域共享
- `state_history` 只记录本 session 内的状态迁移

### 跨站点任务的正确做法

跨站点工作流由**调用方（Agent）**管理多个 session_id，Vernier 不提供跨 session 协调能力：

```python
# 正确：调用方管理两个独立 session
session_pypi = client.browse("https://pypi.org/project/requests/", adapter_hint="pypi")
github_url = session_pypi["data"]["github_url"]  # 从数据中提取

session_gh = client.browse(github_url, adapter_hint="github_issues")  # 新 session，不传 session_id
```

```python
# 错误：试图复用 session 跨越不同 adapter
session_pypi = client.browse("https://pypi.org/...", adapter_hint="pypi")
# 下面这行会返回 adapter_mismatch 错误：
client.browse("https://github.com/...", session_id=session_pypi["session_id"])
```

### 为什么这样设计

- session 状态的语义来自特定 adapter 的 manifest（状态名、转换规则都是 adapter 特有的）
- 允许跨 adapter 会导致 `state_history` 语义混乱（`logged_in` 在 reddit 和 github 是完全不同的状态）
- 跨站点协调是 Agent 的职责，不是中间层的职责
