"""Typed algorithm-service errors, mapped to the API error codes."""

from __future__ import annotations

from typing import Any


class AlgoError(Exception):
    """Base error carrying an API-facing code."""

    code = "ALGO_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or []

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ModelNotFoundError(AlgoError):
    code = "MODEL_UNAVAILABLE"


class WeightIntegrityError(AlgoError):
    code = "WEIGHT_INTEGRITY_ERROR"


class ImageDecodeError(AlgoError):
    code = "INFERENCE_FAILED"


class EvaluationError(AlgoError):
    code = "EVALUATION_FAILED"
