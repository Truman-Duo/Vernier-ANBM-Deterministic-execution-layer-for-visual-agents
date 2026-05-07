# Vernier 项目介绍（面向非技术读者）

> 内部代号 `anbm`（Agent-Native Browser Middleware）

## 一句话

Vernier 是一个"中间人"程序——它坐在 AI 和网站之间，帮 AI 记住做到哪一步了，指引 AI 按正确顺序操作，在 AI 迷路时及时喊停。

---

## 项目是什么

想象一下：你让一个助理去图书馆查资料。助理走到书架前，每做一步都要跑回来问你"找到了一本书，接下来呢？"。这样效率很低，因为助理记不住刚才做了什么，也不知道整个流程是什么。

Vernier 就是给这个助理准备的"便签本 + 路线图"。有了它：

- **便签本**（Session）：AI 做完一步后，Vernier 记下"已到达第 3 步，当前在详情页"
- **路线图**（FSM 状态机）：Vernier 知道"搜索页面"下一步可以去"打开结果"或"翻页"，但不可以去"提交评论"
- **自动纠错**（Retry）：如果页面加载慢了没找到内容，Vernier 会自动重试，而不是直接告诉 AI 出错了
- **紧急刹车**（Fallback）：如果网站改版了、按钮找不到了，Vernier 会截一张图、明确告知 AI"我不认识这个页面了"，而不是假装一切正常

Vernier 本身**不做决定**——决定由 AI 做。Vernier 只做三件事：记住状态、执行操作、在状态异常时报告。

---

## 能解决什么问题

### 问题一：AI 记不住"刚才做了什么"

没有 Vernier 时，AI 每次操作网站都像是第一次打开——它不知道刚才已经翻到第 3 页了，也不知道刚刚已经点开过哪篇文章。这会导致：

- 重复打开同一篇文章
- 在错误的页面上做不该做的操作（比如在登录页点"翻页"）
- 每步都要重新理解页面，消耗大量算力

### 问题二：网站改版导致 AI 不知所措

网站改版在互联网世界是家常便饭。没有 Vernier 时，AI 可能在改版后的页面上盲目操作，产生错误结果而用户完全不知情。

Vernier 的做法是：每个适配器（Adapter）都有一套明确的"怎么判断当前页面"的规则。规则失效时，Vernier **明确报错**，不静默产生错误结果。

### 问题三：一步一步截图太贵了

AI 通过截图理解页面（视觉模型）非常消耗算力和时间——每步都要传输和处理整张图片。Vernier 让大部分步骤走"结构化路径"（直接读代码找元素，不需要看图），只有出问题时才截图分析。这大幅降低了成本和延迟。

---

## 与类似项目的区别

### 和浏览器自动化工具（如 Selenium、Playwright）的区别

这些工具是"遥控器"——它们可以控制浏览器打开网页、点击按钮，但不知道自己在做什么、下一步该做什么。Vernier 是"遥控器 + 笔记本 + 路线图"——它知道当前状态、下一步能做什么、做错了怎么处理。

### 和 AI Agent 框架（如 AutoGPT）的区别

AI Agent 框架让 AI 自己决定每一步做什么。这很灵活，但也容易跑偏——AI 可能第 3 步就忘了第 1 步的目标是什么。

Vernier 走的是**约束路径**——不交给 AI 自由发挥，而是由状态机定义清晰的"当前状态 → 允许的操作 → 下一个状态"。AI 只能在允许的范围内选择。这看起来限制更多，但在多步任务中更可靠。

### 和 RPA（机器人流程自动化）的区别

RPA 也是按固定流程操作，但 RPA 非常脆弱——页面元素位置变了就失败。Vernier 通过语义定位（找"搜索按钮"而不是找"坐标(100,200)处的按钮"）和自动重试机制，比传统 RPA 更适应页面变化。

### 核心区别总结

| | Vernier | 浏览器自动化工具 | AI Agent 框架 | RPA |
|---|---|---|---|---|
| 记状态 | ✅ 有状态机 | ❌ 无状态 | ❌ 无内置状态 | ✅ 有状态 |
| 操作方式 | 结构化 + 视觉兜底 | 纯结构化 | 纯视觉/LLM | 结构化 |
| 网站改版 | 明确报错 | 静默失败 | 可能静默失败 | 静默失败 |
| 出错处理 | 分级重试 | 脚本崩溃 | 可能无限循环 | 脚本崩溃 |
| 适用场景 | 多步精确任务 | 单步测试 | 开放式探索 | 固定流程 |

---

## 目标用户

Vernier 目前是**开发者工具**，不是面向普通用户的产品。以下人群可能感兴趣：

1. **AI 应用开发者**：正在构建需要操作网站的 AI Agent，需要一个可靠的多步执行"中间层"

2. **数据采集工程师**：需要从多个网站提取结构化数据，希望有比传统爬虫更健壮的方案

3. **DevOps 工程师**：负责维护浏览器自动化基础设施，需要健康监控和故障诊断工具

4. **开源贡献者**：对浏览器自动化和状态机设计感兴趣，希望为开源社区贡献适配器

如果你**不是**上述人群，但读到这里依然感兴趣，仍然可以尝试使用——只需要能用命令行和知道一些基本概念就行。

---

## 详细使用方法

### 第一步：安装

```bash
# 需要 Python 3.10+
# 从源码安装
pip install -e .

# 安装 Chromium 浏览器
playwright install chromium
```

### 第二步：启动服务

```bash
# 启动 API 服务
uvicorn anbm.api.server:app --reload --port 8000
```

看到类似这样的输出说明启动成功：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 第三步：发送请求

> 不需要写代码——用 `curl` 命令行工具即可。打开一个新的终端窗口。

**浏览一个网站：**

```bash
curl -X POST http://localhost:8000/browse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://news.ycombinator.com/news","adapter_hint":"hackernews"}'
```

你会收到类似这样的响应：

```json
{
  "session_id": "xxx",
  "current_state": "news_list",
  "adapter": "hackernews",
  "data": {
    "stories": [
      {"title": "...", "url": "...", "score": 123}
    ]
  },
  "retry": {"attempts": 1, "succeeded": true},
  "execution_path": "deterministic",
  "session_suspended": false
}
```

关键信息解读：
- `session_id` — 本次浏览的"会话编号"，后续操作需要带上它
- `current_state` — 当前页面类型（这里是"新闻列表页"）
- `data` — 提取的数据（新闻列表）
- `execution_path: "deterministic"` — 正常执行，没有问题

**在同一个会话中执行操作：**

```bash
# 注意替换 SESSION_ID 为上一步返回的 session_id
curl -X POST http://localhost:8000/act \
  -H "Content-Type: application/json" \
  -d '{"session_id":"xxx","action":"paginate"}'
```

这里的 `action` 参数必须是当前状态允许的操作。

**查询会话状态：**

```bash
curl http://localhost:8000/session/xxx
```

返回当前状态、历史记录、重试统计等。

### 第四步：用 Python 写脚本（更简单）

如果你想在 Python 里用：

```python
from anbm.client import ANBMClient

client = ANBMClient()

# 浏览 Hacker News
result = client.browse("https://news.ycombinator.com/news", adapter_hint="hackernews")
print("找到", len(result["data"]["stories"]), "条新闻")
print("标题:", result["data"]["stories"][0]["title"])

# 翻页
sid = result["session_id"]
result2 = client.act(sid, "paginate")
print("翻页成功:", result2["execution_path"])

# 删除会话（清理资源）
client.delete_session(sid)
```

### 第五步：试更多网站

Vernier 支持 15 个网站。把 `adapter_hint` 换成以下任一试试：

| 标识 | 网站 | 可以做 |
|------|------|--------|
| `douban_movie` | 豆瓣电影 | 查看 Top250 并翻页 |
| `hackernews` | Hacker News | 浏览新闻、翻页、看评论 |
| `wikipedia` | 维基百科 | 看文章、提取目录 |
| `reddit` | Reddit | 浏览子版块、投票 |
| `github_issues` | GitHub Issues | 浏览 Issue、发评论、关闭 Issue |
| `arxiv` | arXiv | 搜索论文、看详情 |

### 第六步：查看健康状态

```bash
# 检查某个适配器是否正常工作
curl http://localhost:8000/health/adapter/hackernews

# 列出所有适配器的健康状态
curl http://localhost:8000/health/adapters
```

或使用命令行工具：

```bash
anbm check --all
anbm status
```

### 第七步：出了问题怎么办

**现象：请求返回 `execution_path: "visual_fallback"`**

这意味着适配器失效了（可能是网站改版）。请查看详细错误信息，然后：

1. 用健康检查确认问题范围：
   ```bash
   anbm check hackernews
   ```
2. 如果确认选择器失效，可用修复向导：
   ```bash
   anbm repair hackernews --dry-run
   ```
3. 或报告给项目维护者，等待适配器更新

---

## 工作流程示意图

```
你（用户/AI Agent）
  │
  ▼ 发送请求
API 服务 (http://localhost:8000)
  │
  ▼ 识别网站类型
适配器层 (找对应的"网站说明书")
  │
  ▼ 执行操作
浏览器引擎 (Playwright 控制无头浏览器)
  │
  ▼ 返回结果
你收到结构化数据
```

如果出错：

```
出错 → 自动重试（最多 3 次）
  ├── 重试成功 → 返回数据
  └── 重试失败 → 截图分析
        ├── 能识别 → 继续
        └── 不能识别 → 明确告知你"我遇到了无法处理的情况"
```

---

## 常见问题（非技术向）

### Vernier 能自动适应网站改版吗？

不能。网站改版后对应的适配器需要手动更新。但 Vernier 的好处是：**适配器失效时它会明确告诉你"我不认识这个页面了"**，而不是静默产生错误数据。健康检查工具会帮你诊断具体哪个选择器出了问题。

### 我完全不会编程，能用吗？

目前还不太适合。安装和运行需要命令行操作和基本的 JSON 理解能力。但如果你愿意学，上手并不难——核心只有 3 个 API 接口。

### Vernier 和浏览器插件的区别是什么？

浏览器插件帮你**看**网页（去广告、记密码）；Vernier 帮 AI **操作**网页（点按钮、读数据、记住步骤）。

### Vernier 会被网站封禁吗？

Vernier 内置了反检测措施（伪装浏览器指纹），但不做任何对抗性操作。如果网站有明确的反爬策略，Vernier 也不会尝试绕过。它在设计上是一个**协作工具**，不是攻击工具。

### 支持哪些浏览器？

目前只支持 Chromium（通过 Playwright 控制）。

### 最多能记住多少步？

每个会话（session）的状态历史最多保留 50 条。超过时自动删除最旧的记录。

### 能同时运行多个任务吗？

可以。每个任务使用不同的 session_id，互不干扰。但注意：一个 session 一次只能执行一个操作（并发请求会收到"忙"的错误）。
