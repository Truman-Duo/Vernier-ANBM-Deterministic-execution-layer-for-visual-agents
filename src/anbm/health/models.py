from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


class AdapterHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"
    UNREACHABLE = "unreachable"


class DegradationReason(str, Enum):
    SELECTOR_CHANGED = "selector_changed"
    STRUCTURE_CHANGED = "structure_changed"
    URL_MOVED = "url_moved"
    SERVICE_DOWN = "service_down"
    AUTH_REQUIRED = "auth_required"


@dataclass
class SelectorCandidate:
    selector: str
    source: Literal["css_similar", "aria_candidate", "llm_suggested"]
    similarity: float | None  # llm_suggested 时为 None

    def to_dict(self) -> dict:
        return {
            "selector": self.selector,
            "source": self.source,
            "similarity": self.similarity,
        }


@dataclass
class SelectorCheckResult:
    selector: str
    state: str
    found: bool
    candidates: list[SelectorCandidate] = field(default_factory=list)
    similarity_scores: list[float] = field(default_factory=list)


@dataclass
class HealthReport:
    adapter_id: str
    adapter_version: str
    checked_at: datetime
    status: AdapterHealthStatus
    reason: DegradationReason | None
    test_url: str
    final_url: str
    detected_state: str
    selector_results: list[SelectorCheckResult]
    response_time_ms: int
    raw_error: str | None = None


@dataclass
class AlertEvent:
    adapter_id: str
    previous_status: AdapterHealthStatus | None
    current_status: AdapterHealthStatus
    reason: DegradationReason | None
    failed_selectors: list[SelectorCheckResult]
    report: HealthReport
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
