from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["admin", "data_engineer", "annotator", "screener", "reviewer"]
Label = Literal["benign", "malignant", "normal"]
ID = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$")]
Password = Annotated[str, Field(min_length=8, max_length=64)]
Note = Annotated[str, Field(max_length=512)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str = Field(min_length=3, max_length=64)
    password: Password


class PasswordChange(Input):
    old_password: Password
    new_password: Password


class UserCreate(Login):
    display_name: str = Field(min_length=1, max_length=64)
    roles: list[Role] = Field(min_length=1)


class UserPatch(Input):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["active", "disabled"] | None = None
    roles: list[Role] | None = Field(default=None, min_length=1)
    password: Password | None = None


class DatasetCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)


class Ratios(Input):
    train: float = Field(default=0.7, gt=0, lt=1)
    val: float = Field(default=0.15, gt=0, lt=1)
    test: float = Field(default=0.15, gt=0, lt=1)

    @model_validator(mode="after")
    def total(self):
        if abs(self.train + self.val + self.test - 1) > 1e-8:
            raise ValueError("ratios must sum to 1")
        return self


class ImageFilter(Input):
    class_labels: list[Label] | None = None
    only_approved: bool = False
    image_ids: list[ID] | None = None


class VersionCreate(Input):
    dataset_id: ID
    version: str = Field(min_length=1, max_length=32)
    split_seed: int = Field(default=0, ge=0)
    ratios: Ratios = Field(default_factory=Ratios)
    filter: ImageFilter = Field(default_factory=ImageFilter)


class AnnotationTaskCreate(Input):
    dataset_version_id: ID | None = None
    image_ids: list[ID] | None = Field(default=None, min_length=1, max_length=500)
    class_labels: list[Label] | None = None
    count: int = Field(default=500, ge=1, le=500)
    priority: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def source(self):
        if bool(self.dataset_version_id) == bool(self.image_ids):
            raise ValueError("choose dataset_version_id or image_ids")
        return self


class RLE(Input):
    size: list[Annotated[int, Field(strict=True, gt=0, le=10000)]] = Field(min_length=2, max_length=2)
    counts: list[Annotated[int, Field(strict=True, ge=0)]] = Field(min_length=1, max_length=1000000)

    @model_validator(mode="after")
    def valid(self):
        if self.size[0] * self.size[1] > 25_000_000:
            raise ValueError("mask exceeds 25 million pixels")
        if sum(self.counts) != self.size[0] * self.size[1]:
            raise ValueError("counts must sum to H*W")
        return self


class AnnotationCreate(Input):
    image_id: ID
    mask_rle: RLE
    is_empty: bool = False
    source: Literal["manual", "preannot", "model", "import"]
    note: Note | None = None


class Submit(Input):
    note: Note | None = None


class AnnotationDecision(Input):
    decision: Literal["approve", "reject"]
    comment: Note | None = None


class ModelCreate(Input):
    name: Literal["transunet"]
    task: Literal["segmentation"] = "segmentation"
    framework: Literal["pytorch"] = "pytorch"


class ModelConfigInput(Input):
    size: Literal[256]
    in_ch: Literal[3]
    rgb: Literal[True]
    tta: bool
    scales: list[float]
    threshold: float = Field(gt=0, lt=1)
    postproc: bool
    min_area: float = Field(ge=0, lt=1)
    seed: int = Field(ge=0)
    transunet_commit: Literal["02ef0010b36eb8328b5e689eadaf613602edf9b8"]

    @field_validator("scales")
    @classmethod
    def scales_fixed(cls, value):
        if value != [1.0]:
            raise ValueError("TransUNet requires scales=[1.0]")
        return value


class ModelVersionCreate(Input):
    version: str = Field(min_length=1, max_length=64)
    weights_key: str = Field(min_length=1, max_length=512)
    weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: ModelConfigInput
    metrics: dict | None = None


class InferenceParams(Input):
    tta: bool | None = None
    threshold: float | None = Field(default=None, gt=0, lt=1)
    postproc: bool | None = None
    min_area: float | None = Field(default=None, ge=0, lt=1)


class InferenceCreate(Input):
    image_id: ID
    model_version_id: ID | None = None
    params: InferenceParams = Field(default_factory=InferenceParams)


class EvaluationCreate(Input):
    model_version_id: ID
    dataset_version_id: ID


class BatchCreate(EvaluationCreate):
    params: InferenceParams = Field(default_factory=InferenceParams)


class PatientCreate(Input):
    patient_no: str | None = Field(default=None, min_length=1, max_length=64)
    gender: Literal["M", "F", "O"]
    birth_year: int | None = Field(default=None, ge=1900, le=date.today().year)
    remark: str | None = Field(default=None, max_length=255)


class StudyCreate(Input):
    patient_id: ID
    study_no: str | None = Field(default=None, min_length=1, max_length=64)
    modality: Literal["US", "MG"] = "US"
    device: str | None = Field(default=None, max_length=64)
    study_date: date
    indication: str | None = Field(default=None, max_length=255)
    image_ids: list[ID] = Field(default_factory=list, max_length=500)


class ScreenCreate(Input):
    study_id: ID
    priority: int = Field(default=3, ge=1, le=5)


class StudyDecision(Input):
    decision: Literal["accept", "modify", "reject"]
    image_id: ID | None = None
    annotation_id: ID | None = None
    mask_rle: RLE | None = None
    is_empty: bool = False
    comment: Note | None = None
    follow_up: bool = False


class TemplateCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=20000)
    variables: list[str] = Field(default_factory=list, max_length=30)


class TemplatePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    variables: list[str] | None = Field(default=None, max_length=30)
    active: bool | None = None


class ReportContent(Input):
    findings: str = Field(max_length=5000)
    impression: str = Field(max_length=5000)
    recommendation: str = Field(max_length=5000)


class ReportCreate(Input):
    study_id: ID
    inference_result_id: ID | None = None
    template_id: ID
    content: ReportContent


class ReportDecision(Input):
    decision: Literal["sign", "reject"]
    comment: Note | None = None
