from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ActRequest(BaseModel):
    session_id: str
    action: str
    params: dict | None = None


@router.post("/act")
async def act_endpoint(req: ActRequest, request: Request):
    fsm = request.app.state.fsm
    return await fsm.act(req.session_id, req.action, params=req.params or {})
