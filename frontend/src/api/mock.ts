import type {
  AnnotationTask, ApiMeta, ApiResponse, AuditLog, Dataset, DatasetVersion, Image,
  ImportJob, ModelVersion, Report, ReportTemplate, RleMask, ScreenTask, Study, User
} from '@/types'

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms))

export function ok<T>(data: T, meta?: ApiMeta): Promise<ApiResponse<T>> {
  return delay().then(() => ({ data, meta: meta ?? { request_id: 'req_mock' } }))
}

export function list<T>(items: T[], page = 1, page_size = 20): Promise<ApiResponse<T[]>> {
  const total = items.length
  const start = (page - 1) * page_size
  return delay().then(() => ({
    data: items.slice(start, start + page_size),
    meta: { request_id: 'req_mock', page, page_size, total }
  }))
}

export function rleSize(rle: RleMask | null): [number, number] {
  return rle?.size ?? [256, 256]
}

function img(id: string, cls: 'benign' | 'malignant' | 'normal', status: Image['annotation_status'] = null): Image {
  return {
    id, study_id: null, format: 'png', width: 256, height: 256, channels: 1, bit_depth: 8,
    sha256: `sha256-${id}`.padEnd(64, '0'), class_label: cls, source: 'BUSI',
    mask_available: cls !== 'normal', annotation_status: status, thumbnail_url: null,
    created_at: '2026-10-30T09:00:00+08:00'
  }
}

export const Mock = {
  users: [
    { id: 'u-admin', username: 'admin', display_name: '管理员', status: 'active', roles: ['admin', 'data_engineer', 'screener'], last_login_at: '2026-11-01T20:10:00+08:00' },
    { id: 'u-ann', username: 'annotator', display_name: '标注员', status: 'active', roles: ['annotator'], last_login_at: '2026-11-01T19:00:00+08:00' },
    { id: 'u-scr', username: 'screener', display_name: '筛查医生', status: 'active', roles: ['screener'], last_login_at: '2026-11-02T08:30:00+08:00' },
    { id: 'u-rev', username: 'reviewer', display_name: '审核医师', status: 'active', roles: ['reviewer', 'screener'], last_login_at: '2026-11-02T09:00:00+08:00' },
    { id: 'u-eng', username: 'data_engineer', display_name: '数据工程师', status: 'active', roles: ['data_engineer'], last_login_at: '2026-10-31T15:00:00+08:00' }
  ] as User[],

  datasets: [
    { id: 'ds-busi', name: 'BUSI 乳腺超声', description: 'Al-Dhabyani et al., Data in Brief 2020，780 张', image_count: 780, created_at: '2026-10-30T09:00:00+08:00' }
  ] as Dataset[],

  datasetVersions: [
    { id: 'dv-1', dataset_id: 'ds-busi', version: 'v1-seed0', status: 'frozen', split_seed: 0, ratios: { train: 0.7, val: 0.15, test: 0.15 }, counts: { train: 546, val: 118, test: 116 }, manifest_url: null, frozen_at: '2026-10-30T10:00:00+08:00', created_at: '2026-10-30T09:30:00+08:00' }
  ] as DatasetVersion[],

  images: [
    img('img-001', 'malignant'), img('img-002', 'benign'), img('img-003', 'normal'),
    img('img-004', 'malignant'), img('img-005', 'benign'), img('img-006', 'malignant', 'approved'),
    img('img-007', 'benign', 'pending'), img('img-008', 'normal'), img('img-009', 'malignant'),
    img('img-010', 'benign', 'approved'), img('img-011', 'benign'), img('img-012', 'normal')
  ] as Image[],

  annotationTasks: [
    { id: 'at-1', image_id: 'img-006', dataset_version_id: 'dv-1', assignee: { id: 'u-ann', display_name: '标注员' }, status: 'approved', priority: 1, claimed_at: '2026-11-01T10:00:00+08:00', finished_at: '2026-11-01T11:00:00+08:00' },
    { id: 'at-2', image_id: 'img-007', dataset_version_id: 'dv-1', assignee: { id: 'u-ann', display_name: '标注员' }, status: 'in_progress', priority: 1, claimed_at: '2026-11-02T09:00:00+08:00' },
    { id: 'at-3', image_id: 'img-001', dataset_version_id: 'dv-1', assignee: null, status: 'pending', priority: 2 },
    { id: 'at-4', image_id: 'img-004', dataset_version_id: 'dv-1', assignee: null, status: 'pending', priority: 3 },
    { id: 'at-5', image_id: 'img-002', dataset_version_id: 'dv-1', assignee: { id: 'u-ann', display_name: '标注员' }, status: 'submitted', priority: 1, claimed_at: '2026-11-01T14:00:00+08:00' }
  ] as AnnotationTask[],

  modelVersions: [
    { id: 'mv-seed0', model_id: 'm-transunet', version: 's256rgb-seed0', weights_key: 'p1_transunet_seed0.pth', weights_sha256: 'a'.repeat(64), config: { model: 'transunet', size: 256, rgb: true, tta: true }, metrics: { dice: 0.7002, precision: 0.8416, recall: 0.7405, hd95: 106.8, seeds: 3 }, status: 'active' },
    { id: 'mv-seed1', model_id: 'm-transunet', version: 's256rgb-seed1', weights_key: 'p1_transunet_seed1.pth', weights_sha256: 'b'.repeat(64), config: { model: 'transunet', size: 256, rgb: true, tta: true }, metrics: { dice: 0.6943, precision: 0.8664, recall: 0.7377, hd95: 115.4, seeds: 3 }, status: 'candidate' },
    { id: 'mv-seed2', model_id: 'm-transunet', version: 's256rgb-seed2', weights_key: 'p1_transunet_seed2.pth', weights_sha256: 'c'.repeat(64), config: { model: 'transunet', size: 256, rgb: true, tta: true }, metrics: { dice: 0.7087, precision: 0.7896, recall: 0.7929, hd95: 96.2, seeds: 3 }, status: 'candidate' }
  ] as ModelVersion[],

  importJobs: [
    { id: 'job-1', dataset_id: 'ds-busi', status: 'completed', total: 780, success: 780, failed: 0, duplicate: 0, report: { warnings: 0 }, started_at: '2026-10-30T09:00:00+08:00', finished_at: '2026-10-30T09:12:00+08:00' }
  ] as ImportJob[],

  studies: [
    {
      id: 'study-1', study_no: 'US-20261102-001', modality: 'US', device: 'GE Logiq E9',
      study_date: '2026-11-02', indication: '左乳外上象限低回声结节，BI-RADS 4a', status: 'in_progress',
      patient: { id: 'p-1', name: '张某某', gender: 'F', birth_date: '1978-03-12', medical_no: 'M20261102001' },
      images: [img('img-006', 'malignant', 'approved')],
      latest_inference: { mask_url: null, mask_rle: null, prob_mean: 0.683, lesion_area_ratio: 0.0312, quality_flags: ['MULTI_LESION'], elapsed_ms: 1824 },
      timeline: [
        { at: '2026-11-02T09:00:00+08:00', actor: { id: 'u-scr', display_name: '筛查医生' }, action: 'study.created', detail: { by: 'admin' } },
        { at: '2026-11-02T09:05:00+08:00', actor: { id: 'u-scr', display_name: '筛查医生' }, action: 'screen_task.claimed' },
        { at: '2026-11-02T09:10:00+08:00', actor: null, action: 'inference.succeeded', detail: { elapsed_ms: 1824 } }
      ]
    },
    {
      id: 'study-2', study_no: 'US-20261102-002', modality: 'US', device: 'Philips EPIQ 7',
      study_date: '2026-11-02', indication: '右乳囊肿随访', status: 'done',
      patient: { id: 'p-2', name: '李某某', gender: 'F', birth_date: '1985-07-20', medical_no: 'M20261102002' },
      images: [img('img-010', 'benign', 'approved')],
      latest_inference: { mask_url: null, mask_rle: null, prob_mean: 0.121, lesion_area_ratio: 0.0021, quality_flags: ['EMPTY_MASK'], elapsed_ms: 1510 },
      timeline: [
        { at: '2026-11-02T08:40:00+08:00', actor: { id: 'u-rev', display_name: '审核医师' }, action: 'study.created' },
        { at: '2026-11-02T08:55:00+08:00', actor: { id: 'u-rev', display_name: '审核医师' }, action: 'screen_task.claimed' }
      ]
    }
  ] as Study[],

  screenTasks: [
    { id: 'st-1', study_id: 'study-1', assignee: { id: 'u-scr', display_name: '筛查医生' }, status: 'in_progress', priority: 1, claimed_at: '2026-11-02T09:05:00+08:00' },
    { id: 'st-2', study_id: 'study-2', assignee: { id: 'u-rev', display_name: '审核医师' }, status: 'done', priority: 2, claimed_at: '2026-11-02T08:55:00+08:00', finished_at: '2026-11-02T09:20:00+08:00' },
    { id: 'st-3', study_id: 'study-1', assignee: null, status: 'pending', priority: 1 }
  ] as ScreenTask[],

  reportTemplates: [
    { id: 'rt-1', name: '乳腺超声标准报告', body: '<h3>乳腺超声检查报告</h3><p>{{findings}}</p><p>印象：{{impression}}</p><p>建议：{{recommendation}}</p>', variables: ['findings', 'impression', 'recommendation'], active: true }
  ] as ReportTemplate[],

  reports: [
    {
      id: 'rp-1', study_id: 'study-2', inference_result_id: null, template_id: 'rt-1',
      content: { findings: '右乳可见一囊性无回声区，边界清晰。', impression: 'BI-RADS 2，良性囊肿。', recommendation: '建议年度常规随访。' },
      status: 'signed', author: { id: 'u-rev', display_name: '审核医师' }, reviewer: { id: 'u-rev', display_name: '审核医师' },
      version: 1, signed_at: '2026-11-02T09:20:00+08:00', pdf_url: null, created_at: '2026-11-02T09:15:00+08:00'
    },
    {
      id: 'rp-2', study_id: 'study-1', inference_result_id: null, template_id: 'rt-1',
      content: { findings: '左乳外上象限见低回声结节，边界欠清，形态不规则。', impression: 'BI-RADS 4a，建议穿刺活检。', recommendation: '建议超声引导下穿刺活检。' },
      status: 'draft', author: { id: 'u-scr', display_name: '筛查医生' }, reviewer: null,
      version: 1, signed_at: null, pdf_url: null, created_at: '2026-11-02T09:40:00+08:00'
    }
  ] as Report[],

  auditLogs: [
    { id: 1, actor: { id: 'u-admin', display_name: '管理员' }, action: 'user.login', object_type: 'user', object_id: 'u-admin', ip: '127.0.0.1', created_at: '2026-11-02T08:00:00+08:00' },
    { id: 2, actor: { id: 'u-ann', display_name: '标注员' }, action: 'annotation.submit', object_type: 'annotation', object_id: 'ann-1', created_at: '2026-11-02T08:12:00+08:00' },
    { id: 3, actor: { id: 'u-rev', display_name: '审核医师' }, action: 'report.sign', object_type: 'report', object_id: 'rp-1', created_at: '2026-11-02T09:20:00+08:00' },
    { id: 4, actor: { id: 'u-scr', display_name: '筛查医生' }, action: 'screen_task.claim', object_type: 'screen_task', object_id: 'st-1', created_at: '2026-11-02T09:05:00+08:00' },
    { id: 5, actor: { id: 'u-admin', display_name: '管理员' }, action: 'dataset_version.freeze', object_type: 'dataset_version', object_id: 'dv-1', created_at: '2026-10-30T10:00:00+08:00' }
  ] as AuditLog[],

  statsOverview: {
    images: 780, annotations_approved: 42, dataset_versions: 2, model_versions: 3,
    screen_tasks: 12, reports_signed: 5, positive_rate: 0.42, avg_review_seconds: 186
  },

  statsAnnotations: {
    definition: 'positive = lesion_area_ratio > 0 且复核结论为阳性',
    by_class: { benign: 437, malignant: 210, normal: 133 },
    by_status: { pending: 120, in_progress: 25, submitted: 10, approved: 42, rejected: 3 },
    completion_rate: 0.18
  },

  statsModels: {
    versions: [
      { version: 'baseline', dice: 0.7002, precision: 0.8416, recall: 0.7405, hd95: 106.8, seeds: [0.7293, 0.7012, 0.6701] },
      { version: 'A2+A1', dice: 0.6943, precision: 0.8664, recall: 0.7377, hd95: 115.4, seeds: [0.724, 0.682, 0.677] },
      { version: 'A2+A1+A3', dice: 0.7087, precision: 0.7896, recall: 0.7929, hd95: 96.2, seeds: [0.7318, 0.704, 0.69] }
    ]
  },

  statsScreening: {
    definition: 'positive = lesion_area_ratio > 0 且复核结论为阳性',
    by_status: { pending: 4, in_progress: 3, done: 5 },
    by_decision: { accept: 8, modify: 1, reject: 1 },
    avg_review_seconds: 186
  }
}