"""Relational identities and constraints; JSON stores versioned clinical payloads only."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from .db import Base, Entity


def ref(table, **kw):
    return Column(String(36), ForeignKey(table + ".id", ondelete="RESTRICT"), **kw)


class User(Entity, Base):
    __tablename__ = "app_user"
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(64), nullable=False)
    roles = Column(JSON, nullable=False)
    status = Column(String(16), default="active", nullable=False)
    token_version = Column(Integer, default=0, nullable=False)
    last_login_at = Column(DateTime(timezone=True))


class RevokedToken(Entity, Base):
    __tablename__ = "revoked_token"
    jti = Column(String(36), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Dataset(Entity, Base):
    __tablename__ = "dataset"
    name = Column(String(64), unique=True, nullable=False)
    description = Column(Text)
    created_by = ref("app_user", nullable=False)


class ImportJob(Entity, Base):
    __tablename__ = "import_job"
    dataset_id = ref("dataset", nullable=False)
    created_by = ref("app_user", nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    total = Column(Integer, default=0)
    success = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    duplicate = Column(Integer, default=0)
    report = Column(JSON)
    upload_key = Column(String(512), nullable=False)
    class_hint = Column(String(16))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class Patient(Entity, Base):
    __tablename__ = "patient"
    patient_no = Column(String(64), unique=True, nullable=False)
    gender = Column(String(1), nullable=False)
    birth_year = Column(Integer)
    remark = Column(String(255))
    created_by = ref("app_user", nullable=False)


class Study(Entity, Base):
    __tablename__ = "study"
    patient_id = ref("patient", nullable=False)
    study_no = Column(String(64), unique=True, nullable=False)
    modality = Column(String(8), nullable=False)
    device = Column(String(64))
    study_date = Column(Date, nullable=False)
    indication = Column(String(255))
    status = Column(String(16), default="pending", nullable=False)
    created_by = ref("app_user", nullable=False)


class Image(Entity, Base):
    __tablename__ = "image"
    dataset_id = ref("dataset", nullable=False, index=True)
    study_id = ref("study", index=True)
    filename = Column(String(255), nullable=False)
    relative_path = Column(String(512), nullable=False)
    object_key = Column(String(512), unique=True, nullable=False)
    mask_object_key = Column(String(512))
    cache_key = Column(String(512))
    preview_key = Column(String(512))
    format = Column(String(8), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    channels = Column(Integer, nullable=False)
    bit_depth = Column(Integer, nullable=False)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), unique=True, nullable=False)
    class_label = Column(String(16), nullable=False, index=True)
    source = Column(String(16), default="BUSI", nullable=False)


class Annotation(Entity, Base):
    __tablename__ = "annotation"
    image_id = ref("image", nullable=False, index=True)
    version = Column(Integer, nullable=False)
    mask_rle = Column(JSON, nullable=False)
    mask_key = Column(String(512), nullable=False)
    is_empty = Column(Boolean, default=False, nullable=False)
    source = Column(String(16), nullable=False)
    status = Column(String(16), default="draft", nullable=False)
    annotator_id = ref("app_user", nullable=False)
    note = Column(String(512))
    reviewed_by_id = ref("app_user")
    review_comment = Column(String(512))
    reviewed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("image_id", "version"),
        Index(
            "uq_approved_annotation",
            "image_id",
            unique=True,
            postgresql_where=text("status='approved'"),
            sqlite_where=text("status='approved'"),
        ),
    )


class AnnotationReview(Entity, Base):
    __tablename__ = "annotation_review"
    annotation_id = ref("annotation", nullable=False)
    reviewer_id = ref("app_user", nullable=False)
    decision = Column(String(16), nullable=False)
    comment = Column(String(512))


class DatasetVersion(Entity, Base):
    __tablename__ = "dataset_version"
    dataset_id = ref("dataset", nullable=False)
    version = Column(String(32), nullable=False)
    status = Column(String(16), default="draft", nullable=False)
    split_seed = Column(Integer, default=0, nullable=False)
    ratios = Column(JSON, nullable=False)
    filter = Column(JSON, nullable=False)
    counts = Column(JSON)
    manifest_key = Column(String(512))
    frozen_at = Column(DateTime(timezone=True))
    created_by = ref("app_user", nullable=False)
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)


class DatasetItem(Entity, Base):
    __tablename__ = "dataset_item"
    dataset_version_id = ref("dataset_version", nullable=False, index=True)
    image_id = ref("image", nullable=False)
    annotation_id = ref("annotation", nullable=False)
    split = Column(String(8), nullable=False)
    class_label = Column(String(16), nullable=False)
    mask_ref = Column(String(512), nullable=False)
    __table_args__ = (UniqueConstraint("dataset_version_id", "image_id"),)


class AnnotationTask(Entity, Base):
    __tablename__ = "annotation_task"
    image_id = ref("image", nullable=False)
    dataset_version_id = ref("dataset_version")
    assignee_id = ref("app_user")
    annotation_id = ref("annotation")
    status = Column(String(16), default="pending", nullable=False, index=True)
    priority = Column(Integer, default=3, nullable=False)
    claimed_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_open_annotation_task",
            "image_id",
            unique=True,
            postgresql_where=text("status != 'approved'"),
            sqlite_where=text("status != 'approved'"),
        ),
    )


class Model(Entity, Base):
    __tablename__ = "model"
    name = Column(String(64), nullable=False, unique=True)
    task = Column(String(32), default="segmentation", nullable=False)
    framework = Column(String(32), default="pytorch", nullable=False)


class ModelVersion(Entity, Base):
    __tablename__ = "model_version"
    model_id = ref("model", nullable=False)
    version = Column(String(64), nullable=False)
    weights_key = Column(String(512), nullable=False)
    weights_sha256 = Column(String(64), nullable=False)
    config = Column(JSON, nullable=False)
    metrics = Column(JSON)
    status = Column(String(16), default="candidate", nullable=False)
    created_by = ref("app_user", nullable=False)
    activated_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("model_id", "version"),
        Index(
            "uq_active_model",
            "model_id",
            unique=True,
            postgresql_where=text("status='active'"),
            sqlite_where=text("status='active'"),
        ),
    )


class InferenceBatch(Entity, Base):
    __tablename__ = "inference_batch"
    dataset_version_id = ref("dataset_version", nullable=False)
    model_version_id = ref("model_version", nullable=False)
    params = Column(JSON, nullable=False)
    created_by = ref("app_user", nullable=False)


class InferenceTask(Entity, Base):
    __tablename__ = "inference_task"
    image_id = ref("image", nullable=False, index=True)
    model_version_id = ref("model_version", nullable=False)
    batch_id = ref("inference_batch", index=True)
    requested_by = ref("app_user", nullable=False)
    status = Column(String(16), default="queued", nullable=False)
    params = Column(JSON, nullable=False)
    cache_key = Column(String(64), nullable=False, index=True)
    error = Column(JSON)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class InferenceResult(Entity, Base):
    __tablename__ = "inference_result"
    task_id = ref("inference_task", unique=True, nullable=False)
    mask_key = Column(String(512), nullable=False)
    mask_rle = Column(JSON, nullable=False)
    prob_mean = Column(Float)
    lesion_area_ratio = Column(Float, nullable=False)
    quality_flags = Column(JSON, nullable=False)
    elapsed_ms = Column(Integer, nullable=False)
    artifacts = Column(JSON, nullable=False)


class EvaluationJob(Entity, Base):
    __tablename__ = "evaluation_job"
    model_version_id = ref("model_version", nullable=False)
    dataset_version_id = ref("dataset_version", nullable=False)
    created_by = ref("app_user", nullable=False)
    status = Column(String(16), default="queued", nullable=False)
    metrics = Column(JSON)
    regression = Column(JSON)
    error = Column(JSON)
    result_key = Column(String(512))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class ScreenTask(Entity, Base):
    __tablename__ = "screen_task"
    study_id = ref("study", unique=True, nullable=False)
    assignee_id = ref("app_user")
    status = Column(String(16), default="pending", nullable=False, index=True)
    priority = Column(Integer, default=3, nullable=False)
    claimed_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class StudyReview(Entity, Base):
    __tablename__ = "study_review"
    study_id = ref("study", nullable=False, index=True)
    image_id = ref("image")
    annotation_id = ref("annotation")
    inference_result_id = ref("inference_result")
    reviewer_id = ref("app_user", nullable=False)
    decision = Column(String(16), nullable=False)
    comment = Column(String(512))
    follow_up = Column(Boolean, default=False, nullable=False)


class ReportTemplate(Entity, Base):
    __tablename__ = "report_template"
    name = Column(String(64), nullable=False, unique=True)
    body = Column(Text, nullable=False)
    variables = Column(JSON, nullable=False)
    active = Column(Boolean, default=True, nullable=False)


class Report(Entity, Base):
    __tablename__ = "report"
    study_id = ref("study", nullable=False)
    inference_result_id = ref("inference_result")
    template_id = ref("report_template", nullable=False)
    content = Column(JSON, nullable=False)
    snapshot = Column(JSON, nullable=False)
    rendered_html = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String(16), default="draft", nullable=False)
    author_id = ref("app_user", nullable=False)
    reviewer_id = ref("app_user")
    review_comment = Column(String(512))
    signed_at = Column(DateTime(timezone=True))
    pdf_key = Column(String(512))
    __table_args__ = (UniqueConstraint("study_id", "version"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = ref("app_user")
    action = Column(String(64), nullable=False, index=True)
    object_type = Column(String(32), nullable=False)
    object_id = Column(String(64), nullable=False, index=True)
    detail = Column(JSON, nullable=False)
    ip = Column(String(64))
    request_id = Column(String(64))
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


class Idempotency(Entity, Base):
    __tablename__ = "idempotency"
    actor_id = ref("app_user", nullable=False)
    route = Column(String(160), nullable=False)
    key = Column(String(128), nullable=False)
    digest = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
    status_code = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("actor_id", "route", "key"),)


class Outbox(Entity, Base):
    __tablename__ = "outbox"
    kind = Column(String(32), nullable=False)
    object_id = Column(String(36), nullable=False)
    published_at = Column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("kind", "object_id"),)
