"""Tests for the RLE codec."""
from __future__ import annotations

import numpy as np
import pytest

from algo.adapter.rle import rle_area, rle_decode, rle_encode


@pytest.mark.parametrize("shape", [(1, 1), (3, 7), (64, 64), (421, 563)])
def test_roundtrip_random(shape: tuple[int, int]) -> None:
    rng = np.random.default_rng(0)
    mask = rng.random(shape) > 0.7
    rle = rle_encode(mask)
    assert rle["size"] == [shape[0], shape[1]]
    assert np.array_equal(mask, rle_decode(rle))
    assert rle_area(rle) == int(mask.sum())


def test_empty_and_full() -> None:
    empty = np.zeros((4, 5), dtype=bool)
    full = np.ones((4, 5), dtype=bool)
    assert np.array_equal(rle_decode(rle_encode(empty)), empty)
    assert np.array_equal(rle_decode(rle_encode(full)), full)
    assert rle_area(rle_encode(empty)) == 0
    assert rle_area(rle_encode(full)) == 20


def test_invalid_counts() -> None:
    with pytest.raises(ValueError):
        rle_decode({"size": [2, 2], "counts": [3]})
    with pytest.raises(ValueError):
        rle_decode({"size": [2, 2], "counts": [-1, 5]})
