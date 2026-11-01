"""Local model registry backed by ``algo/models/registry.json``.

The platform's production registry lives in PostgreSQL (``model_version``).
Until the backend is implemented, this JSON file is the stand-in used by the
algorithm service, CLI and worker. It carries the same identity fields:
weights path, sha256, inference config and recorded metrics.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .errors import ModelNotFoundError, WeightIntegrityError
from .paths import ALGO_DIR, MODEL_REGISTRY_PATH, REPO_ROOT, TRANSUNET_DIR


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_weights_path(raw: str | Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    for base in (REPO_ROOT, TRANSUNET_DIR, ALGO_DIR):
        candidate = (base / path).resolve()
        if candidate.exists():
            return candidate
    return (REPO_ROOT / path).resolve()


_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ModelVersion:
    id: str
    name: str
    version: str
    weights_path: Path
    weights_sha256: str
    config: ModelConfig
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelVersion":
        missing = [k for k in ("id", "name", "version", "weights_path", "weights_sha256") if k not in data]
        if missing:
            raise ValueError(f"model entry missing fields: {missing}")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            version=str(data["version"]),
            weights_path=_resolve_weights_path(data["weights_path"]),
            weights_sha256=str(data["weights_sha256"]).lower(),
            config=ModelConfig.from_dict(data.get("config")),
            metrics=dict(data.get("metrics") or {}),
            status=str(data.get("status", "candidate")),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "weights_path": str(self.weights_path),
            "weights_sha256": self.weights_sha256,
            "config": self.config.to_dict(),
            "metrics": self.metrics,
            "status": self.status,
            "notes": self.notes,
        }

    @property
    def metric_dice(self) -> float | None:
        try:
            return float(self.metrics["A2+A1"]["dice"])
        except (KeyError, TypeError, ValueError):
            return None


class ModelRegistry:
    """Read-only registry with optional weight verification."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or MODEL_REGISTRY_PATH).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"model registry not found: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            entries = raw
        else:
            entries = raw.get("models", [])
        self._models = [ModelVersion.from_dict(item) for item in entries]
        if not self._models:
            raise ValueError(f"model registry is empty: {self.path}")
        self._by_id = {m.id: m for m in self._models}
        duplicates = len(self._by_id) != len(self._models)
        if duplicates:
            raise ValueError("duplicate model id in registry")

    def all(self) -> list[ModelVersion]:
        return list(self._models)

    def get(self, key: str | None) -> ModelVersion:
        if not key or key == "active":
            return self.active()
        if key in self._by_id:
            return self._by_id[key]
        matches = [
            m
            for m in self._models
            if key in (m.version, f"{m.name}/{m.version}")
        ]
        if not matches:
            raise ModelNotFoundError(
                f"model version not found: {key}",
                details=[{"available": [m.version for m in self._models]}],
            )
        if len(matches) > 1:
            raise ModelNotFoundError(
                f"ambiguous model version: {key}",
                details=[{"matches": [m.id for m in matches]}],
            )
        return matches[0]

    def active(self, name: str | None = None) -> ModelVersion:
        active = [m for m in self._models if m.status == "active" and (name is None or m.name == name)]
        if not active:
            raise ModelNotFoundError(
                "no active model version",
                details=[{"name": name, "available": [m.version for m in self._models]}],
            )
        if len(active) > 1:
            raise ValueError("multiple active model versions; registry is invalid")
        return active[0]

    def verify_weight(self, key: str, *, recompute: bool = True) -> dict[str, Any]:
        model = self.get(key)
        payload: dict[str, Any] = {
            "id": model.id,
            "version": model.version,
            "path": str(model.weights_path),
            "expected": model.weights_sha256,
            "actual": None,
            "status": "SKIPPED",
        }
        if not model.weights_path.exists():
            payload["status"] = "MISSING"
            return payload
        if not recompute:
            return payload
        actual = sha256_file(model.weights_path)
        payload["actual"] = actual
        payload["status"] = "PASS" if actual == model.weights_sha256 else "FAIL"
        return payload

    def verify_all(self, *, recompute: bool = True) -> list[dict[str, Any]]:
        return [self.verify_weight(m.id, recompute=recompute) for m in self._models]

    def require_weight(self, key: str) -> ModelVersion:
        model = self.get(key)
        check = self.verify_weight(model.id)
        if check["status"] != "PASS":
            raise WeightIntegrityError(
                f"weight verification failed for {model.version}: {check['status']}",
                details=[check],
            )
        return model

    def activate(self, key: str) -> ModelVersion:
        """Activate one version and archive the previous active one (rollback).

        This is the local-JSON stand-in for ``POST /model-versions/{id}/activate``
        until the backend's PostgreSQL registry is available. The file is
        rewritten atomically so a crash cannot leave a half-written registry.
        """
        target = self.get(key)
        with _WRITE_LOCK:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                entries = raw.get("models", [])
            else:
                entries = raw

            found = False
            for item in entries:
                if item.get("id") == target.id:
                    item["status"] = "active"
                    found = True
                elif item.get("status") == "active":
                    item["status"] = "archived"
            if not found:
                raise ModelNotFoundError(f"model version not found: {key}")

            payload = raw if isinstance(raw, dict) else entries
            tmp_path = self.path.with_name(self.path.name + ".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_path, self.path)

            self._models = [ModelVersion.from_dict(item) for item in entries]
            self._by_id = {m.id: m for m in self._models}
            return next(m for m in self._models if m.id == target.id)
