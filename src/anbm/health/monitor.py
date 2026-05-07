import asyncio
import logging
import os

from anbm.adapter.loader import AdapterLoader
from anbm.health.checker import HealthChecker
from anbm.health.models import AlertEvent
from anbm.health.reporter import AlertReporter

logger = logging.getLogger(__name__)


class AdapterMonitor:
    """
    后台健康巡检器。
    ANBM_MONITOR_ENABLED=true 时启动定时循环，在每个 adapter 状态变化时触发告警。
    开发环境默认不启动。
    """

    def __init__(
        self,
        checker: HealthChecker,
        loader: AdapterLoader,
        reporter: AlertReporter | None = None,
        interval_seconds: int = 3600,
    ):
        self.checker = checker
        self.loader = loader
        self.reporter = reporter or AlertReporter()
        self.interval = interval_seconds
        self.health_store: dict[str, "HealthReport"] = {}
        self._task: asyncio.Task | None = None
        self.enabled = os.getenv("ANBM_MONITOR_ENABLED", "false").lower() == "true"

    async def start(self):
        if not self.enabled:
            logger.info("AdapterMonitor disabled (ANBM_MONITOR_ENABLED != true)")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("AdapterMonitor started (interval=%ds)", self.interval)

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("AdapterMonitor stopped")

    async def _loop(self):
        while True:
            try:
                for adapter_id in self.loader.list_adapters():
                    try:
                        report = await self.checker.check(adapter_id)
                        prev = self.health_store.get(adapter_id)
                        self.health_store[adapter_id] = report
                        if prev is None or prev.status != report.status:
                            failed = [
                                r for r in report.selector_results if not r.found
                            ]
                            await self.reporter.emit(
                                AlertEvent(
                                    adapter_id=adapter_id,
                                    previous_status=prev.status if prev else None,
                                    current_status=report.status,
                                    reason=report.reason,
                                    failed_selectors=failed,
                                    report=report,
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            "Monitor check failed for %s: %s", adapter_id, e,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Monitor loop error: %s", e)

            await asyncio.sleep(self.interval)
