from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/session/{session_id}")
async def get_session(session_id: str, request: Request):
    fsm = request.app.state.fsm
    session = await fsm.session_store.get(session_id)
    return {
        "session_id": session.session_id,
        "adapter": session.adapter_id,
        "adapter_version": session.adapter_version,
        "current_state": session.current_state,
        "session_suspended": session.session_suspended,
        "state_history": session.state_history,
        "retry_stats": session.retry_stats,
        "created_at": session.created_at.isoformat(),
        "last_action_at": session.last_action_at.isoformat(),
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, request: Request):
    fsm = request.app.state.fsm
    await fsm.session_store.delete(session_id)
    return {"deleted": True, "session_id": session_id}
