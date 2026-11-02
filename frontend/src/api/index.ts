import { http } from './client'
import { Mock, ok, list } from './mock'
import type {
  AnnotationTask, AuditLog, Dataset, DatasetVersion, Image, ImportJob, InferenceTask,
  LoginPayload, LoginResult, ModelVersion, Report, ReportTemplate, ScreenTask, StatsOverview,
  Study, User
} from '@/types'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

// ---- 认证 ----
export function login(payload: LoginPayload) {
  if (USE_MOCK) {
    const user = Mock.users.find((u) => u.username === payload.username)
    if (user) {
      const result: LoginResult = { access_token: 'mock-token-' + user.id, token_type: 'bearer', expires_in: 3600, user }
      return ok(result)
    }
    return Promise.reject({ response: { status: 401, data: { code: 'UNAUTHORIZED', message: '用户名或密码错误' } } })
  }
  return http.post('/auth/login', payload)
}
export function logout() {
  if (USE_MOCK) return ok(null)
  return http.post('/auth/logout')
}
export function me() {
  if (USE_MOCK) return ok(Mock.users[0])
  return http.get('/auth/me')
}

// ---- 用户 ----
export function getUsers(params: { page?: number; page_size?: number; q?: string } = {}) {
  if (USE_MOCK) {
    let us = Mock.users
    if (params.q) us = us.filter((u) => u.username.includes(params.q!) || u.display_name.includes(params.q!))
    return list(us, params.page, params.page_size)
  }
  return http.get('/users', { params })
}
export function createUser(payload: Partial<User>) {
  if (USE_MOCK) return ok({ id: 'u-new', ...payload } as User)
  return http.post('/users', payload)
}
export function patchUser(id: string, payload: Partial<User>) {
  if (USE_MOCK) return ok({ id, ...payload } as User)
  return http.patch(`/users/${id}`, payload)
}

// ---- 数据集 / 导入 ----
export function getDatasets() {
  if (USE_MOCK) return list<Dataset>(Mock.datasets)
  return http.get('/datasets')
}
export function createDataset(payload: Partial<Dataset>) {
  if (USE_MOCK) return ok({ id: 'ds-new', ...payload } as Dataset)
  return http.post('/datasets', payload)
}
export function createImport(datasetId: string, payload: unknown) {
  if (USE_MOCK) return ok({ id: 'job-new', dataset_id: datasetId, status: 'pending', total: 0, success: 0, failed: 0, duplicate: 0 } as ImportJob)
  return http.post(`/datasets/${datasetId}/imports`, payload)
}
export function getImport(jobId: string) {
  if (USE_MOCK) return ok(Mock.importJobs.find((j) => j.id === jobId) ?? Mock.importJobs[0])
  return http.get(`/imports/${jobId}`)
}

// ---- 影像 ----
export function getImages(params: { page?: number; page_size?: number; q?: string; class_label?: string; split?: string } = {}) {
  if (USE_MOCK) {
    let ims = Mock.images
    if (params.q) ims = ims.filter((i) => i.id.includes(params.q!))
    if (params.class_label) ims = ims.filter((i) => i.class_label === params.class_label)
    return list<Image>(ims, params.page, params.page_size)
  }
  return http.get('/images', { params })
}
export function getImage(id: string) {
  if (USE_MOCK) return ok(Mock.images.find((i) => i.id === id) ?? Mock.images[0])
  return http.get(`/images/${id}`)
}

// ---- 数据集版本 ----
export function getDatasetVersions() {
  if (USE_MOCK) return list<DatasetVersion>(Mock.datasetVersions)
  return http.get('/dataset-versions')
}
export function createDatasetVersion(payload: Partial<DatasetVersion>) {
  if (USE_MOCK) return ok({ id: 'dv-new', status: 'draft', ...payload } as DatasetVersion)
  return http.post('/dataset-versions', payload)
}
export function freezeDatasetVersion(id: string) {
  if (USE_MOCK) return ok({ id, status: 'frozen' } as DatasetVersion)
  return http.post(`/dataset-versions/${id}/freeze`)
}

// ---- 标注 ----
export function getAnnotationTasks(params: { page?: number; page_size?: number; status?: string } = {}) {
  if (USE_MOCK) {
    let ts = Mock.annotationTasks
    if (params.status) ts = ts.filter((t) => t.status === params.status)
    return list<AnnotationTask>(ts, params.page, params.page_size)
  }
  return http.get('/annotation-tasks', { params })
}
export function claimAnnotationTask(id: string) {
  if (USE_MOCK) return ok({ id, status: 'in_progress' } as AnnotationTask)
  return http.post(`/annotation-tasks/${id}/claim`)
}
export function saveAnnotation(payload: unknown) {
  if (USE_MOCK) return ok({ id: 'ann-new', status: 'draft', ...(payload as object) })
  return http.post('/annotations', payload)
}
export function submitAnnotation(id: string) {
  if (USE_MOCK) return ok({ id, status: 'submitted' })
  return http.post(`/annotations/${id}/submit`)
}
export function reviewAnnotation(id: string, payload: { decision: string; comment?: string }) {
  if (USE_MOCK) return ok({ id, status: payload.decision === 'approve' ? 'approved' : 'rejected' })
  return http.post(`/annotations/${id}/reviews`, payload)
}
export function getAnnotationHistory(imageId: string) {
  if (USE_MOCK) return ok([{ id: 'ann-1', image_id: imageId, version: 1, mask_rle: null, is_empty: false, source: 'preannot', status: 'approved', annotator: { id: 'u-ann', display_name: '标注员' } }])
  return http.get(`/images/${imageId}/annotations`)
}

// ---- 模型 ----
export function getModels() {
  if (USE_MOCK) return ok([{ id: 'm-transunet', name: 'TransUNet', versions: 3 }])
  return http.get('/models')
}
export function getModelVersions(modelId: string) {
  if (USE_MOCK) return list<ModelVersion>(Mock.modelVersions)
  return http.get(`/models/${modelId}/versions`)
}
export function activateModelVersion(id: string) {
  if (USE_MOCK) return ok({ id, status: 'active' } as ModelVersion)
  return http.post(`/model-versions/${id}/activate`)
}

// ---- 推理 ----
export function createInference(payload: { image_id: string; model_version_id: string; params?: unknown }) {
  if (USE_MOCK) return ok({ id: 'inf-new', status: 'queued', ...payload } as InferenceTask)
  return http.post('/inference-tasks', payload)
}
export function getInference(id: string) {
  if (USE_MOCK) {
    const result = Mock.studies[0].latest_inference ?? null
    return ok({ id, image_id: 'img-006', model_version_id: 'mv-seed0', status: 'succeeded', result, elapsed_ms: result?.elapsed_ms } as InferenceTask)
  }
  return http.get(`/inference-tasks/${id}`)
}

// ---- 筛查 ----
export function getScreenTasks(params: { page?: number; page_size?: number; status?: string } = {}) {
  if (USE_MOCK) {
    let ts = Mock.screenTasks
    if (params.status) ts = ts.filter((t) => t.status === params.status)
    return list<ScreenTask>(ts, params.page, params.page_size)
  }
  return http.get('/screen-tasks', { params })
}
export function claimScreenTask(id: string) {
  if (USE_MOCK) return ok({ id, status: 'in_progress' } as ScreenTask)
  return http.post(`/screen-tasks/${id}/claim`)
}
export function getStudy(id: string) {
  if (USE_MOCK) return ok(Mock.studies.find((s) => s.id === id) ?? Mock.studies[0])
  return http.get(`/studies/${id}`)
}
export function reviewStudy(id: string, payload: { decision: string; comment?: string }) {
  if (USE_MOCK) return ok({ id, decision: payload.decision })
  return http.post(`/studies/${id}/reviews`, payload)
}

// ---- 报告 ----
export function getReportTemplates() {
  if (USE_MOCK) return list<ReportTemplate>(Mock.reportTemplates)
  return http.get('/report-templates')
}
export function createReport(payload: Partial<Report>) {
  if (USE_MOCK) return ok({ id: 'rp-new', status: 'draft', version: 1, ...payload } as Report)
  return http.post('/reports', payload)
}
export function getReport(id: string) {
  if (USE_MOCK) return ok(Mock.reports.find((r) => r.id === id) ?? Mock.reports[0])
  return http.get(`/reports/${id}`)
}
export function submitReport(id: string) {
  if (USE_MOCK) return ok({ id, status: 'pending_review' } as Report)
  return http.post(`/reports/${id}/submit`)
}
export function signReport(id: string, payload: { decision: string; comment?: string }) {
  if (USE_MOCK) return ok({ id, status: payload.decision === 'sign' ? 'signed' : 'rejected' } as Report)
  return http.post(`/reports/${id}/sign`, payload)
}
export function getReportPdf(id: string) {
  if (USE_MOCK) return ok({ url: null })
  return http.get(`/reports/${id}/pdf`)
}

// ---- 统计 ----
export function getStatsOverview() {
  if (USE_MOCK) return ok<StatsOverview>(Mock.statsOverview)
  return http.get('/stats/overview')
}
export function getStatsAnnotations() {
  if (USE_MOCK) return ok(Mock.statsAnnotations)
  return http.get('/stats/annotations')
}
export function getStatsModels() {
  if (USE_MOCK) return ok(Mock.statsModels)
  return http.get('/stats/models')
}
export function getStatsScreening() {
  if (USE_MOCK) return ok(Mock.statsScreening)
  return http.get('/stats/screening')
}

// ---- 审计 ----
export function getAuditLogs(params: { page?: number; page_size?: number; q?: string } = {}) {
  if (USE_MOCK) {
    let logs = Mock.auditLogs
    if (params.q) logs = logs.filter((l) => l.action.includes(params.q!) || l.object_type.includes(params.q!))
    return list<AuditLog>(logs, params.page, params.page_size)
  }
  return http.get('/audit-logs', { params })
}

// ---- 健康 ----
export function healthz() {
  if (USE_MOCK) return ok({ status: 'ok' })
  return http.get('/healthz')
}