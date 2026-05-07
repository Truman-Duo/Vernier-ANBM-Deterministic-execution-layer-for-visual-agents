import logging

from fastapi import APIRouter, Request

from anbm.health.models import AdapterHealthStatus

logger = logging.getLogger(__name__)
router = APIRouter()


def _report_to_dict(report, last_hot_reload=None):
    """Convert HealthReport to serializable dict."""
    return {
        "adapter_id": report.adapter_id,
        "adapter_version": report.adapter_version,
        "checked_at": report.checked_at.isoformat(),
        "status": report.status.value,
        "reason": report.reason.value if report.reason else None,
        "test_url": report.test_url,
        "final_url": report.final_url,
        "detected_state": report.detected_state,
        "last_hot_reload": last_hot_reload,
        "selector_results": [
            {
                "selector": r.selector,
                "state": r.state,
                "found": r.found,
                "candidates": [c.to_dict() for c in r.candidates[:5]],
                "similarity_scores": r.similarity_scores[:5],
            }
            for r in report.selector_results
        ],
        "response_time_ms": report.response_time_ms,
        "raw_error": report.raw_error,
    }


def _get_checker(request: Request):
    """Get health checker from the monitor."""
    fsm = request.app.state.fsm
    return fsm.monitor.checker


@router.get("/health/adapter/{adapter_id}")
async def health_check_adapter(adapter_id: str, request: Request):
    """返回指定 adapter 的最新缓存健康报告（如果有），否则执行一次检查。"""
    fsm = request.app.state.fsm
    last_reload = fsm.adapter_loader.get_last_reload_time(adapter_id)
    cached = fsm.monitor.health_store.get(adapter_id)
    if cached:
        return _report_to_dict(cached, last_hot_reload=last_reload)

    checker = _get_checker(request)
    try:
        report = await checker.check(adapter_id)
        fsm.monitor.health_store[adapter_id] = report
        return _report_to_dict(report, last_hot_reload=last_reload)
    except Exception as e:
        return {
            "adapter_id": adapter_id,
            "status": "not_found",
            "message": str(e),
        }


@router.get("/health/adapters")
async def health_list_adapters(request: Request):
    """返回所有 adapter 的摘要列表。"""
    fsm = request.app.state.fsm
    adapters = fsm.adapter_loader.list_adapters()
    result = []
    for aid in adapters:
        report = fsm.monitor.health_store.get(aid)
        result.append({
            "adapter_id": aid,
            "status": report.status.value if report else "unknown",
            "reason": report.reason.value if report and report.reason else None,
            "checked_at": report.checked_at.isoformat() if report else None,
            "last_hot_reload": fsm.adapter_loader.get_last_reload_time(aid),
        })
    return {"adapters": result}


@router.post("/health/adapter/{adapter_id}/check")
async def health_manual_check(adapter_id: str, request: Request):
    """手动触发一次健康检查，不等定时器。"""
    checker = _get_checker(request)
    try:
        report = await checker.check(adapter_id)
        fsm = request.app.state.fsm
        fsm.monitor.health_store[adapter_id] = report
        last_reload = fsm.adapter_loader.get_last_reload_time(adapter_id)
        return _report_to_dict(report, last_hot_reload=last_reload)
    except Exception as e:
        return {
            "adapter_id": adapter_id,
            "status": "not_found",
            "message": str(e),
        }
