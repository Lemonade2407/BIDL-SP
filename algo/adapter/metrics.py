"""Metric helpers reusing the frozen BUSI protocol.

All metric definitions come from ``transunet/code/busi_common.py`` and
``train_supervised.aggregate``. Duplicating them here would risk a different
evaluation口径, so these functions are thin wrappers only.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .paths import ensure_transunet_importable


def dice_binary(pred: np.ndarray, gt: np.ndarray) -> float:
    ensure_transunet_importable()
    from busi_common import dice_binary as _dice

    return float(_dice(pred, gt))


def iou_binary(pred: np.ndarray, gt: np.ndarray) -> float:
    ensure_transunet_importable()
    from busi_common import iou_binary as _iou

    return float(_iou(pred, gt))


def per_image_metrics(pred: np.ndarray, gt: np.ndarray) -> dict[str, Any]:
    ensure_transunet_importable()
    from busi_common import per_image_metrics as _metrics

    return dict(_metrics(pred, gt))


def aggregate(per_image: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_transunet_importable()
    from train_supervised import aggregate as _aggregate

    return dict(_aggregate(per_image))


def load_reference_mask(item: dict[str, Any]) -> np.ndarray:
    """Load the OR-ed reference mask at original resolution for a BUSI item."""
    ensure_transunet_importable()
    from busi_common import load_mask

    return np.asarray(load_mask(item), dtype=bool)


def load_busi_index() -> list[dict[str, Any]]:
    ensure_transunet_importable()
    from busi_common import build_index

    return list(build_index())
