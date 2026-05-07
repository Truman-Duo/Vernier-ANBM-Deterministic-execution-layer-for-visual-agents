# BF-20260507-1：Adapter 提取选择器与目标网站当前 UI 不匹配

**报告日期**：2026-05-07

**修复版本**：v0.10.0-alpha.2

**严重程度**：Medium（不影响稳定性，但 extract 降级为 visual_fallback）

**状态**：已分析

---

## 现象

导航成功后，`extract()` 找不到对应元素，进入 `visual_fallback`：

### GitHub Issues

```
"selector_diff": {
  "failed_selector": "[role=\"row\"] or [role=\"listitem\"]",
  "error_context": "找不到 issue 列表"
}
```

### Reddit

```
"selector_diff": {
  "failed_selector": "shreddit-post or [role=\"article\"]",
  "error_context": "找不到帖子列表"
}
```

---

## 根因

### GitHub Issues

`[role="listitem"]` 选择器本身正确。用户通过 DevTools 确认 DOM 中存在 `<li role="listitem">` 元素。
问题在于测试仓库（`Truman-Duo/Lexi-Semantic-Vocabulary-Classifier`）没有 issue，页面渲染为空状态，
没有任何 `[role="listitem"]` 元素。

用有 issue 的仓库（`Hmbown/DeepSeek-TUI`）测试，`[role="listitem"]` 正常提取 3/3 步骤全部 PASS。

**结论**：选择器正确，测试数据问题（空仓库）。

### Reddit

Reddit 在边缘节点直接检测并屏蔽 headless Chromium，返回 **403** 纯 CSS 屏蔽页，
页面不含任何实际内容（0 个自定义元素、0 个脚本、0 个帖子元素）。

即使尝试以下措施均无效：
- 添加 session cookie
- 使用系统 Chrome（`channel="chrome"`）
- 增强 stealth 脚本（`navigator.webdriver`、`navigator.plugins`、`chrome.runtime`）
- 使用 `old.reddit.com`
- 禁用 `AutomationControlled`

Reddit 基于 TLS/HTTP 指纹在传输层拒绝连接，并非前端选择器问题。

**结论**：不是选择器失效，是 headless 浏览器被 Reddit 服务器端屏蔽。

---

## 解决方案

### GitHub

无需修改选择器。在有 issue 的仓库上测试即可 PASS。

### Reddit

因 Reddit 服务器端封锁 headless 浏览器，Playwright 无法渲染实际页面内容。
当前无可行绕过方案。建议：

1. 文档标注：Reddit adapter 需要真实的浏览器环境（非 headless）
2. 或者研究 puppeteer-extra-plugin-stealth 等更全面的反检测方案
3. 或者考虑通过 Reddit API（OAuth）替代浏览器自动化

---

## 涉及文件

- `adapters/github_issues/handler.py` — `[role="listitem"]` 选择器正确，无需修改
- `adapters/reddit/handler.py` — `shreddit-post` 选择器在真实浏览器中正确，headless 下无法验证
- `scripts/verify_github.py` — 增加 HTTP 状态码检查
- `scripts/verify_reddit.py` — 默认 subreddit 改为 `python`
- `src/anbm/executor/browser.py` — 添加 `channel="chrome"` 支持
- `src/anbm/engine/fsm.py` — 添加 API cookie 传递机制
