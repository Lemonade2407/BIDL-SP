import hashlib
import io
import json
import random
import re
import stat
import zipfile
from pathlib import PurePosixPath

import numpy as np
from PIL import Image as PILImage
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from algo.adapter.rle import rle_encode

from . import models as m
from .common import APIError, audit, get
from .config import ROOT, settings
from .db import SessionLocal, now, uid
from .storage import storage

PILImage.MAX_IMAGE_PIXELS = 25_000_000
LABELS = ("benign", "malignant", "normal")
NAME = re.compile(r"^(benign|malignant|normal) \((\d+)\)(?:_mask(?:_\d+)?)?\.png$")


def png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def validate_archive(path):
    try:
        with zipfile.ZipFile(path) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            if len(files) > 2000 or sum(i.file_size for i in files) > settings.max_zip_mb * 1024**2:
                raise APIError(413, "ZIP 解压后超过 2 GB 或 2000 个文件")
            names = set()
            for item in files:
                p = PurePosixPath(item.filename)
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in item.filename
                    or ":" in item.filename
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise APIError(422, "ZIP 含非法路径、符号链接或加密文件")
                if item.filename in names:
                    raise APIError(422, "ZIP 内文件名重复")
                names.add(item.filename)
                if item.file_size > settings.max_upload_mb * 1024**2:
                    raise APIError(413, "ZIP 内单文件超过上传上限")
            return [i.filename for i in files]
    except zipfile.BadZipFile:
        raise APIError(415, "不是有效 ZIP 文件") from None


def import_archive(job_id):
    with SessionLocal() as db:
        job = get(db, m.ImportJob, job_id)
        claimed = db.execute(
            update(m.ImportJob)
            .where(m.ImportJob.id == job_id, m.ImportJob.status == "pending")
            .values(status="validating", started_at=now())
        ).rowcount
        db.commit()
        if not claimed:
            return
        db.refresh(job)
        work = settings.work_dir / job.id / "import.zip"
        try:
            storage.download("bidlsp-raw", job.upload_key, work)
            names = validate_archive(work)
            failures, warnings = [], []
            images, mask_names = [], []
            for name in names:
                basename = PurePosixPath(name).name
                if "_mask" in basename:
                    mask_names.append(name)
                else:
                    images.append(name)
            job.total, job.status = len(images), "importing"
            job.success = job.duplicate = job.failed = 0
            db.commit()
            paired = set()
            with zipfile.ZipFile(work) as archive:
                for name in sorted(images):
                    try:
                        with db.begin_nested():
                            image, used, notes = import_image(db, archive, name, mask_names, job)
                            paired.update(used)
                            warnings.extend(notes)
                            if image is None:
                                job.duplicate += 1
                            else:
                                job.success += 1
                    except (APIError, ValueError, OSError, IntegrityError) as exc:
                        job.failed += 1
                        failures.append(
                            {
                                "file": name,
                                "reason": exc.message
                                if isinstance(exc, APIError)
                                else "解码、命名或数据约束校验失败",
                            }
                        )
                    db.commit()
            for orphan in sorted(set(mask_names) - paired):
                warnings.append({"file": orphan, "reason": "孤儿或未导入影像的掩膜"})
            job.status = "completed"
            job.report = {"failures": failures, "warnings": warnings}
            job.finished_at = now()
            audit(
                db,
                db.get(m.User, job.created_by),
                "data.import.finish",
                job,
                detail={"success": job.success, "duplicate": job.duplicate, "failed": job.failed},
            )
            db.commit()
        except Exception:
            db.rollback()
            job = get(db, m.ImportJob, job_id)
            job.status = "failed"
            job.finished_at = now()
            job.report = {"error": "导入失败，请检查 ZIP、对象存储与 Worker 日志"}
            db.commit()
            import logging

            logging.getLogger(__name__).exception("Import %s failed", job_id)
        finally:
            work.unlink(missing_ok=True)


def import_image(db, archive, name, mask_names, job):
    path = PurePosixPath(name)
    match = NAME.fullmatch(path.name)
    if not match or "_mask" in path.name:
        raise APIError(422, "文件名不符合 BUSI 规范")
    label = next((p for p in reversed(path.parts[:-1]) if p in LABELS), job.class_hint)
    if label not in LABELS or label != match[1]:
        raise APIError(422, "类别目录或 class_hint 与文件名不符")
    mask_pattern = re.compile(re.escape(str(path.with_suffix(""))) + r"_mask(?:_\d+)?\.png$")
    matches = [n for n in mask_names if mask_pattern.fullmatch(n)]
    data = archive.read(name)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise APIError(415, "PNG 魔术字节不符")
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(m.Image).where(m.Image.sha256 == digest))
    if existing:
        return (
            None,
            matches,
            [
                {
                    "file": name,
                    "relative_path": f"{label}/{path.name}",
                    "reason": "DUPLICATE_IMAGE",
                    "duplicate_of": existing.relative_path,
                    "sha256": digest,
                    "class_conflict": existing.class_label != label,
                }
            ],
        )
    with PILImage.open(io.BytesIO(data)) as original:
        if original.width * original.height > 25_000_000:
            raise APIError(413, "影像像素过多")
        original.load()
        rgb = original.convert("RGB")
        channels = 1 if original.mode in ("L", "I", "I;16", "1") else 3
        bit_depth = 16 if original.mode in ("I", "I;16") else 8
    if not matches and label != "normal":
        raise APIError(422, "病灶影像缺少配对掩膜")
    mask = np.zeros((rgb.height, rgb.width), dtype=bool)
    warnings = []
    for mask_name in matches:
        mask_bytes = archive.read(mask_name)
        if not mask_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise APIError(415, "掩膜不是 PNG")
        with PILImage.open(io.BytesIO(mask_bytes)) as mask_image:
            mask_image.load()
            gray = mask_image.convert("L")
            if gray.size != rgb.size:
                gray = gray.resize(rgb.size, PILImage.Resampling.NEAREST)
                warnings.append({"file": mask_name, "reason": "掩膜按最近邻缩放到原图尺寸"})
            mask |= np.asarray(gray) > 0
    if label == "normal" and mask.any():
        raise APIError(422, "正常图掩膜包含前景")
    if label != "normal" and not mask.any():
        raise APIError(422, "病灶参考掩膜为空")
    image_id = uid()
    original_key = f"raw/{job.dataset_id}/{label}/{image_id}/{path.name}"
    prefix = f"curated/{image_id}"
    storage.put("bidlsp-raw", original_key, data, "image/png")
    for mask_name in matches:
        storage.put(
            "bidlsp-raw",
            f"raw/{job.dataset_id}/{label}/{image_id}/{PurePosixPath(mask_name).name}",
            archive.read(mask_name),
            "image/png",
        )
    mask_key = storage.put(
        "bidlsp-curated",
        prefix + "/mask.png",
        png(PILImage.fromarray(mask.astype("uint8") * 255)),
        "image/png",
    )
    preview = storage.put("bidlsp-curated", prefix + "/image.png", png(rgb), "image/png")
    cache = storage.put("bidlsp-curated", prefix + "/thumb_256.png", png(rgb.resize((256, 256))), "image/png")
    image = m.Image(
        id=image_id,
        dataset_id=job.dataset_id,
        filename=path.name,
        relative_path=f"{label}/{path.name}",
        object_key=original_key,
        mask_object_key=mask_key,
        cache_key=cache,
        preview_key=preview,
        format="png",
        width=rgb.width,
        height=rgb.height,
        channels=channels,
        bit_depth=bit_depth,
        file_size=len(data),
        sha256=digest,
        class_label=label,
    )
    db.add(image)
    db.flush()
    db.add(
        m.Annotation(
            image_id=image.id,
            version=1,
            mask_rle=rle_encode(mask),
            mask_key=mask_key,
            is_empty=not bool(mask.any()),
            source="import",
            status="approved",
            annotator_id=job.created_by,
            note="BUSI 公共参考掩膜导入；非人工审核",
            reviewed_at=now(),
        )
    )
    db.flush()
    return image, matches, warnings


def freeze(db, version, user, request):
    if version.status != "draft":
        raise APIError(409, "只有草稿版本可冻结")
    stmt = select(m.Image).where(m.Image.dataset_id == version.dataset_id)
    filters = version.filter
    if filters.get("class_labels"):
        stmt = stmt.where(m.Image.class_label.in_(filters["class_labels"]))
    if filters.get("image_ids"):
        stmt = stmt.where(m.Image.id.in_(filters["image_ids"]))
    images = list(db.scalars(stmt.order_by(m.Image.relative_path)))
    annotations = {
        a.image_id: a
        for a in db.scalars(
            select(m.Annotation).where(
                m.Annotation.status == "approved", m.Annotation.image_id.in_([i.id for i in images])
            )
        )
    }
    if filters.get("only_approved"):
        images = [i for i in images if i.id in annotations]
    if not images:
        raise APIError(422, "没有可冻结影像")
    if any(i.id not in annotations for i in images):
        raise APIError(409, "影像缺少 approved 标注")
    frozen = json.loads((ROOT / "transunet/data/splits/busi_seed0.json").read_text())
    reference = {name: split for split in ("train", "val", "test") for name in frozen[split]}
    duplicate_paths = set()
    for job in db.scalars(
        select(m.ImportJob).where(
            m.ImportJob.dataset_id == version.dataset_id, m.ImportJob.status == "completed"
        )
    ):
        duplicate_paths.update(
            w["relative_path"]
            for w in (job.report or {}).get("warnings", [])
            if w.get("reason") == "DUPLICATE_IMAGE" and w.get("relative_path") in reference
        )
    present_paths = {i.relative_path for i in images}
    use_reference = (
        version.split_seed == 0
        and version.ratios == {"train": 0.7, "val": 0.15, "test": 0.15}
        and present_paths <= set(reference)
        and present_paths | duplicate_paths == set(reference)
    )
    assignments = {}
    if use_reference:
        assignments = {i.id: reference[i.relative_path] for i in images}
    else:
        rng = random.Random(version.split_seed)
        for label in LABELS:
            group = [i for i in images if i.class_label == label]
            if not group:
                continue
            rng.shuffle(group)
            a, b = round(len(group) * version.ratios["train"]), round(len(group) * version.ratios["val"])
            if min(a, b, len(group) - a - b) < 1:
                raise APIError(422, "每个所选类别至少需要可划分为三个非空集合的样本")
            for idx, image in enumerate(group):
                assignments[image.id] = "train" if idx < a else "val" if idx < a + b else "test"
    counts = {s: list(assignments.values()).count(s) for s in ("train", "val", "test")}
    items = []
    for image in images:
        annotation = annotations[image.id]
        item = {
            "image_id": image.id,
            "relative_path": image.relative_path,
            "sha256": image.sha256,
            "annotation_id": annotation.id,
            "annotation_version": annotation.version,
            "mask_ref": annotation.mask_key,
            "split": assignments[image.id],
            "class_label": image.class_label,
        }
        items.append(item)
        db.add(
            m.DatasetItem(
                dataset_version_id=version.id,
                image_id=image.id,
                annotation_id=annotation.id,
                split=item["split"],
                class_label=image.class_label,
                mask_ref=annotation.mask_key,
            )
        )
    manifest = {
        "dataset_version_id": version.id,
        "split_seed": version.split_seed,
        "split_source": "busi_seed0.json" if use_reference else "stratified-python-random",
        "effective_seed": frozen["seed"] if use_reference else version.split_seed,
        "ratios": version.ratios,
        "counts": counts,
        "items": items,
        "excluded_duplicates": sorted(set(reference) - present_paths) if use_reference else [],
    }
    prefix = f"datasets/{version.dataset_id}/{version.id}"
    version.manifest_key = storage.put(
        "bidlsp-dataset",
        prefix + "/manifest.json",
        json.dumps(manifest, ensure_ascii=False).encode(),
        "application/json",
    )
    for split in counts:
        storage.put(
            "bidlsp-dataset",
            prefix + f"/splits/{split}.txt",
            "\n".join(i["relative_path"] for i in items if i["split"] == split).encode(),
            "text/plain",
        )
    version.status, version.frozen_at, version.counts = "frozen", now(), counts
    audit(
        db,
        user,
        "dataset.freeze",
        version,
        request,
        {"counts": counts, "effective_seed": manifest["effective_seed"]},
    )
    db.flush()
    return version
