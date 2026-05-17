# ANBM v0.10.0-beta.1 下一步执行计划

本文档供 Claude cowork 独立执行。包含：当前状态、已完成项、待执行项、精确命令。

---

## 当前状态总览（2026-05-17）

```
已完成 ✅
├── PyPI adapter 选择器修复（5 个 selector，基于 DOM 快照验证）
├── Stack Overflow adapter 选择器修复（7 个 selector，基于 DOM 快照验证）
├── 全部 15 个 manifest.json 增加 last_verified 时间戳
├── SO HTML fixture + 集成测试更新
├── 单元测试 126/126 PASS
├── Lint 15/15 PASS
├── 文档更新（CLAUDE.md、CHANGELOG.md、TEST_LOG.md）
└── Bridge 验证系统搭建完成（Chrome 扩展 + HTTP 中继）

待执行 ❌
├── 【P0 阻塞】修 bridge content.js JSON 转义 bug
├── 【P1】启动 ANBM 服务 → 跑 PyPI/SO verify 确认修复有效
├── 【P1】跑全量集成测试（86 个）
├── 【P1】实施 T5.3 act 后 URL 漂移检测（beta.1 唯一代码改进）
├── 【P2】扫描剩余 7 个 adapter（需先修 bridge bug）
├── 【P2】端到端 repair CLI 流程验证
└── 【P3】更新 VERSION.md → v0.10.0-beta.1，打 tag
```

---

## 第一部分：P0 阻塞项 — 修 bridge JSON 转义 bug

### 问题

`content.js` 的 `captureDOMSnapshot()` 在大页面（arXiv 79KB、Lobsters 270KB）上偶发 JSON 解析错误。
根因：DOM 文本内容中的特殊字符（Unicode 引号、`<`、`&`、换行符）未正确转义。

### 修复

文件：`.bridge/extension/content.js`

在 `extractText()` 函数和属性提取中对 `"` `\` 和控制字符做转义，
或在 `walk()` 函数返回前对 text/attr value 做 sanitize。

参考方向：
```javascript
function sanitize(str) {
    return str.replace(/\\/g, '\\\\')
              .replace(/"/g, '\\"')
              .replace(/\n/g, '\\n')
              .replace(/\r/g, '\\r')
              .replace(/\t/g, '\\t')
              .replace(/[\x00-\x1f]/g, '');
}
```

### 验证

修好后重新扫描 arXiv 搜索页 + arXiv 论文详情页，确认 DOM 快照可完整解析。

---

## 第二部分：P1 项 — 核心验证

### P1.1 启动服务 + 验证 PyPI/SO 修复

```bash
cd C:\Users\Duo\Desktop\Truman\ClaudeCode_WorkSpace\anbm

# 终端 1：启动服务
python run_direct.py

# 终端 2：PyPI 快速验证
curl -X POST http://localhost:8000/browse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://pypi.org/search/?q=requests","adapter_hint":"pypi"}'

# 期望：200，current_state="project_list"，execution_path="deterministic"

# 终端 2：SO 快速验证
curl -X POST http://localhost:8000/browse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://stackoverflow.com/questions","adapter_hint":"stackoverflow"}'

# 期望：200，current_state="question_list"，execution_path="deterministic"
```

**若失败**：记录 response body 中的 `execution_path`、`selector_diff`、`error` 字段。

### P1.2 全量集成测试

```bash
# 全部（耗时较长，约 30-40 分钟）
python -m pytest tests/integration/ -v -m network --timeout=60

# 或优先跑关键架构场景
python -m pytest tests/integration/test_pypi.py -v -m network --timeout=60
python -m pytest tests/integration/test_stackoverflow.py -v -m network --timeout=60
python -m pytest tests/integration/test_cross_adapter.py -v -m network --timeout=60
python -m pytest tests/integration/test_pypi.py::test_filter_version_does_not_change_state -v -m network
python -m pytest tests/integration/test_pypi.py::test_paginate_keeps_state -v -m network
```

**期望**：PyPI 和 SO 的测试全部通过（选择器已更新）。其他 adapter 可能因网站改版失败——记录失败列表。

### P1.3 实施 T5.3：act 后 URL 漂移检测

**文件**：`src/anbm/engine/fsm.py`（`act()` 方法）

**要做什么**：act 成功返回后，对比 `page.url` 和当前 state 的 `url_patterns`。
如果 URL 已变化且不匹配当前状态的任何 pattern，标记为 `state_changed`。

**实现位置**：在 `fsm.py:act()` 中 `result["success"] == True` 且 `next_state == current_state` 的分支中，
增加 URL 检查逻辑。

**伪代码**：
```python
if result["success"] and next_state == current_state:
    current_url = page.url
    current_state_config = manifest["states"].get(current_state, {})
    url_patterns = manifest.get("url_patterns", [])
    # 检查当前 URL 是否仍匹配当前状态
    url_still_matches = any(pattern in current_url for pattern in url_patterns 
                           if "search" not in pattern)  # 简化检查
    if not url_still_matches:
        # 尝试用 detect_state 重新检测
        new_state, _ = await validator.detect_state(page, manifest, ...)
        if new_state != current_state and new_state != "unknown":
            result["execution_path"] = "state_changed"
            result["next_state"] = new_state
            # 记录 URL 漂移信息
            result["url_drift"] = {"from": current_url, "detected_state": new_state}
```

**测试**：在 `tests/unit/test_fsm.py` 中新增 `test_url_drift_detected_after_act`，
用 FakePage 模拟 act 成功后 URL 变化的场景。

**工作量**：约 1 小时。

---

## 第三部分：P2 项 — 扩大验证覆盖

### P2.1 扫描剩余 7 个 adapter

**前提**：P0 bridge JSON bug 已修复。

逐个打开目标网站 → 点扩展图标 → 填 adapter_id → 扫描：

| # | Adapter | 目标 URL | 需扫状态 |
|---|---------|----------|---------|
| 1 | douban_movie | `https://movie.douban.com/top250` | movie_list |
| 2 | devto | `https://dev.to` | feed, article_detail |
| 3 | codeberg | `https://codeberg.org/Codeberg/org/issues` | issue_list, issue_detail |
| 4 | mastodon | `https://fosstodon.org/explore` | feed_partial |
| 5 | unsplash | `https://unsplash.com` | photo_grid, photo_detail |
| 6 | mdn | `https://developer.mozilla.org/en-US/docs/Web/JavaScript` | article |
| 7 | exercism | `https://exercism.org/tracks` | track_list, exercise_list |

每次扫描后：
- 检查 `.bridge/sites/{id}/dom_snapshot.json` 是否完整可解析
- 对照 `adapters/{id}/manifest.json` 中的 check/also_check 选择器逐一验证
- 失效的选择器参考 handoff 报告 3.3/3.4 的格式，写修复建议
- 更新 `last_verified` 时间戳

### P2.2 端到端 repair CLI 流程验证

**目的**：确认 T5.1（LLM selector 推荐 + 人工确认 + 写入 adapter）的完整链路可用。

**步骤**：
1. 选一个已验证的 adapter（如 lobsters），故意改坏一个 selector
2. 运行 `python -m anbm.cli check lobsters`
3. 确认检测到 DEGRADED
4. 运行 `python -m anbm.cli repair lobsters --dry-run`
5. 确认候选列表中有合理建议
6. 选择一个候选写入（带 `--dry-run` 不实际写入）
7. 验证修复后 selector 写入了备份文件

**期望**：四阶段流程（诊断 → 候选选择 → 验证 → 写入）完整跑通。

---

## 第四部分：P3 项 — 发布准备

### P3.1 更新 VERSION.md

当前 VERSION.md 记录到 v0.9.9。需要追加：
- v0.10.0-alpha.1 / alpha.2 的变更（从 TEST_LOG.md 中提取）
- v0.10.0-beta.1 的变更（从 CHANGELOG.md Phase 10 中提取）
- 更新版本号到 `v0.10.0-beta.1`

### P3.2 打 tag

```bash
git add -A
git commit -m "v0.10.0-beta.1: adapter decay fix (PyPI + SO) + freshness tracking"
git tag v0.10.0-beta.1
```

### P3.3 最终检查清单

```
[ ] 单元测试 126/126（或更多，含 T5.3 新增测试）
[ ] Lint 15/15
[ ] PyPI verify: deterministic
[ ] SO verify: deterministic
[ ] 集成测试关键场景: 全 PASS
[ ] Bridge JSON bug: 已修复
[ ] VERSION.md: 已更新至 beta.1
[ ] CHANGELOG.md: Phase 10 完整
[ ] TEST_LOG.md: beta.1 条目完整
[ ] last_verified: 已扫描的 adapter 全部更新
[ ] git tag: v0.10.0-beta.1
```

---

## 附录：快速命令参考

```bash
# 环境
cd C:\Users\Duo\Desktop\Truman\ClaudeCode_WorkSpace\anbm
pip install -e .
python run_direct.py                              # 启动服务

# 测试
python -m pytest tests/unit/ -v                   # 单元测试（无网络）
python -m pytest tests/integration/ -v -m network --timeout=60  # 集成测试（需网络+服务）
python lint_adapter.py                            # Lint 检查

# Verify 脚本
python verify_hackernews.py                       # HN（需服务启动）
python verify_github.py                           # GitHub（需 GITHUB_TEST_REPO）

# Bridge
python bridge_server.py                           # 启动 bridge 中继

# CLI
python -m anbm.cli check --all                    # 全部 adapter 健康状态
python -m anbm.cli status                         # 系统摘要
python -m anbm.cli repair <adapter_id> --dry-run  # 修复预演
```
