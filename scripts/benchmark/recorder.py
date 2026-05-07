"""
BenchmarkRecorder：verify 脚本的 metrics 记录工具。

用法：
    recorder = BenchmarkRecorder(adapter_id="hackernews")
    recorder.record_step(
        step_name="paginate",
        execution_path="deterministic",
        retry_attempts=1,
        success=True,
        duration_ms=342,
    )
    recorder.save()  # 写入 scripts/benchmark/results/
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

RESULTS_DIR = Path(__file__).parent / "results"

ExecutionPath = Literal["deterministic", "state_changed", "visual_fallback"]


@dataclass
class StepResult:
    step_name: str
    execution_path: ExecutionPath
    retry_attempts: int
    success: bool
    duration_ms: int
    selector_diff: dict | None = None
    error: str | None = None


@dataclass
class BenchmarkRun:
    adapter_id: str
    run_id: str
    started_at: str
    finished_at: str | None
    steps: list[StepResult] = field(default_factory=list)
    overall_success: bool = False

    success_rate: float = 0.0
    retry_attempts_distribution: dict = field(default_factory=dict)
    execution_path_distribution: dict = field(default_factory=dict)
    total_duration_ms: int = 0


class BenchmarkRecorder:
    def __init__(self, adapter_id: str):
        self.adapter_id = adapter_id
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._steps: list[StepResult] = []
        self._step_start: float | None = None

    def step_start(self):
        """在每个 verify 步骤开始前调用。"""
        self._step_start = time.monotonic()

    def record_step(
        self,
        step_name: str,
        execution_path: ExecutionPath,
        retry_attempts: int,
        success: bool,
        selector_diff: dict | None = None,
        error: str | None = None,
    ):
        """记录一个步骤的结果。需在 step_start() 之后调用。"""
        duration_ms = int((time.monotonic() - (self._step_start or time.monotonic())) * 1000)
        self._steps.append(StepResult(
            step_name=step_name,
            execution_path=execution_path,
            retry_attempts=retry_attempts,
            success=success,
            duration_ms=duration_ms,
            selector_diff=selector_diff,
            error=error,
        ))
        self._step_start = None

    def save(self, overall_success: bool) -> Path:
        """计算汇总指标并写入 JSON 文件，返回文件路径。"""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        finished_at = datetime.now(timezone.utc).isoformat()
        total_steps = len(self._steps)
        successful_steps = sum(1 for s in self._steps if s.success)

        retry_dist: dict[str, int] = {}
        for s in self._steps:
            key = str(s.retry_attempts)
            retry_dist[key] = retry_dist.get(key, 0) + 1

        path_dist: dict[str, int] = {}
        for s in self._steps:
            path_dist[s.execution_path] = path_dist.get(s.execution_path, 0) + 1

        run = BenchmarkRun(
            adapter_id=self.adapter_id,
            run_id=self._run_id,
            started_at=self._started_at,
            finished_at=finished_at,
            steps=self._steps,
            overall_success=overall_success,
            success_rate=successful_steps / total_steps if total_steps > 0 else 0.0,
            retry_attempts_distribution=retry_dist,
            execution_path_distribution=path_dist,
            total_duration_ms=sum(s.duration_ms for s in self._steps),
        )

        filename = f"{self.adapter_id}_{self._run_id}.json"
        output_path = RESULTS_DIR / filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(asdict(run), f, ensure_ascii=False, indent=2)

        return output_path

    def print_summary(self, output_path: Path):
        """在 verify 脚本结束时打印摘要。"""
        total = len(self._steps)
        succeeded = sum(1 for s in self._steps if s.success)
        fallbacks = [s for s in self._steps if s.execution_path == "visual_fallback"]

        print("\n" + "=" * 60)
        print(f"  Benchmark 摘要 — {self.adapter_id}")
        print("=" * 60)
        print(f"  步骤总数:     {total}")
        pct = f"{succeeded/total*100:.0f}%" if total else "N/A"
        print(f"  成功步骤:     {succeeded} / {total}  ({pct})")
        print(f"  Fallback 次数: {len(fallbacks)}")

        retry_dist: dict[int, int] = {}
        for s in self._steps:
            retry_dist[s.retry_attempts] = retry_dist.get(s.retry_attempts, 0) + 1
        print(f"  Retry 分布:   {dict(sorted(retry_dist.items(), key=lambda x: (x[0] is None, x[0])))}")

        path_dist: dict[str, int] = {}
        for s in self._steps:
            path_dist[s.execution_path] = path_dist.get(s.execution_path, 0) + 1
        print(f"  执行路径分布: {path_dist}")

        if fallbacks:
            print("\n  [!] Fallback 详情：")
            for s in fallbacks:
                if s.selector_diff:
                    print(f"    - {s.step_name}: 失效 selector = {s.selector_diff.get('failed_selector')}")
                else:
                    print(f"    - {s.step_name}: {s.error}")

        print(f"\n  结果文件: {output_path}")
        print("=" * 60)
