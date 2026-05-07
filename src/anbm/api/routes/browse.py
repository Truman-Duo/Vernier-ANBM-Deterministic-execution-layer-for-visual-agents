from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class BrowseRequest(BaseModel):
    url: str
    session_id: str | None = None
    adapter_hint: str | None = None
    options: dict | None = None
    cookies: list[dict] | None = None


@router.post("/browse")
async def browse_endpoint(req: BrowseRequest, request: Request):
    fsm = request.app.state.fsm

    if req.session_id is None:
        # 无 session_id → 自动创建新 session（不导航，仅分配）
        session = await fsm.create_session(
            url=req.url, adapter_hint=req.adapter_hint
        )
        session_id = session.session_id
    else:
        # 有 session_id → 验证存在（不存在则 401/SessionNotFoundError）
        await fsm.session_store.get(req.session_id)
        session_id = req.session_id

    # browse() 统一处理导航 + 状态检测 + extract
    result = await fsm.browse(session_id, req.url, options=req.options or {}, cookies=req.cookies)

    # 新 session 场景补充 adapter 信息
    if req.session_id is None and "adapter" not in result:
        result["adapter"] = session.adapter_id
        result["adapter_version"] = session.adapter_version

    return result
