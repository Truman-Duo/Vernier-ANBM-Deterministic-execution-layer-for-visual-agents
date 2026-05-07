import json

import scripts.benchmark.recorder as recorder_module
from scripts.benchmark.recorder import BenchmarkRecorder


def test_recorder_saves_json_with_correct_fields(tmp_path):
    recorder_module.RESULTS_DIR = tmp_path / "results"
    recorder = BenchmarkRecorder(adapter_id="test_adapter")

    recorder.step_start()
    recorder.record_step(
        step_name="step_one",
        execution_path="deterministic",
        retry_attempts=1,
        success=True,
    )
    recorder.step_start()
    recorder.record_step(
        step_name="step_two",
        execution_path="deterministic",
        retry_attempts=1,
        success=True,
    )
    recorder.step_start()
    recorder.record_step(
        step_name="step_three",
        execution_path="visual_fallback",
        retry_attempts=3,
        success=False,
        selector_diff={"failed_selector": ".broken"},
    )

    output_path = recorder.save(overall_success=False)

    assert output_path.exists()
    with open(output_path) as f:
        data = json.load(f)

    assert data["adapter_id"] == "test_adapter"
    assert data["overall_success"] is False
    assert data["success_rate"] == 2 / 3
    assert data["execution_path_distribution"] == {"deterministic": 2, "visual_fallback": 1}
    assert data["retry_attempts_distribution"] == {"1": 2, "3": 1}
    assert data["total_duration_ms"] >= 0


def test_recorder_selector_diff_captured(tmp_path):
    recorder_module.RESULTS_DIR = tmp_path / "results"
    recorder = BenchmarkRecorder(adapter_id="test_adapter")

    recorder.step_start()
    recorder.record_step(
        step_name="fallback_step",
        execution_path="visual_fallback",
        retry_attempts=2,
        success=False,
        selector_diff={"failed_selector": ".broken"},
    )

    output_path = recorder.save(overall_success=False)
    with open(output_path) as f:
        data = json.load(f)

    step = data["steps"][0]
    assert step["selector_diff"]["failed_selector"] == ".broken"


def test_recorder_empty_steps(tmp_path):
    recorder_module.RESULTS_DIR = tmp_path / "results"
    recorder = BenchmarkRecorder(adapter_id="empty_test")

    output_path = recorder.save(overall_success=False)

    assert output_path.exists()
    with open(output_path) as f:
        data = json.load(f)

    assert data["success_rate"] == 0.0
    assert len(data["steps"]) == 0
    assert data["overall_success"] is False
