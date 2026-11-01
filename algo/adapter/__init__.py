"""Algorithm adapter: registry, predictor, metrics and RLE codec."""

from .config import ModelConfig, TRANSUNET_COMMIT
from .errors import (
    AlgoError,
    EvaluationError,
    ImageDecodeError,
    ModelNotFoundError,
    WeightIntegrityError,
)
from .registry import ModelRegistry, ModelVersion, sha256_file
from .rle import rle_area, rle_decode, rle_encode

__all__ = [
    "AlgoError",
    "EvaluationError",
    "ImageDecodeError",
    "ModelConfig",
    "ModelNotFoundError",
    "ModelRegistry",
    "ModelVersion",
    "TRANSUNET_COMMIT",
    "WeightIntegrityError",
    "rle_area",
    "rle_decode",
    "rle_encode",
    "sha256_file",
]
