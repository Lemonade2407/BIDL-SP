"""BIDL-SP algorithm service package (Member B).

This package wraps the existing ``transunet/`` reproduction package without
modifying it. It provides:

- model registry with weight identity checks
- single-image inference (preprocess / TTA / A1 post-processing / RLE)
- offline evaluation through the frozen ``eval_postproc.py`` protocol
- Celery task entrypoints and a small CLI

Run ``python -m algo.cli --help`` for usage.
"""

__version__ = "1.0.0"
