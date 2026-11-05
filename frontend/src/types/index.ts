// ===== 枚举 =====
export type ClassLabel = 'benign' | 'malignant' | 'normal'
export type Split = 'train' | 'val' | 'test'
export type ImageSource = 'BUSI' | 'DICOM' | 'UPLOAD'
export type ImageFormat = 'png' | 'jpg' | 'dicom'
export type AnnotationSource = 'manual' | 'preannot' | 'model' | 'import'
export type AnnotationStatus = 'draft' | 'pending' | 'approved' | 'rejected'
export type AnnotationTaskStatus = 'pending' | 'in_progress' | 'submitted' | 'approved' | 'rejected'
export type ImportJobStatus = 'pending' | 'validating' | 'importing' | 'completed' | 'failed'
export type DatasetVersionStatus = 'draft' | 'frozen' | 'archived'
export type ModelVersionStatus = 'candidate' | 'active' | 'archived'
export type EvalJobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type InferenceTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type InferenceBatchStatus = 'queued' | 'running' | 'succeeded' | 'partial' | 'failed'
export type ScreenTaskStatus = 'pending' | 'in_progress' | 'done'
export type ReportStatus = 'draft' | 'pending_review' | 'signed' | 'rejected'
export type ReportDecision = 'sign' | 'reject'
export type ReviewDecision = 'approve' | 'reject'
export type StudyReviewDecision = 'accept' | 'modify' | 'reject'
export type Modality = 'US' | 'MG'
export type Gender = 'M' | 'F' | 'O'
export type QualityFlag =
  | 'EMPTY_MASK'
  | 'AREA_TOO_LARGE'
  | 'LOW_CONFIDENCE'
  | 'MULTI_LESION'
  | 'MASK_MISSING'
export type Role = 'admin' | 'data_engineer' | 'annotator' | 'screener' | 'reviewer'
export type UserStatus = 'active' | 'disabled'

// ===== 通用 =====
export interface UserRef {
  id: string
  username?: string
  display_name?: string
}

export interface ApiMeta {
  request_id?: string
  page?: number
  page_size?: number
  total?: number
}

export interface ApiResponse<T> {
  data: T
  meta?: ApiMeta
}

export interface ApiError {
  code: string
  message: string
  request_id?: string
  details?: { field: string; reason: string }[]
}

export interface PageQuery {
  page?: number
  page_size?: number
  sort?: string
  q?: string
}

// ===== 对象 =====
export interface User {
  id: string
  username: string
  display_name: string
  status: UserStatus
  roles: Role[]
  last_login_at?: string | null
  created_at?: string
}

export interface Image {
  id: string
  study_id?: string | null
  format: ImageFormat
  width: number
  height: number
  channels: number
  bit_depth: number
  sha256: string
  class_label?: ClassLabel | null
  source: ImageSource
  mask_available: boolean
  annotation_status?: AnnotationStatus | null
  thumbnail_url?: string | null
  created_at?: string
}

export interface ImportJob {
  id: string
  dataset_id: string
  status: ImportJobStatus
  total: number
  success: number
  failed: number
  duplicate: number
  report?: Record<string, unknown> | null
  started_at?: string | null
  finished_at?: string | null
}

export interface Dataset {
  id: string
  name: string
  description?: string | null
  image_count?: number
  created_at?: string
}

export interface DatasetVersion {
  id: string
  dataset_id: string
  version: string
  status: DatasetVersionStatus
  split_seed: number
  ratios: { train: number; val: number; test: number }
  counts: { train: number; val: number; test: number }
  manifest_url?: string | null
  frozen_at?: string | null
  created_at?: string
}

export interface RleMask {
  size: [number, number]
  counts: number[]
}

export interface Annotation {
  id: string
  image_id: string
  version: number
  mask_rle: RleMask | null
  is_empty: boolean
  source: AnnotationSource
  status: AnnotationStatus
  annotator: UserRef
  note?: string | null
  review_comment?: string | null
  reviewed_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface AnnotationTask {
  id: string
  image_id: string
  dataset_version_id?: string | null
  assignee?: UserRef | null
  status: AnnotationTaskStatus
  priority: number
  annotation_id?: string | null
  claimed_at?: string | null
  finished_at?: string | null
  created_at?: string
}

export interface ModelVersion {
  id: string
  model_id: string
  version: string
  weights_key: string
  weights_sha256: string
  config: Record<string, unknown>
  metrics?: Record<string, unknown> | null
  status: ModelVersionStatus
  created_at?: string
}

export interface InferenceResult {
  mask_url?: string | null
  mask_rle: RleMask | null
  prob_mean: number
  lesion_area_ratio: number
  quality_flags: QualityFlag[]
  elapsed_ms: number
}

export interface InferenceTask {
  id: string
  image_id: string
  model_version_id: string
  status: InferenceTaskStatus
  params?: Record<string, unknown>
  result?: InferenceResult | null
  error?: string | null
  created_at?: string
  finished_at?: string | null
}

export interface PatientRef {
  id?: string
  name: string
  gender?: Gender
  birth_date?: string | null
  medical_no?: string | null
}

export interface TimelineEvent {
  at: string
  actor?: UserRef | null
  action: string
  detail?: Record<string, unknown> | null
}

export interface Study {
  id: string
  study_no: string
  patient: PatientRef
  modality: Modality
  device?: string | null
  study_date: string
  indication?: string | null
  status: string
  images: Image[]
  latest_inference?: InferenceResult | null
  timeline: TimelineEvent[]
  created_at?: string
}

export interface ScreenTask {
  id: string
  study_id: string
  assignee?: UserRef | null
  status: ScreenTaskStatus
  priority: number
  claimed_at?: string | null
  finished_at?: string | null
  created_at?: string
}

export interface ReportContent {
  findings: string
  impression: string
  recommendation: string
}

export interface Report {
  id: string
  study_id: string
  inference_result_id?: string | null
  template_id: string
  content: ReportContent
  status: ReportStatus
  author: UserRef
  reviewer?: UserRef | null
  version: number
  signed_at?: string | null
  pdf_url?: string | null
  created_at?: string
  updated_at?: string
}

export interface ReportTemplate {
  id: string
  name: string
  body: string
  variables: string[]
  active: boolean
}

export interface AuditLog {
  id: number
  actor?: UserRef | null
  action: string
  object_type: string
  object_id: string
  detail?: Record<string, unknown> | null
  ip?: string | null
  created_at: string
}

export interface StatsOverview {
  images: number
  annotations_approved: number
  dataset_versions: number
  model_versions: number
  screen_tasks: number
  reports_signed: number
  positive_rate: number
  avg_review_seconds: number
}

// ===== 登录 =====
export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}