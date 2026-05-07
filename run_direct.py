#!/usr/bin/env python3
"""
ANBM 服务启动入口（Windows 兼容，直接模式）。

在 asyncio.run() 之前设置事件循环策略，确保 Windows 上使用
ProactorEventLoop，避免 Playwright 子进程操作因 SelectorEventLoop
不支持 create_subprocess_exec 而失败。

用法：
    python run_direct.py
"""

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
