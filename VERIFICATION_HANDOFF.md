# ANBM v0.10.0-beta.1 真实验证报告 v3（最终版）— 给 Claude Code 的交接文档

**生成者**: Claude Desktop Cowork  
**日期**: 2026-05-17（三轮验证）  
**用途**: cc 据此修复失效选择器、更新 manifest、推进 beta.1

---

## 一、Bridge v2 验证系统

### 1.1 文件清单

```
anbm/
  bridge_server.py              # Python stdlib HTTP 中继 v2（零依赖）
  .bridge/
    PROTOCOL.md                 # 通信协议规格
    extension/
      manifest.json             # Chrome MV3 扩展
      background.js             # Service worker v2
      content.js                # DOM 扫描 v2（sanitize 防 JSON 损坏）
      popup.html                # 控制面板 v2
      popup.js                  # 控制面板 v2.1
    sites/{adapter}/            # DOM 快照（支持状态后缀，防覆盖）
```

### 1.2 已确认可用的功能

| 功能 | 状态 |
|------|------|
| Bridge 连接 + 3s 超时健康检查 | ✅ |
| Adapter 下拉列表（15个）+ 状态选择器 | ✅ |
| 域名自动检测（URL 正则匹配） | ✅ |
| 扫描当前页 + 上传（content.js v2 sanitize） | ✅ |
| 快照防覆盖（按状态命名） | ✅ |
| 验证此 Adapter（一键测试所有选择器） | ✅ |
| 单个选择器快速测试 | ✅ |
| 批量扫描 | ❌ 待修 |

### 1.3 已知问题

**#1: 批量扫描 create_tab/URL 错误** — background.js 缺少 handler，URL 构造逻辑需要从 manifest test_url 读取。当前手动逐个扫够用。

**#2: popup.js 文件写入限制** — VM Write/Edit 工具对大文件不可靠，需修改时用 bash heredoc。

---

## 二、15 Adapter 完整验证状态

```
✅ = 全部通过    ⚠️ = 部分失效（列出失效选择器及替代）   ❌ = 阻塞
```

### ✅ lobsters（18/18）
| 页面 | 选择器 | 状态 |
|------|--------|------|
| 列表页 | ol.stories.list, li.story, a.u-url, a.tag, .voters .upvoter, .domain, .byline .u-author, .comments_label a, nav.morelink a | ✅ |
| 列表页 | div.story_content (also_check absent) | ✅ |
| 详情页 | div.story_content, textarea | ✅ |
| 详情页 | ol.stories.list (also_check absent) | ✅ |

### ✅ hackernews（5/5，2026-05-07 验证，需重新确认）
### ✅ github_issues（3/3，2026-05-07 验证，需重新确认）

### ⚠️ pypi（列表页 ✅ / 详情页 1 失效）
| 失效选择器 | 替代方案 |
|-----------|---------|
| `.sidebar-section__body`（详情页） | 新版侧边栏不再用 __body 包裹值。可用 `.sidebar-section__classifiers`、`.sidebar-section__maintainer` 或直接取 `.sidebar-section` 文本 |

### ⚠️ stackoverflow（列表页 ✅ / 详情页 4 失效）
| 失效选择器 | 替代方案 |
|-----------|---------|
| `[itemprop="name"]`（标题） | 新版 SO 移除所有 schema.org 微数据。可用 `h1 a` 或 `.s-prose` 前元素 |
| `[itemprop="text"]`（正文） | 改用 `.s-prose.js-post-body` |
| `[itemprop="upvoteCount"]`（投票数） | 改版后投票在 `.s-post-summary--stats-item__emphasized .s-post-summary--stats-item-number` |
| `[rel="tag"]`（标签，详情页） | 列表页仍有590x，详情页无。详情页标签需另选 |
| ✅ `[aria-label$="answers"]` | 仍有效 |
| ✅ `[aria-label="Up vote"]` | 仍有效 |

### ⚠️ arxiv（搜索页 ✅ / 1 失效）
| 失效选择器 | 替代方案 |
|-----------|---------|
| `a[href^='/abs/']`（论文链接） | href 是完整 URL `https://arxiv.org/abs/...`，改为 `a[href*='/abs/']` |

### ⚠️ wikipedia（5/6）
| 失效选择器 | 替代方案 |
|-----------|---------|
| `a.interlanguage-link-target`（语言链接） | Wikipedia 改版为下拉菜单 `#p-lang-btn`。非核心功能（语言链接列表） |

### ⚠️ unsplash（data-testid 更名）
| 失效选择器 | 替代方案 |
|-----------|---------|
| `[data-testid='asset-grid-masonry-figure']` | 改用 `[data-testid='photos-feed-route']`。Unsplash 是 React SPA，可能需要滚动触发图片加载 |

### ❌ mastodon（需登录）
hachyderm.io 公开时间线仅返回 1 个顶层元素，`article[data-id]` 不存在。需登录或换用 mastodon.social 测试。

### ❌ reddit（TLS 指纹屏蔽，非代码问题）
### ✅ codeberg（issue_list 全部有效）
### ✅ devto（feed 全部有效）
### ✅ exercism（track_list 全部有效）
### ✅ douban_movie（movie_list 全部有效）
### ✅ mdn（article 全部有效）

---

## 三、cc 需修复的失效选择器汇总

| 优先级 | Adapter | 失效选择器 | 替代建议 | 文件 |
|--------|---------|-----------|---------|------|
| P0 | pypi | `.sidebar-section__body` | `.sidebar-section__classifiers` 或直接取 section 文本 | handler.py |
| P0 | stackoverflow | 4 个 `[itemprop]` + `[rel="tag"]` | `.s-prose.js-post-body`、`.s-post-summary--stats-item-number` 等 | handler.py |
| P1 | arxiv | `a[href^='/abs/']` | `a[href*='/abs/']` | handler.py |
| P1 | unsplash | `[data-testid='asset-grid-masonry-figure']` | `[data-testid='photos-feed-route']` | manifest.json |
| P2 | wikipedia | `a.interlanguage-link-target` | `#p-lang-btn`（或从 output_schema 移除 language_links） | handler.py |
| P2 | mastodon | `article[data-id]` | 需在已登录 Mastodon 实例上重新验证 | manifest.json |

---

## 四、可选改进（非阻塞）

- T5.3：act 后 URL 漂移检测
- bridge 批量扫描修复（#1, #2）
- `getSelectorsForState()` 为所有 15 adapter 补全选择器定义
- 跑完整 ANBM 测试套件（pytest unit + integration + lint）

---

## 五、DOM 快照位置

所有快照在 `.bridge/sites/{adapter}/`：
```
arxiv/dom_snapshot_search_results.json
codeberg/dom_snapshot_issue_list.json
devto/dom_snapshot_feed.json
douban_movie/dom_snapshot_movie_list.json
exercism/dom_snapshot_track_list.json
lobsters/dom_snapshot_story_list.json
lobsters/dom_snapshot_story_detail.json
mastodon/dom_snapshot_feed_partial.json
mdn/dom_snapshot_article.json
pypi/dom_snapshot_project_list.json
pypi/dom_snapshot_project_detail.json
stackoverflow/dom_snapshot_question_list.json
stackoverflow/dom_snapshot_question_detail.json
unsplash/dom_snapshot_photo_grid.json
wikipedia/dom_snapshot.json
```
