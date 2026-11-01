"""TransUNet inference adapter.

The preprocessing / TTA / post-processing path is deliberately identical to
``transunet/code/eval_postproc.py``:

- RGB, resize to 256x256 with bilinear interpolation
- per-channel standardisation
- optional horizontal-flip TTA only (no multi-scale; fixed positional embeddings)
- foreground probability resized back to the original resolution
- threshold, then A1 post-processing (fill holes + largest component + area gate)

The adapter adds API-facing pieces: RLE encoding, quality flags, timing and
artifact saving (mask, raw mask, overlay, result JSON).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .config import ModelConfig
from .errors import AlgoError, ImageDecodeError, WeightIntegrityError
from .paths import ensure_transunet_importable
from .registry import ModelRegistry, ModelVersion, sha256_file
from .rle import rle_encode

# COCO-style RLE is column-major; this comment is the single reminder if a
# frontend implementation ever needs to decode it.
_RLE_ORDER = "F"


def _resolve_device(requested: str | Any, torch_module: Any) -> Any:
    if isinstance(requested, torch_module.device):
        if requested.type == "cuda" and not torch_module.cuda.is_available():
            raise AlgoError("CUDA requested but not available", code="MODEL_UNAVAILABLE")
        return requested
    value = str(requested or "auto").lower()
    if value == "auto":
        value = "cuda" if torch_module.cuda.is_available() else "cpu"
    if value.startswith("cuda") and not torch_module.cuda.is_available():
        raise AlgoError("CUDA requested but not available", code="MODEL_UNAVAILABLE")
    return torch_module.device(value)


def _as_rgb_image(image: Any) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB").copy()
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise ImageDecodeError(f"image not found: {path}")
        try:
            with Image.open(path) as im:
                return im.convert("RGB").copy()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageDecodeError(f"cannot decode image {path}: {exc}") from exc
    if isinstance(image, (bytes, bytearray)):
        try:
            with Image.open(BytesIO(bytes(image))) as im:
                return im.convert("RGB").copy()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageDecodeError(f"cannot decode image bytes: {exc}") from exc
    if isinstance(image, np.ndarray):
        arr = np.asarray(image)
        if arr.dtype == bool:
            arr = (arr.astype(np.uint8) * 255)
        try:
            return Image.fromarray(arr).convert("RGB")
        except (TypeError, ValueError) as exc:
            raise ImageDecodeError(f"cannot convert numpy image: {exc}") from exc
    raise ImageDecodeError(f"unsupported image type: {type(image)!r}")


@dataclass
class Prediction:
    model_id: str
    model_name: str
    model_version: str
    weights_sha256: str
    image_width: int
    image_height: int
    prob: np.ndarray = field(repr=False)
    mask_raw: np.ndarray = field(repr=False)
    mask: np.ndarray = field(repr=False)
    original_image: Image.Image = field(repr=False, compare=False)
    prob_mean: float = 0.0
    lesion_area_ratio: float = 0.0
    quality_flags: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    threshold: float = 0.5
    tta: bool = True
    postproc: bool = True
    min_area: float = 0.001

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe result matching ``接口规范.md`` 5.5.5."""
        return {
            "model": {
                "id": self.model_id,
                "name": self.model_name,
                "version": self.model_version,
                "weights_sha256": self.weights_sha256,
            },
            "image": {"width": self.image_width, "height": self.image_height},
            "params": {
                "tta": self.tta,
                "threshold": self.threshold,
                "postproc": self.postproc,
                "min_area": self.min_area,
            },
            "result": {
                "mask_rle": rle_encode(self.mask, order=_RLE_ORDER),
                "prob_mean": round(float(self.prob_mean), 5),
                "lesion_area_ratio": round(float(self.lesion_area_ratio), 6),
                "quality_flags": list(self.quality_flags),
                "elapsed_ms": int(self.elapsed_ms),
            },
        }

    def _overlay(self) -> Image.Image:
        base = self.original_image.convert("RGB")
        arr = np.asarray(base, dtype=np.float32)
        mask = self.mask.astype(bool)
        if mask.any():
            arr[mask] = arr[mask] * 0.55 + np.array([255.0, 32.0, 32.0], dtype=np.float32) * 0.45
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    def save(
        self,
        out_dir: str | Path,
        *,
        save_prob: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write mask / raw mask / overlay / result.json and return the payload."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        mask_path = out / "mask.png"
        mask_raw_path = out / "mask_raw.png"
        overlay_path = out / "overlay.png"
        result_path = out / "result.json"

        Image.fromarray((self.mask.astype(np.uint8) * 255)).save(mask_path)
        Image.fromarray((self.mask_raw.astype(np.uint8) * 255)).save(mask_raw_path)
        self._overlay().save(overlay_path)
        if save_prob:
            Image.fromarray(np.clip(self.prob * 255.0, 0, 255).astype(np.uint8)).save(
                out / "prob.png"
            )

        payload = self.to_dict()
        if metadata:
            payload.update(metadata)
        payload["result"]["mask_path"] = str(mask_path.resolve())
        payload["result"]["mask_url"] = mask_path.resolve().as_uri()
        payload["artifacts"] = {
            "mask": str(mask_path.resolve()),
            "mask_raw": str(mask_raw_path.resolve()),
            "overlay": str(overlay_path.resolve()),
            "result": str(result_path.resolve()),
        }
        result_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload


class Predictor:
    """Load one model version and run single-image inference."""

    def __init__(self, model_version: ModelVersion, *, device: str = "auto") -> None:
        ensure_transunet_importable()
        import torch  # local import keeps non-torch helpers importable

        self._torch = torch
        self.model_version = model_version
        self.config: ModelConfig = model_version.config
        self.device = _resolve_device(device, torch)

        if not model_version.weights_path.exists():
            raise AlgoError(
                f"weights not found: {model_version.weights_path}",
                code="MODEL_UNAVAILABLE",
            )
        if not os.environ.get("BIDLSP_SKIP_WEIGHT_VERIFY"):
            actual = sha256_file(model_version.weights_path)
            if actual != model_version.weights_sha256:
                raise WeightIntegrityError(
                    "weights sha256 mismatch",
                    details=[
                        {
                            "version": model_version.version,
                            "expected": model_version.weights_sha256,
                            "actual": actual,
                        }
                    ],
                )

        from models import build_model  # provided by transunet/code via sys.path

        self.model = build_model(
            model_version.name,
            in_ch=self.config.in_ch,
            n_cls=2,
            size=self.config.size,
        )
        raw = torch.load(str(model_version.weights_path), map_location="cpu")
        state_dict = raw.get("state_dict", raw) if isinstance(raw, dict) else raw
        missing, unexpected = self.model.load_state_dict(state_dict, strict=False)
        if missing or unexpected:
            raise WeightIntegrityError(
                "state_dict keys do not match the TransUNet definition",
                details=[
                    {"missing": list(missing)[:10], "unexpected": list(unexpected)[:10]}
                ],
            )

        self.model.to(self.device)
        self.model.eval()
        if self.device.type == "cuda":
            torch.backends.cudnn.benchmark = True
        self._lock = threading.Lock()

    @property
    def _softmax(self) -> Any:
        return self._torch.softmax

    def _forward(self, x: Any) -> Any:
        out = self.model(x)
        if isinstance(out, (list, tuple)):
            out = out[-1]
        return out

    def _preprocess(self, image: Image.Image, cfg: ModelConfig) -> Any:
        im = image.convert("RGB").resize((cfg.size, cfg.size), Image.Resampling.BILINEAR)
        arr = np.asarray(im, dtype=np.float32)
        if cfg.in_ch == 1:
            arr = arr.mean(axis=2, keepdims=True)
        arr = (arr - arr.mean(axis=(0, 1), keepdims=True)) / (
            arr.std(axis=(0, 1), keepdims=True) + 1e-8
        )
        x = self._torch.from_numpy(arr).permute(2, 0, 1)[None].contiguous()
        return x.to(self.device)

    def _prob_model_res(self, x: Any, cfg: ModelConfig) -> Any:
        """Foreground probability at model resolution; TTA averages at this resolution."""
        torch = self._torch
        F = torch.nn.functional
        if not cfg.tta:
            return self._softmax(self._forward(x), dim=1)[:, 1]

        acc = None
        n = 0
        for scale in cfg.scales:
            if abs(float(scale) - 1.0) > 1e-9:
                xs = F.interpolate(
                    x, scale_factor=float(scale), mode="bilinear", align_corners=False
                )
            else:
                xs = x
            for flip in (False, True):
                xin = torch.flip(xs, dims=[3]) if flip else xs
                prob = self._softmax(self._forward(xin), dim=1)[:, 1]
                if flip:
                    prob = torch.flip(prob, dims=[2])
                prob = F.interpolate(
                    prob[:, None],
                    size=(x.shape[-2], x.shape[-1]),
                    mode="bilinear",
                    align_corners=False,
                )[:, 0]
                acc = prob if acc is None else acc + prob
                n += 1
        return acc / max(n, 1)

    def _quality_flags(
        self, mask_raw: np.ndarray, mask: np.ndarray, prob_mean: float
    ) -> list[str]:
        flags: list[str] = []
        if not mask.any():
            flags.append("EMPTY_MASK")
        if float(mask.mean()) > 0.6:
            flags.append("AREA_TOO_LARGE")
        if float(prob_mean) < 0.6:
            flags.append("LOW_CONFIDENCE")
        try:
            from scipy import ndimage

            _, n = ndimage.label(mask_raw, structure=np.ones((3, 3), dtype=np.uint8))
            if int(n) > 1:
                flags.append("MULTI_LESION")
        except Exception:
            # Quality flags are advisory; never fail inference for this.
            pass
        return flags

    def predict(
        self,
        image: Any,
        *,
        tta: bool | None = None,
        threshold: float | None = None,
        postproc: bool | None = None,
        min_area: float | None = None,
    ) -> Prediction:
        cfg = self.config.with_overrides(
            tta=tta, threshold=threshold, postproc=postproc, min_area=min_area
        )
        original = _as_rgb_image(image)
        width, height = original.size
        started = time.perf_counter()

        x = self._preprocess(original, cfg)
        with self._torch.no_grad():
            with self._lock:
                prob = self._prob_model_res(x, cfg)
                prob = self._torch.nn.functional.interpolate(
                    prob[:, None],
                    size=(height, width),
                    mode="bilinear",
                    align_corners=False,
                )[:, 0]
                prob_np = prob[0].detach().cpu().numpy()

        mask_raw = prob_np > float(cfg.threshold)
        if cfg.postproc:
            from busi_common import postprocess_mask

            mask = postprocess_mask(mask_raw, float(cfg.min_area))
        else:
            mask = mask_raw
        mask = np.asarray(mask, dtype=bool)

        prob_mean = float(prob_np.mean())
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return Prediction(
            model_id=self.model_version.id,
            model_name=self.model_version.name,
            model_version=self.model_version.version,
            weights_sha256=self.model_version.weights_sha256,
            image_width=width,
            image_height=height,
            prob=prob_np,
            mask_raw=mask_raw,
            mask=mask,
            original_image=original,
            prob_mean=prob_mean,
            lesion_area_ratio=float(mask.mean()),
            quality_flags=self._quality_flags(mask_raw, mask, prob_mean),
            elapsed_ms=elapsed_ms,
            threshold=float(cfg.threshold),
            tta=bool(cfg.tta),
            postproc=bool(cfg.postproc),
            min_area=float(cfg.min_area),
        )

    def predict_path(self, path: str | Path, **kwargs: Any) -> Prediction:
        return self.predict(path, **kwargs)


_CACHE: "OrderedDict[tuple[str, str], Predictor]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_MAX_CACHE = 2


def get_predictor(
    key: str | ModelVersion | None = None,
    *,
    device: str = "auto",
    registry: ModelRegistry | None = None,
) -> Predictor:
    """Return a cached predictor for a model version (id / version / name/version)."""
    import torch

    reg = registry or ModelRegistry()
    model_version = reg.get(key) if not isinstance(key, ModelVersion) else key
    resolved = _resolve_device(device, torch)
    cache_key = (model_version.id, str(resolved))

    with _CACHE_LOCK:
        if cache_key in _CACHE:
            _CACHE.move_to_end(cache_key)
            return _CACHE[cache_key]
        predictor = Predictor(model_version, device=str(resolved))
        _CACHE[cache_key] = predictor
        while len(_CACHE) > _MAX_CACHE:
            _CACHE.popitem(last=False)
        return predictor


def clear_model_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
