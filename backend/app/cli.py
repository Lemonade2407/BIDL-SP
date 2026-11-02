"""Administrator commands; passwords come from prompt/environment, never CLI args."""

import argparse
import getpass
import json
import os
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy import select

from . import models as m
from .common import audit, get
from .config import ROOT, settings
from .data_service import import_archive
from .db import SessionLocal, uid
from .reports import DEFAULT_TEMPLATE, VARIABLES
from .security import hash_password
from .storage import storage


def seed_admin(db, password, demo=False):
    if len(password) < 12:
        raise ValueError("管理员/演示密码至少 12 字符")
    for role in ["admin", "data_engineer", "annotator", "screener", "reviewer"] if demo else ["admin"]:
        if not db.scalar(select(m.User).where(m.User.username == role)):
            obj = m.User(
                username=role, display_name=role, roles=[role], password_hash=hash_password(password)
            )
            db.add(obj)
            db.flush()
            audit(db, obj, "user.seed", obj)
    if not db.scalar(select(m.ReportTemplate.id).where(m.ReportTemplate.name == "默认科研筛查报告")):
        db.add(m.ReportTemplate(name="默认科研筛查报告", body=DEFAULT_TEMPLATE, variables=sorted(VARIABLES)))
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-storage")
    commands.add_parser("seed-admin")
    commands.add_parser("seed-demo")
    models = commands.add_parser("seed-models")
    models.add_argument("--root", type=Path, default=ROOT)
    imports = commands.add_parser("import-directory")
    imports.add_argument("path", type=Path)
    imports.add_argument("--dataset", default="BUSI")
    commands.add_parser("dispatch-once")
    archive = commands.add_parser("archive-version")
    archive.add_argument("id")
    args = parser.parse_args()
    if args.command == "init-storage":
        storage.init()
        return
    if args.command == "dispatch-once":
        from .worker import dispatch, drain_eager

        (drain_eager if settings.task_eager else dispatch.run)()
        return
    with SessionLocal() as db:
        if args.command.startswith("seed-") and args.command != "seed-models":
            password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("初始化密码（至少12字符）：")
            seed_admin(db, password, demo=args.command == "seed-demo")
            print("Accounts initialized; existing passwords unchanged.")
            return
        user = db.scalar(select(m.User).where(m.User.username == "admin"))
        if not user:
            raise ValueError("先执行 seed-admin")
        if args.command == "archive-version":
            version = get(db, m.DatasetVersion, args.id, lock=True)
            if version.status != "frozen":
                raise ValueError("只能归档已冻结版本")
            version.status = "archived"
            audit(db, user, "dataset.archive", version)
            db.commit()
            print("Archived; manifest and frozen members are unchanged.")
            return
        if args.command == "seed-models":
            import hashlib

            registry = json.loads((ROOT / "algo/models/registry.json").read_text())
            model = db.scalar(select(m.Model).where(m.Model.name == "transunet"))
            if not model:
                model = m.Model(name="transunet")
                db.add(model)
                db.flush()
            for record in registry["models"]:
                if db.scalar(
                    select(m.ModelVersion.id).where(
                        m.ModelVersion.model_id == model.id, m.ModelVersion.version == record["version"]
                    )
                ):
                    continue
                path = args.root / record["weights_path"]
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != record["weights_sha256"]:
                        raise ValueError("权重 SHA256 不符：" + str(path))
                key = f"models/{record['weights_sha256']}.pth"
                storage.put_file("bidlsp-model", key, path)
                obj = m.ModelVersion(
                    model_id=model.id,
                    version=record["version"],
                    weights_key=key,
                    weights_sha256=record["weights_sha256"],
                    config=record["config"],
                    metrics=record["metrics"],
                    status=record["status"],
                    created_by=user.id,
                )
                db.add(obj)
                db.flush()
                audit(db, user, "model.version.seed", obj)
            db.commit()
            print("Model weights verified and registered.")
        elif args.command == "import-directory":
            root = args.path.resolve(strict=True)
            dataset = db.scalar(select(m.Dataset).where(m.Dataset.name == args.dataset))
            if not dataset:
                dataset = m.Dataset(name=args.dataset, created_by=user.id)
                db.add(dataset)
                db.flush()
            settings.work_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=settings.work_dir) as temp:
                archive_path = Path(temp) / "dataset.zip"
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(root.rglob("*.png")):
                        if path.is_symlink() or not path.resolve().is_relative_to(root):
                            raise ValueError("目录不能包含外部链接")
                        archive.write(path, path.relative_to(root).as_posix())
                id = uid()
                key = f"uploads/{id}.zip"
                storage.put_file("bidlsp-raw", key, archive_path, "application/zip")
            job = m.ImportJob(id=id, dataset_id=dataset.id, created_by=user.id, upload_key=key)
            db.add(job)
            db.flush()
            audit(db, user, "data.import", job)
            db.commit()
            import_archive(id)
            db.refresh(job)
            print(
                json.dumps(
                    {
                        "job_id": id,
                        "status": job.status,
                        "success": job.success,
                        "failed": job.failed,
                        "duplicate": job.duplicate,
                        "report": job.report,
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    main()
