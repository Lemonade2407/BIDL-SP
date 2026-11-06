import { http } from './client'
import type { Dataset, DatasetVersion, LoginPayload, RegisterPayload, ReportContent, User } from '@/types'

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
export function getUsers(params: { page?: number; page_size?: number; q?: string } = {}) {
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
export function getImages(params: { page?: number; page_size?: number; q?: string; class_label?: string; split?: string } = {}) {
  return http.get('/images', { params })
}
export function getImage(id: string) {
  return http.get(`/images/${id}`)
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

// ---- 标注 ----
export function getAnnotationTasks(params: { page?: number; page_size?: number; status?: string } = {}) {
  return http.get('/annotation-tasks', { params })
}
export function claimAnnotationTask(id: string) {
  return http.post(`/annotation-tasks/${id}/claim`)
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

// ---- 推理 ----
export function createInference(payload: { image_id: string; model_version_id?: string; params?: unknown }) {
  return http.post('/inference-tasks', payload)
}
export function getInference(id: string) {
  return http.get(`/inference-tasks/${id}`)
}

// ---- 筛查 ----
export function getScreenTasks(params: { page?: number; page_size?: number; status?: string } = {}) {
  return http.get('/screen-tasks', { params })
}
export function claimScreenTask(id: string) {
  return http.post(`/screen-tasks/${id}/claim`)
}
export function getStudy(id: string) {
  return http.get(`/studies/${id}`)
}
export function reviewStudy(id: string, payload: { decision: string; comment?: string }) {
  return http.post(`/studies/${id}/reviews`, payload)
}

// ---- 报告 ----
export function getReportTemplates() {
  return http.get('/report-templates')
}
export function createReport(payload: {
  study_id: string
  inference_result_id?: string | null
  template_id: string
  content: ReportContent
}) {
  return http.post('/reports', payload)
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
  return http.get(`/reports/${id}/pdf`)
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
export function getStatsScreening() {
  return http.get('/stats/screening')
}

// ---- 审计 ----
export function getAuditLogs(params: { page?: number; page_size?: number; q?: string } = {}) {
  return http.get('/audit-logs', { params })
}

// ---- 健康 ----
export function healthz() {
  return http.get('/healthz')
}
