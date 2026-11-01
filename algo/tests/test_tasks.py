"""Worker task contract tests that do not require loading the model."""
from __future__ import annotations

from algo.worker.tasks import execute_inference


def test_missing_image_returns_structured_failure() -> None:
    result = execute_inference(
        {
            "task_id": "test-task",
            "image_path": "does/not/exist.png",
            "model_version": "s256rgb-seed0",
        }
    )
    assert result["task_id"] == "test-task"
    assert result["status"] == "failed"
    assert result["error"]["code"] == "INFERENCE_FAILED"


def test_missing_image_path_returns_failure() -> None:
    result = execute_inference({"task_id": "test-task-2"})
    assert result["status"] == "failed"
    assert "image_path" in result["error"]["message"]
