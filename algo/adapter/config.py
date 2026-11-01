"""Model configuration shared by inference, evaluation and the registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable

TRANSUNET_COMMIT = "02ef0010b36eb8328b5e689eadaf613602edf9b8"


@dataclass(frozen=True)
class ModelConfig:
    """Frozen inference configuration.

    Defaults mirror ``transunet/code/eval_postproc.py`` for the published
    TransUNet weights: 256x256 RGB, horizontal-flip TTA only, threshold 0.5,
    A1 post-processing with a 0.1% area gate.
    """

    size: int = 256
    in_ch: int = 3
    rgb: bool = True
    tta: bool = True
    scales: tuple[float, ...] = (1.0,)
    threshold: float = 0.5
    postproc: bool = True
    min_area: float = 0.001
    seed: int = 0
    transunet_commit: str = TRANSUNET_COMMIT

    def __post_init__(self) -> None:
        # Normalise JSON lists to tuples so the dataclass stays hashable/frozen.
        if not isinstance(self.scales, tuple):
            object.__setattr__(self, "scales", tuple(float(x) for x in self.scales))
        self.validate()

    def validate(self) -> None:
        if self.size <= 0:
            raise ValueError("size must be positive")
        if self.in_ch not in (1, 3):
            raise ValueError("in_ch must be 1 or 3")
        if self.rgb and self.in_ch != 3:
            raise ValueError("rgb=True requires in_ch=3")
        if not self.rgb and self.in_ch != 1:
            raise ValueError("rgb=False requires in_ch=1")
        if not self.scales:
            raise ValueError("scales must not be empty")
        if any(float(s) <= 0 for s in self.scales):
            raise ValueError("scales must be positive")
        # TransUNet uses fixed positional embeddings; multi-scale TTA breaks them.
        if any(abs(float(s) - 1.0) > 1e-9 for s in self.scales):
            raise ValueError(
                "only scales=[1.0] is allowed: TransUNet uses fixed positional "
                "embeddings and multi-scale TTA is invalid"
            )
        if not 0.0 < float(self.threshold) < 1.0:
            raise ValueError("threshold must be in (0, 1)")
        if not 0.0 <= float(self.min_area) < 1.0:
            raise ValueError("min_area must be in [0, 1)")
        if int(self.seed) < 0:
            raise ValueError("seed must be non-negative")

    def with_overrides(
        self,
        *,
        tta: bool | None = None,
        threshold: float | None = None,
        postproc: bool | None = None,
        min_area: float | None = None,
    ) -> "ModelConfig":
        return replace(
            self,
            tta=self.tta if tta is None else bool(tta),
            threshold=self.threshold if threshold is None else float(threshold),
            postproc=self.postproc if postproc is None else bool(postproc),
            min_area=self.min_area if min_area is None else float(min_area),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ModelConfig":
        data = data or {}
        allowed: Iterable[str] = (
            "size",
            "in_ch",
            "rgb",
            "tta",
            "scales",
            "threshold",
            "postproc",
            "min_area",
            "seed",
            "transunet_commit",
        )
        kwargs = {k: data[k] for k in allowed if k in data}
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scales"] = [float(x) for x in self.scales]
        return payload
