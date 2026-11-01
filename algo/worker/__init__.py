"""Worker package: inference/evaluation task entrypoints."""

from .eval_worker import (
    EvaluationReport,
    build_eval_command,
    compare_with_registry,
    run_evaluation,
    summarize_eval_data,
    verify_metrics,
)
from .tasks import execute_evaluation, execute_inference

__all__ = [
    "EvaluationReport",
    "build_eval_command",
    "compare_with_registry",
    "execute_evaluation",
    "execute_inference",
    "run_evaluation",
    "summarize_eval_data",
    "verify_metrics",
]
