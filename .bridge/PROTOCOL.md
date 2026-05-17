# .bridge/ Protocol Specification v1

Bridge 是 Chrome 扩展和 Claude (Cowork VM) 之间的文件通信协议。
通信介质：workspace 文件夹下的 `.bridge/` 子目录。
传输方向：Chrome 扩展 ← HTTP → bridge_server.py ← 文件 R/W → Claude

## 目录结构

```
workspace/.bridge/
  sites/
    {adapter_id}/
      dom_snapshot.json    # 扩展抓取的页面 DOM 结构
      screenshot.png       # 页面截图 (base64 in JSON or raw png)
  tasks/
    {task_id}.json         # Claude 下达的验证任务
  results/
    {task_id}.json         # 扩展执行的验证结果
  adapters/
    {adapter_id}/
      manifest.json        # Claude 生成的 manifest
      handler.py           # Claude 生成的 handler
  status.json              # bridge 运行状态
```

## HTTP API (bridge_server.py → Chrome 扩展)

bridge_server 监听 `localhost:8765`，CORS 全开。

### POST /snapshot

扩展上传页面 DOM 快照。

Request:
```json
{
  "adapter_id": "lobsters",
  "url": "https://lobste.rs",
  "title": "Lobsters",
  "timestamp": "2026-05-17T12:00:00Z",
  "elements": [
    {
      "tag": "div",
      "role": "article",
      "text": "Why Rust is great...",
      "attrs": {"class": "story", "data-short-id": "abc123"},
      "children": [
        {"tag": "a", "role": "link", "text": "Why Rust is great...", "attrs": {"class": "u-url"}},
        {"tag": "span", "text": "42 comments", "attrs": {"class": "comments_label"}}
      ]
    }
  ],
  "aria_tree": "... (optional accessibility tree text)",
  "state_hint": "story_list"
}
```

Response 200: `{"ok": true, "task_count": 0}`

### POST /selector-result

扩展执行 selector 检查后上报结果。

Request:
```json
{
  "task_id": "verify_lobsters_20260517_001",
  "adapter_id": "lobsters",
  "results": [
    {
      "selector": "div.story",
      "found": true,
      "count": 25,
      "sample_html": "<div class=\"story\">...</div>"
    },
    {
      "selector": "a.comments",
      "found": true,
      "count": 25,
      "sample_html": null
    }
  ]
}
```

Response 200: `{"ok": true}`

### GET /tasks?adapter_id=lobsters

扩展轮询是否有待执行任务。返回第一条 pending task。

Response 200 (有任务):
```json
{
  "task_id": "verify_lobsters_20260517_001",
  "adapter_id": "lobsters",
  "url": "https://lobste.rs",
  "state": "pending",
  "actions": [
    {"type": "test_selector", "selector": "div.story", "expect": "present"},
    {"type": "test_selector", "selector": "a.u-url", "expect": "present"},
    {"type": "navigate", "url": "https://lobste.rs/t/rust"},
    {"type": "capture_dom", "label": "filtered list"}
  ]
}
```

Response 200 (无任务): `{"task_id": null}`

### GET /health

Response 200: `{"ok": true, "uptime_seconds": 3600, "tasks_pending": 3, "snapshots_received": 12}`

## 文件格式 (Claude ↔ bridge_server)

### .bridge/sites/{adapter_id}/dom_snapshot.json

同 POST /snapshot 的 request body。

### .bridge/tasks/{task_id}.json

Claude 写入此文件来给扩展下达任务。

```json
{
  "task_id": "verify_lobsters_20260517_001",
  "adapter_id": "lobsters",
  "created_at": "2026-05-17T12:05:00Z",
  "state": "pending",
  "url": "https://lobste.rs",
  "actions": [
    {
      "type": "test_selector",
      "selector": "div.story",
      "expect": "present",
      "label": "story card container"
    },
    {
      "type": "test_selector", 
      "selector": "a[aria-label]",
      "expect": "present",
      "label": "any aria-labeled link"
    },
    {
      "type": "navigate",
      "url": "https://lobste.rs/t/rust",
      "label": "filtered by tag"
    },
    {
      "type": "capture_dom",
      "label": "tag-filtered page",
      "state_hint": "story_list_filtered"
    }
  ]
}
```

state 流转：`pending` → `in_progress` (bridge 分发后) → `completed` (收到 selector-result 后)

### .bridge/results/{task_id}.json

扩展完成验证后，bridge 写入此文件。

同 POST /selector-result 的 request body，附加：
```json
{
  "completed_at": "2026-05-17T12:06:00Z",
  "duration_ms": 4523
}
```

### .bridge/adapters/{adapter_id}/

Claude 直接将生成的 adapter 文件写入此目录。

## 通信时序

```
扩展                    bridge_server              workspace/.bridge/         Claude (VM)
 │                          │                           │                         │
 │  POST /snapshot ───────→ │ ──write──→ sites/lobsters/dom_snapshot.json ──read──→ │
 │                          │                           │                         │
 │                          │                           │   分析 DOM，选 selector    │
 │                          │                           │   生成 manifest+handler   │
 │                          │                           │                         │
 │                          │                           │ ←──write── tasks/verify*.json
 │                          │                           │ ←──write── adapters/lobsters/*
 │                          │                           │                         │
 │  GET /tasks?adapter ───→ │ ←──read── tasks/verify*.json                        │
 │  ←── task JSON           │                           │                         │
 │                          │                           │                         │
 │  执行 selector test      │                           │                         │
 │  POST /selector-result → │ ──write──→ results/verify*.json ──read──→           │
 │                          │                           │                         │
 │                          │                           │   验证结果，修正 adapter   │
```

## 错误处理

- bridge_server 未启动：扩展 popup 显示 "Bridge 离线"，禁用功能按钮
- 文件写入失败：bridge 返回 500 + error 字段
- 任务超时（5 分钟未完成）：Claude 将 task state 改为 `timeout`
