"""Reproducible real-data acceptance. Run with an isolated, migrated database.

python backend/scripts/verify_busi.py --data /path/to/Dataset_BUSI_with_GT --output docs/evidence/busi.json
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from app import models as m
from app.cli import main as cli_main
from app.config import ROOT
from app.data_service import freeze
from app.db import SessionLocal
from app.storage import storage
from sqlalchemy import select


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.argv = ["cli", "import-directory", str(args.data)]
    cli_main()
    with SessionLocal() as db:
        dataset = db.scalar(select(m.Dataset).where(m.Dataset.name == "BUSI"))
        images = list(db.scalars(select(m.Image).where(m.Image.dataset_id == dataset.id)))
        user = db.scalar(select(m.User).where(m.User.username == "admin"))
        version = m.DatasetVersion(
            dataset_id=dataset.id,
            version="acceptance-v1",
            split_seed=0,
            ratios={"train": 0.7, "val": 0.15, "test": 0.15},
            filter={},
            created_by=user.id,
        )
        db.add(version)
        db.flush()
        freeze(db, version, user, None)
        db.commit()
        manifest = json.loads(storage.read("bidlsp-dataset", version.manifest_key))
        reference = json.loads((ROOT / "transunet/data/splits/busi_seed0.json").read_text())
        present = {i.relative_path for i in images}
        members_match = all(
            sorted(i["relative_path"] for i in manifest["items"] if i["split"] == split)
            == sorted(n for n in reference[split] if n in present)
            for split in ("train", "val", "test")
        )
        first = db.scalar(select(m.ImportJob).order_by(m.ImportJob.created_at.desc()))
        report = {
            "dataset": "BUSI",
            "image_count": len(images),
            "by_class": dict(Counter(i.class_label for i in images)),
            "import": {
                "success": first.success,
                "failed": first.failed,
                "duplicate": first.duplicate,
                "report": first.report,
            },
            "split_counts": version.counts,
            "effective_seed": manifest["effective_seed"],
            "frozen_members_match_reference": members_match,
            "sha256_unique": len({i.sha256 for i in images}) == len(images),
            "excluded_duplicates": manifest.get("excluded_duplicates", []),
            "original_780_requirement_met": len(images) == 780,
        }
    # Import the exact same dataset again; verify deduplication through the real importer.
    cli_main()
    with SessionLocal() as db:
        repeat = db.scalar(select(m.ImportJob).order_by(m.ImportJob.created_at.desc()))
        report["repeat_import"] = {
            "success": repeat.success,
            "duplicate": repeat.duplicate,
            "failed": repeat.failed,
        }
    # Real BUSI contains one identical image with conflicting labels, both in train.
    passed = report["image_count"] == 779 and report["by_class"] == {
        "benign": 437,
        "malignant": 209,
        "normal": 133,
    }
    passed = passed and report["split_counts"] == {"train": 545, "val": 118, "test": 116} and members_match
    passed = (
        passed
        and report["import"]["failed"] == 0
        and report["repeat_import"] == {"success": 0, "duplicate": 780, "failed": 0}
    )
    report["result"] = "PASS_WITH_DATA_QUALITY_EXCEPTION" if passed else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
