# BF-20260506-2：Windows + Python 3.12 下 uvicorn --reload 模式导致 Playwright 浏览器启动失败

**报告日期**：2026-05-06

**修复版本**：v0.10.0-alpha.1（部分修复）

**严重程度**：Critical（阻塞所有真实环境测试）

**状态**：已修复

---

## 现象

```json
POST /browse {"url": "https://news.ycombinator.com"}
-> 500 Internal Server Error
```

错误日志：
```
File "asyncio\base_events.py", line 524, in _make_subprocess_transport
    raise NotImplementedError
NotImplementedError
```

Playwright 无法启动浏览器进程，所有依赖真实浏览器的 API 端点均不可用。

---

## 根因

Windows 默认的 `SelectorEventLoop` 不支持子进程操作，Playwright 需要 `ProactorEventLoop` 来调用 `create_subprocess_exec()` 启动浏览器进程。

`uvicorn.run(loop="asyncio")` 配置未生效——uvicorn 0.46.0 在 Windows 上无法通过 `loop` 参数正确切换事件循环策略。

---

## 修复

新建 `run_direct.py`，完全接管事件循环生命周期：

```python
#!/usr/bin/env python3
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from uvicorn.config import Config
from uvicorn.server import Server


async def main():
    config = Config(
        "anbm.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
    server = Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
```

**原理**：策略设置在 `asyncio.run()` 之前完成，不依赖 uvicorn 的 `loop` 参数。

---

## 验证标准

1. 健康检查：`curl http://localhost:8000/health` -> 200 `{"status":"ok"}`
2. /browse 核心功能：返回 `session_id` 和 `current_state`，无 500
3. 验证脚本：`python scripts/verify_hackernews.py` -> 全部 PASS

---

## 关联反馈

- **BF-20260506-1**：本 bug 阻塞其真实环境验证
