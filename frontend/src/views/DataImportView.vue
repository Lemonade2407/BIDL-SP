<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { Dataset, ImportJob, ImportJobReport } from '@/types'
import * as api from '@/api'
import { usePoll } from '@/composables/usePoll'

const datasets = ref<Dataset[]>([])
const datasetId = ref('')
const file = ref<File | null>(null)
const jobId = ref('')
const { poll } = usePoll()
const job = reactive({
  status: 'idle',
  progress: 0,
  total: 0,
  success: 0,
  failed: 0,
  duplicate: 0,
  report: null as ImportJobReport | null
})

const warnings = computed(() => job.report?.warnings ?? [])
const failures = computed(() => job.report?.failures ?? [])

onMounted(async () => {
  const resp = await api.getDatasets()
  datasets.value = (resp as { data: Dataset[] }).data
  if (datasets.value.length) datasetId.value = datasets.value[0].id
})

function onFileChange(f: { raw: File }) {
  file.value = f.raw
}

function applyJob(data: ImportJob) {
  job.status = data.status
  job.total = data.total
  job.success = data.success
  job.failed = data.failed
  job.duplicate = data.duplicate
  job.report = data.report ?? null
  const handled = data.success + data.failed + data.duplicate
  job.progress = data.total ? Math.min(100, Math.round((handled / data.total) * 100)) : 0
}

async function track(id: string) {
  await poll(
    async () => {
      const data = (await api.getImport(id) as { data: ImportJob }).data
      applyJob(data)
      return data
    },
    (data) => data.status === 'completed' || data.status === 'failed',
    { interval: 1000, attempts: 60 }
  )
}

async function onImport() {
  if (!file.value || !datasetId.value) {
    ElMessage.warning('请选择数据集并上传 ZIP 文件')
    return
  }
  job.status = 'validating'
  job.progress = 0
  job.total = job.success = job.failed = job.duplicate = 0
  job.report = null
  try {
    const resp = await api.createImport(datasetId.value, file.value) as {
      data: { job_id?: string; id?: string }
    }
    const id = resp.data.job_id || resp.data.id
    if (!id) throw new Error('导入任务未返回 job_id')
    jobId.value = id
    await track(id)
    if (job.status === 'completed') {
      ElMessage.success(`导入完成：成功 ${job.success}，重复 ${job.duplicate}，失败 ${job.failed}`)
    } else {
      const report = job.report as ImportJobReport | null
      ElMessage.error(report?.error || '导入未完成，请查看导入报告')
    }
  } catch (error: any) {
    job.status = 'failed'
    ElMessage.error(error?.response?.data?.message || error?.message || '导入失败')
  }
}

function downloadReport() {
  if (!job.report) return
  const payload = {
    job_id: jobId.value,
    status: job.status,
    total: job.total,
    success: job.success,
    failed: job.failed,
    duplicate: job.duplicate,
    report: job.report
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `import-report-${jobId.value || Date.now()}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10000)
}
</script>

<template>
  <div>
    <h3 class="page-title">数据接入</h3>
    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>上传 BUSI 数据集</template>
          <el-form label-position="top">
            <el-form-item label="目标数据集">
              <el-select v-model="datasetId" placeholder="选择数据集" style="width: 100%">
                <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="ZIP 压缩包">
              <el-upload drag :auto-upload="false" :limit="1" accept=".zip" :on-change="onFileChange" style="width: 100%">
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖拽 ZIP 到此处，或<em>点击选择</em></div>
                <template #tip>
                  <div class="el-upload__tip">支持 .zip；解压后 ≤ 2GB、文件数 ≤ 2000</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-button type="primary" @click="onImport">开始导入</el-button>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>导入进度</span>
              <el-button v-if="job.report" size="small" @click="downloadReport">下载 JSON 报告</el-button>
            </div>
          </template>
          <el-empty v-if="job.status === 'idle'" description="尚未开始导入" :image-size="80" />
          <template v-else>
            <el-steps :active="['idle','pending','validating','importing','completed'].indexOf(job.status)" finish-status="success" align-center>
              <el-step title="校验" />
              <el-step title="导入" />
              <el-step title="完成" />
            </el-steps>
            <el-progress :percentage="job.progress" :status="job.status === 'completed' ? 'success' : job.status === 'failed' ? 'exception' : undefined" style="margin: 24px 0" />
            <el-descriptions :column="4" border size="small">
              <el-descriptions-item label="总数">{{ job.total }}</el-descriptions-item>
              <el-descriptions-item label="成功">{{ job.success }}</el-descriptions-item>
              <el-descriptions-item label="失败">{{ job.failed }}</el-descriptions-item>
              <el-descriptions-item label="重复">{{ job.duplicate }}</el-descriptions-item>
            </el-descriptions>
            <el-alert v-if="job.report?.error" type="error" :closable="false" :title="job.report.error" style="margin-top: 12px" />
          </template>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px" v-if="failures.length || warnings.length">
      <el-col :span="12" v-if="failures.length">
        <el-card shadow="never">
          <template #header>失败明细（{{ failures.length }}）</template>
          <el-table :data="failures" border size="small" max-height="320">
            <el-table-column prop="file" label="文件" show-overflow-tooltip />
            <el-table-column prop="reason" label="原因" width="180" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12" v-if="warnings.length">
        <el-card shadow="never">
          <template #header>告警明细（{{ warnings.length }}）</template>
          <el-table :data="warnings" border size="small" max-height="320">
            <el-table-column prop="file" label="文件" show-overflow-tooltip />
            <el-table-column label="原因" width="220">
              <template #default="{ row }">
                {{ row.reason }}
                <el-tag v-if="row.class_conflict" type="warning" size="small" style="margin-left: 4px">类别冲突</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
