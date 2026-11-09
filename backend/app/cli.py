"""Administrator commands; demo accounts use a fixed password, production can rotate later."""

import argparse
import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, update

from . import models as m
from .common import audit, get, serialize
from .config import DEMO_ADMIN_USERNAME, DEMO_PASSWORD, ROOT, settings
from .data_service import import_archive
from .db import SessionLocal, uid
from .reports import DEFAULT_TEMPLATE, VARIABLES
from .security import hash_password, verify_password
from .storage import storage


def seed_admin(db, password, demo=False):
    if len(password) < 12:
        raise ValueError("管理员/演示密码至少 12 字符")
    roles = ["admin", "data_engineer", "annotator", "screener", "reviewer"] if demo else [DEMO_ADMIN_USERNAME]
    for role in roles:
        obj = db.scalar(select(m.User).where(m.User.username == role))
        if obj is None:
            obj = m.User(
                username=role, display_name=role, roles=[role], password_hash=hash_password(password)
            )
            db.add(obj)
            db.flush()
            audit(db, obj, "user.seed", obj)
        else:
            # 演示环境固定密码，重复初始化时同步重置。
            obj.password_hash = hash_password(password)
            obj.status = "active"
            obj.token_version += 1
            db.flush()
    if not db.scalar(select(m.ReportTemplate.id).where(m.ReportTemplate.name == "默认科研筛查报告")):
        db.add(m.ReportTemplate(name="默认科研筛查报告", body=DEFAULT_TEMPLATE, variables=sorted(VARIABLES)))
    db.commit()


def preflight(db, production):
    checks = []

    def add(level, name, detail):
        checks.append({"level": level, "check": name, "detail": detail})

    admin = db.scalar(select(m.User).where(m.User.username == DEMO_ADMIN_USERNAME))
    if admin and verify_password(DEMO_PASSWORD, admin.password_hash):
        add("FAIL" if production else "WARN", "demo_admin_password", "管理员仍使用演示固定口令")
    else:
        add("PASS", "demo_admin_password", "管理员口令已更换")
    if settings.allow_registration:
        add("WARN", "registration", "自助注册开启；生产建议设置 ALLOW_REGISTRATION=false")
    else:
        add("PASS", "registration", "自助注册已关闭")
    if settings.storage_backend != "minio":
        add("WARN", "storage", "当前为本地存储，生产建议使用 MinIO")
    else:
        add("PASS", "storage", "使用 MinIO 对象存储")
    if settings.minio_secure:
        add("PASS", "minio_tls", "MinIO 使用 TLS")
    else:
        add("WARN", "minio_tls", "MinIO 未启用 TLS；生产应在网关终止 HTTPS")
    if any("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins):
        add("WARN", "cors", "CORS 含本机来源；生产请配置域名")
    else:
        add("PASS", "cors", "CORS 来源不含本机")
    if settings.public_api_url.startswith("http://"):
        add("WARN", "public_api_url", "PUBLIC_API_URL 未使用 HTTPS")
    else:
        add("PASS", "public_api_url", "PUBLIC_API_URL 使用 HTTPS")
    if settings.task_eager:
        add("WARN", "task_eager", "TASK_EAGER=true，异步任务将同步执行")
    else:
        add("PASS", "task_eager", "异步任务由 Worker 执行")
    if settings.jwt_hours > 8:
        add("WARN", "jwt", "JWT 有效期过长")
    else:
        add("PASS", "jwt", f"JWT 有效期 {settings.jwt_hours} 小时")
    if settings.pdf_font_path and not Path(settings.pdf_font_path).is_file():
        add("FAIL", "pdf_font", "PDF_FONT_PATH 指向的文件不存在")
    for row in checks:
        print(f"{row['level']:4} {row['check']:20} {row['detail']}")
    return 1 if any(row["level"] == "FAIL" for row in checks) else 0


def reset_demo_tasks(db, confirmed):
    open_annotations = db.scalar(
        select(func.count()).select_from(m.AnnotationTask).where(m.AnnotationTask.status != "approved")
    )
    open_screens = db.scalar(
        select(func.count()).select_from(m.ScreenTask).where(m.ScreenTask.status != "done")
    )
    if not confirmed:
        print("将重置：未完成的标注/筛查任务回到待处理队列，待审核标注回到草稿；已完成数据不变。")
        print("确认请追加 --yes。")
        return 0
    db.execute(
        update(m.Annotation)
        .where(m.Annotation.status == "pending")
        .values(status="draft", reviewed_by_id=None, reviewed_at=None)
    )
    db.execute(m.AnnotationAssignment.__table__.delete())
    db.execute(
        update(m.AnnotationTask)
        .where(m.AnnotationTask.status != "approved")
        .values(
            status="pending",
            assignee_id=None,
            annotation_id=None,
            claimed_at=None,
            finished_at=None,
            consistency=None,
        )
    )
    db.execute(
        update(m.ScreenTask)
        .where(m.ScreenTask.status != "done")
        .values(status="pending", assignee_id=None, claimed_at=None, finished_at=None)
    )
    db.execute(update(m.Study).where(m.Study.status == "in_progress").values(status="pending"))
    db.commit()
    print(f"已重置：标注任务 {open_annotations or 0}、筛查任务 {open_screens or 0}。")
    return 0


def export_audit(db, out, before):
    stmt = select(m.AuditLog)
    if before:
        stmt = stmt.where(m.AuditLog.created_at < datetime.fromisoformat(before))
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as stream:
        for row in db.scalars(stmt.order_by(m.AuditLog.id)):
            stream.write(json.dumps(serialize(row), ensure_ascii=False) + "\n")
            count += 1
    print(f"已导出 {count} 条审计记录到 {path}（审计表保持只追加，不做删除）。")
    return 0


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
    preflight_cmd = commands.add_parser("preflight")
    preflight_cmd.add_argument("--production", action="store_true")
    reset = commands.add_parser("reset-demo-tasks")
    reset.add_argument("--yes", action="store_true")
    export = commands.add_parser("export-audit")
    export.add_argument("--out", required=True, type=Path)
    export.add_argument("--before")
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
            seed_admin(db, DEMO_PASSWORD, demo=args.command == "seed-demo")
            print(f"Accounts initialized; fixed demo password is {DEMO_PASSWORD}.")
            return
        if args.command == "preflight":
            raise SystemExit(preflight(db, args.production))
        if args.command == "reset-demo-tasks":
            raise SystemExit(reset_demo_tasks(db, args.yes))
        if args.command == "export-audit":
            raise SystemExit(export_audit(db, args.out, args.before))
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
