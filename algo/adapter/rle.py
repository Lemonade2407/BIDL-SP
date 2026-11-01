"""Binary mask run-length encoding (COCO-style, column-major).

The API contract stores ``{"size": [h, w], "counts": [...]}``. COCO's RLE is
column-major (Fortran order); we keep that convention so masks can be exchanged
with standard tooling later.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def rle_encode(mask: np.ndarray, *, order: str = "F") -> dict[str, Any]:
    """Encode a 2-D binary mask to ``{"size": [h, w], "counts": [...]}``."""
    arr = np.asarray(mask)
    if arr.ndim != 2:
        raise ValueError(f"mask must be 2-D, got shape {arr.shape}")
    h, w = arr.shape
    flat = (arr != 0).astype(np.uint8).flatten(order=order)

    if flat.size == 0:
        return {"size": [int(h), int(w)], "counts": []}

    changes = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    starts = np.concatenate(([0], changes))
    lengths = np.diff(np.concatenate((starts, [flat.size]))).astype(np.int64)

    counts: list[int] = []
    if flat[0] == 1:  # RLE always starts with a run of zeros
        counts.append(0)
    counts.extend(int(x) for x in lengths)
    return {"size": [int(h), int(w)], "counts": counts}


def rle_decode(rle: dict[str, Any], *, order: str = "F") -> np.ndarray:
    """Decode ``{"size": [h, w], "counts": [...]}`` to a boolean mask."""
    try:
        h, w = (int(x) for x in rle["size"])
        counts = rle["counts"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid RLE payload") from exc

    total = h * w
    counts = [int(c) for c in counts]
    if any(c < 0 for c in counts):
        raise ValueError("RLE counts must be non-negative")
    if sum(counts) != total:
        raise ValueError("RLE counts do not sum to H*W")

    flat = np.zeros(total, dtype=bool)
    pos = 0
    value = False
    for run in counts:
        if run and value:
            flat[pos : pos + run] = True
        pos += run
        value = not value
    return flat.reshape((h, w), order=order)


def rle_area(rle: dict[str, Any]) -> int:
    """Number of foreground pixels in an RLE payload."""
    counts = [int(c) for c in rle.get("counts", [])]
    return int(sum(counts[1::2]))
