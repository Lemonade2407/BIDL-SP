import { http } from './client'
import type { Dataset, DatasetVersion, LoginPayload, RegisterPayload, ReportContent, RleMask, User } from '@/types'

// ---- 认证 ----
export function login(payload: LoginPayload) {
  return http.post('/auth/login', payload)
}
export function register(payload: RegisterPayload) {
  return http.post('/auth/register', payload)
}
export function logout() {
  return http.post('/auth/logout')
}
export function me() {
  return http.get('/auth/me')
}

// ---- 用户 ----
export function getUsers(params: { page?: number; page_size?: number; q?: string; role?: string; status?: string } = {}) {
  return http.get('/users', { params })
}
export function createUser(payload: Partial<User>) {
  return http.post('/users', payload)
}
export function patchUser(id: string, payload: Partial<User>) {
  return http.patch(`/users/${id}`, payload)
}

// ---- 数据集 / 导入 ----
export function getDatasets() {
  return http.get('/datasets')
}
export function createDataset(payload: Partial<Dataset>) {
  return http.post('/datasets', payload)
}
export function createImport(datasetId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return http.post(`/datasets/${datasetId}/imports`, form)
}
export function getImport(jobId: string) {
  return http.get(`/imports/${jobId}`)
}

// ---- 影像 ----
export function getImages(params: { page?: number; page_size?: number; q?: string; class_label?: string; split?: string; unassigned?: boolean; exclude?: string } = {}) {
  return http.get('/images', { params })
}
export function getImage(id: string) {
  return http.get(`/images/${id}`)
}
export function excludeImage(id: string, excludeReason: string | null) {
  return http.post(`/images/${id}/exclude`, { exclude_reason: excludeReason })
}
export function getStudies(params: {
  page?: number
  page_size?: number
  q?: string
  status?: string
  from?: string
  to?: string
} = {}) {
  return http.get('/studies', { params })
}

// ---- 数据集版本 ----
export function getDatasetVersions() {
  return http.get('/dataset-versions')
}
export function createDatasetVersion(payload: Partial<DatasetVersion>) {
  return http.post('/dataset-versions', payload)
}
export function freezeDatasetVersion(id: string) {
  return http.post(`/dataset-versions/${id}/freeze`)
}
export function archiveDatasetVersion(id: string) {
  return http.post(`/dataset-versions/${id}/archive`)
}

// ---- 标注 ----
export function getAnnotationTasks(params: { page?: number; page_size?: number; status?: string; assignee?: string; sort?: string } = {}) {
  return http.get('/annotation-tasks', { params })
}
export function createAnnotationTasks(payload: {
  dataset_version_id?: string | null
  image_ids?: string[]
  class_labels?: string[]
  count?: number
  priority?: number
  required_annotators?: number
}) {
  return http.post('/annotation-tasks', payload)
}
export function claimAnnotationTask(id: string) {
  return http.post(`/annotation-tasks/${id}/claim`)
}
export function joinAnnotationTask(id: string) {
  return http.post(`/annotation-tasks/${id}/join`)
}
export function releaseAnnotationTask(id: string) {
  return http.post(`/annotation-tasks/${id}/release`)
}
export function saveAnnotation(payload: unknown) {
  return http.post('/annotations', payload)
}
export function submitAnnotation(id: string) {
  return http.post(`/annotations/${id}/submit`)
}
export function reviewAnnotation(id: string, payload: { decision: string; comment?: string }) {
  return http.post(`/annotations/${id}/reviews`, payload)
}
export function getAnnotation(id: string) {
  return http.get(`/annotations/${id}`)
}
export function getAnnotationHistory(imageId: string) {
  return http.get(`/images/${imageId}/annotations`)
}

// ---- 模型 ----
export function getModels() {
  return http.get('/models')
}
export function activateModelVersion(id: string) {
  return http.post(`/model-versions/${id}/activate`)
}
export function registerModelVersion(id: string, payload: {
  version: string
  weights_key: string
  weights_sha256: string
  config: Record<string, unknown>
  metrics?: Record<string, unknown> | null
}) {
  return http.post(`/models/${id}/versions`, payload)
}
export function getEvaluations(params: {
  page?: number
  page_size?: number
  model_version_id?: string
  dataset_version_id?: string
  status?: string
} = {}) {
  return http.get('/evaluations', { params })
}
export function createEvaluation(payload: { model_version_id: string; dataset_version_id: string }) {
  return http.post('/evaluations', payload)
}
export function getEvaluation(id: string) {
  return http.get(`/evaluations/${id}`)
}

// ---- 推理 ----
export function createInference(payload: { image_id: string; model_version_id?: string; params?: unknown }) {
  return http.post('/inference-tasks', payload)
}
export function getInference(id: string) {
  return http.get(`/inference-tasks/${id}`)
}
export function createInferenceBatch(payload: {
  dataset_version_id: string
  model_version_id: string
  params?: Record<string, unknown>
}) {
  return http.post('/inference-batches', payload)
}
export function getInferenceBatch(id: string) {
  return http.get(`/inference-batches/${id}`)
}
export function batchToAnnotations(id: string) {
  return http.post(`/inference-batches/${id}/to-annotations`)
}

// ---- 筛查 ----
export function createPatient(payload: {
  patient_no?: string
  gender: 'M' | 'F' | 'O'
  birth_year?: number | null
  remark?: string | null
}) {
  return http.post('/patients', payload)
}
export function createStudy(payload: {
  patient_id: string
  study_no?: string
  modality?: 'US' | 'MG'
  device?: string | null
  study_date: string
  indication?: string | null
  image_ids: string[]
}) {
  return http.post('/studies', payload)
}
export function createScreenTask(payload: { study_id: string; priority?: number }) {
  return http.post('/screen-tasks', payload)
}
export function getScreenTasks(params: { page?: number; page_size?: number; status?: string; assignee?: string; priority?: number; sort?: string } = {}) {
  return http.get('/screen-tasks', { params })
}
export function claimScreenTask(id: string) {
  return http.post(`/screen-tasks/${id}/claim`)
}
export function releaseScreenTask(id: string) {
  return http.post(`/screen-tasks/${id}/release`)
}
export function reassignScreenTask(id: string, assigneeId: string) {
  return http.post(`/screen-tasks/${id}/reassign`, { assignee_id: assigneeId })
}
export function getStudy(id: string) {
  return http.get(`/studies/${id}`)
}
export function reviewStudy(id: string, payload: {
  decision: string
  image_id?: string
  annotation_id?: string
  mask_rle?: RleMask
  is_empty?: boolean
  comment?: string
  follow_up?: string | boolean
}) {
  return http.post(`/studies/${id}/reviews`, payload)
}

// ---- 报告 ----
export function getReportTemplates() {
  return http.get('/report-templates')
}
export function previewReportTemplate(payload: { body: string; variables: string[] }) {
  return http.post('/report-templates/preview', payload)
}
export function createReportTemplate(payload: { name: string; body: string; variables: string[]; active?: boolean }) {
  return http.post('/report-templates', payload)
}
export function patchReportTemplate(id: string, payload: Partial<{ name: string; body: string; variables: string[]; active: boolean }>) {
  return http.patch(`/report-templates/${id}`, payload)
}
export function createReport(payload: {
  study_id: string
  inference_result_id?: string | null
  template_id: string
  content: ReportContent
}) {
  return http.post('/reports', payload)
}
export function getReports(params: {
  page?: number
  page_size?: number
  status?: string
  study_id?: string
  author_id?: string
  reviewer_id?: string
} = {}) {
  return http.get('/reports', { params })
}
export function getReport(id: string) {
  return http.get(`/reports/${id}`)
}
export function submitReport(id: string) {
  return http.post(`/reports/${id}/submit`)
}
export function signReport(id: string, payload: { decision: string; comment?: string }) {
  return http.post(`/reports/${id}/sign`, payload)
}
export function getReportPdf(id: string) {
  return http.get(`/reports/${id}/pdf`, { responseType: 'blob' })
}

// ---- 统计 ----
export function getStatsOverview() {
  return http.get('/stats/overview')
}
export function getStatsAnnotations() {
  return http.get('/stats/annotations')
}
export function getStatsModels() {
  return http.get('/stats/models')
}
export function getStatsScreening(params: { from?: string; to?: string } = {}) {
  return http.get('/stats/screening', { params })
}

// ---- 审计 ----
export function getAuditLogs(params: {
  page?: number
  page_size?: number
  q?: string
  actor_id?: string
  action?: string
  object_type?: string
  object_id?: string
  from?: string
  to?: string
} = {}) {
  return http.get('/audit-logs', { params })
}

// ---- 健康 ----
export function healthz() {
  return http.get('/healthz')
}

// ---- 通知 ----
export function getNotifications(params: { page?: number; page_size?: number; unread_only?: boolean } = {}) {
  return http.get('/notifications', { params, silent: true })
}
export function getUnreadCount() {
  return http.get('/notifications/unread-count', { silent: true })
}
export function markNotificationRead(id: string) {
  return http.post(`/notifications/${id}/read`)
}
export function markAllNotificationsRead() {
  return http.post('/notifications/read-all', null, { silent: true })
}

// ---- 回程路径 ----
export function retryInferenceBatch(id: string) {
  return http.post(`/inference-batches/${id}/retry`)
}
export function voidReport(id: string, payload: { reason: string }) {
  return http.post(`/reports/${id}/void`, payload)
}
export function createAnnotationTasksBatch(payload: {
  image_ids?: string[]
  dataset_version_id?: string | null
  class_labels?: string[]
  priority?: number
  required_annotators?: number
}) {
  return http.post('/annotation-tasks/batch', payload)
}