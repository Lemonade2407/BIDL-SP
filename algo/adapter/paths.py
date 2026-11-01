"""Repository paths and import bootstrapping.

The reproduction package lives in ``<repo>/transunet`` and is treated as
read-only. We add ``transunet/code`` to ``sys.path`` and point
``TRANSUNET_ROOT`` / ``BUSI_ROOT`` at the expected locations, so the existing
``models.py`` and ``busi_common.py`` work unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ALGO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ALGO_DIR.parent
TRANSUNET_DIR = Path(
    os.environ.get("BIDLSP_TRANSUNET_DIR", REPO_ROOT / "transunet")
).resolve()
TRANSUNET_CODE_DIR = TRANSUNET_DIR / "code"
TRANSUNET_OFFICIAL_DIR = Path(
    os.environ.get("TRANSUNET_ROOT", TRANSUNET_DIR / "TransUNet")
).resolve()
MODEL_REGISTRY_PATH = Path(
    os.environ.get("BIDLSP_MODEL_REGISTRY", ALGO_DIR / "models" / "registry.json")
).resolve()
OUTPUT_DIR = Path(
    os.environ.get("BIDLSP_ALGO_OUTPUT_DIR", ALGO_DIR / "outputs")
).resolve()


def ensure_transunet_importable() -> None:
    """Make ``transunet/code`` importable without modifying that package."""
    os.environ.setdefault("TRANSUNET_ROOT", str(TRANSUNET_OFFICIAL_DIR))
    os.environ.setdefault("BUSI_ROOT", str(TRANSUNET_DIR))
    code = str(TRANSUNET_CODE_DIR)
    if code not in sys.path:
        sys.path.insert(0, code)
