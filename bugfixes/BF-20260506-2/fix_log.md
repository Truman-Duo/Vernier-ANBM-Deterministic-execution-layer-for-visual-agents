# BF-20260506-2 修复日志

## 背景

Windows + Python 3.12 下，Playwright 需要 `ProactorEventLoop`，但 `uvicorn --reload` 模式下 `loop="asyncio"` 配置未生效。

---

## Attempt 1：基础验证（确认根因）

**测试**：Python 3.12 的 asyncio 子进程能力
```powershell
python -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy()); asyncio.run(asyncio.create_subprocess_exec('python', '--version'))"
```
**结果**：`Python 3.12.6` 正常输出 —— Python 3.12 本身无问题。

**结论**：问题在 uvicorn 配置层，而非 Python/asyncio 层。

---

## Attempt 2：评估修复方案

| 方案 | 本质 | 侵入性 | 推荐度 |
|------|------|--------|--------|
| 方案1：关闭热重载（reload=False） | 绕过问题 | 1行修改 | ⭐⭐⭐ |
| 方案2：新建 run_direct.py 接管事件循环 | 架构调整 | 新建文件 | ⭐⭐⭐ |
| 方案3：使用 uvicorn 命令行启动 | 运维标准化 | 修改启动脚本 | ⭐⭐ |
| 方案4：升级/降级 uvicorn 版本 | 依赖调整 | 2行修改 | ⭐⭐ |

**选定方案2**，新建 `run_direct.py`：
- 确定性高，不受 uvicorn 配置影响
- 事件循环策略在 `asyncio.run()` 之前设置
- 方案1作为临时备选

---

## Attempt 3：应用修复

**变更**：新建 `run_direct.py`

**验证**：启动 `run_direct.py`，请求 `/health` 和 `/browse`，确认浏览器启动正常

**结果**：通过
