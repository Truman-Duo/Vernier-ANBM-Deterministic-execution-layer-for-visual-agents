import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from anbm.adapter.base import SessionNotFoundError, AdapterNotFoundError
from anbm.adapter.loader import ADAPTERS_DIR
from anbm.adapter.watcher import AdapterWatcher
from anbm.api.routes import browse, act, session, health
from anbm.engine.fsm import FSMEngine


@asynccontextmanager
async def lifespan(app):
    fsm = FSMEngine()
    app.state.fsm = fsm
    await fsm.monitor.start()

    # Adapter 热重载
    watcher = None
    if os.environ.get("ANBM_HOT_RELOAD", "true").lower() == "true":
        watcher = AdapterWatcher(fsm.adapter_loader, ADAPTERS_DIR, fsm_engine=fsm)
        await watcher.start()
        app.state.watcher = watcher

    try:
        yield
    finally:
        if watcher:
            await watcher.stop()
        await fsm.monitor.stop()


app = FastAPI(
    title="ANBM — Agent-Native Browser Middleware",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(request, exc: SessionNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": "session_not_found", "session_id": exc.session_id},
    )


@app.exception_handler(AdapterNotFoundError)
async def adapter_not_found_handler(request, exc: AdapterNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": "adapter_not_found", "adapter_id": exc.adapter_id},
    )


app.include_router(browse.router, tags=["browse"])
app.include_router(act.router, tags=["act"])
app.include_router(session.router, tags=["session"])
app.include_router(health.router, tags=["health"])


@app.get("/health")
async def health():
    return {"status": "ok"}


def get_fsm(request: Request) -> FSMEngine:
    return request.app.state.fsm
