<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { DatasetVersion, EvaluationJob, InferenceBatch, Model, ModelVersion } from '@/types'
import * as api from '@/api'
import { usePoll } from '@/composables/usePoll'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const auth = useAuthStore()
const { poll } = usePoll()
const canManage = computed(() => auth.hasRole('admin'))

const models = ref<Model[]>([])
const versions = ref<ModelVersion[]>([])
const datasets = ref<DatasetVersion[]>([])
const evaluations = ref<EvaluationJob[]>([])

const registerVisible = ref(false)
const registerSaving = ref(false)
const registerForm = reactive({
  model_id: '',
  version: '',
  weights_key: '',
  weights_sha256: '',
  config: JSON.stringify({
    size: 256,
    in_ch: 3,
    rgb: true,
    tta: true,
    scales: [1.0],
    threshold: 0.5,
    postproc: true,
    min_area: 0.001,
    seed: 0,
    transunet_commit: '02ef0010b36eb8328b5e689eadaf613602edf9b8'
  }, null, 2),
  metrics: ''
})

const evalVisible = ref(false)
const evalSaving = ref(false)
const evalForm = reactive({ model_version_id: '', dataset_version_id: '' })

const batchVisible = ref(false)
const batchSaving = ref(false)
const batchForm = reactive({ dataset_version_id: '', model_version_id: '', threshold: 0.5 })
const batches = ref<InferenceBatch[]>([])
const converting = ref('')

const frozenVersions = computed(() => datasets.value.filter((v) => v.status === 'frozen'))

function metric(v: ModelVersion, key: string) {
  const metrics = v.metrics as Record<string, any> | null | undefined
  return metrics?.['A2+A1']?.[key] ?? metrics?.[key]
}

function versionLabel(id: string) {
  const hit = versions.value.find((v) => v.id === id)
  return hit ? hit.version : id.slice(0, 8)
}

function datasetLabel(id: string) {
  const hit = datasets.value.find((v) => v.id === id)
  return hit ? hit.version : id.slice(0, 8)
}

async function loadEvaluations() {
  const resp = await api.getEvaluations({ page_size: 20 }) as { data: EvaluationJob[] }
  evaluations.value = resp.data
}

async function load() {
  const resp = await api.getModels() as { data: Model[] }
  models.value = resp.data ?? []
  versions.value = models.value.flatMap((m) => m.versions ?? [])
  const dv = await api.getDatasetVersions() as { data: DatasetVersion[] }
  datasets.value = dv.data ?? []
  registerForm.model_id = models.value[0]?.id ?? ''
  if (canManage.value) await loadEvaluations()
}

async function activate(v: ModelVersion) {
  if (v.status === 'active') return
  const resp = await api.activateModelVersion(v.id) as { data: ModelVersion & { warning?: string } }
  ElMessage.success(`已启用 ${v.version}`)
  if (resp.data.warning) ElMessage.warning(resp.data.warning)
  versions.value.forEach((x) => {
    if (x.model_id !== v.model_id) return
    if (x.id === v.id) x.status = 'active'
    else if (x.status === 'active') x.status = 'archived'
  })
}

function openRegister() {
  registerForm.version = ''
  registerForm.weights_key = ''
  registerForm.weights_sha256 = ''
  registerForm.metrics = ''
  registerVisible.value = true
}

async function submitRegister() {
  let config: Record<string, unknown>
  let metrics: Record<string, unknown> | null = null
  try {
    config = JSON.parse(registerForm.config)
  } catch {
    ElMessage.error('配置不是合法 JSON')
    return
  }
  if (registerForm.metrics.trim()) {
    try {
      metrics = JSON.parse(registerForm.metrics)
    } catch {
      ElMessage.error('指标不是合法 JSON')
      return
    }
  }
  registerSaving.value = true
  try {
    await api.registerModelVersion(registerForm.model_id, {
      version: registerForm.version,
      weights_key: registerForm.weights_key,
      weights_sha256: registerForm.weights_sha256,
      config,
      metrics
    })
    ElMessage.success('模型版本已注册（候选）')
    registerVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '注册失败')
  } finally {
    registerSaving.value = false
  }
}

function openEvaluation() {
  evalForm.model_version_id = versions.value.find((v) => v.status === 'active')?.id ?? versions.value[0]?.id ?? ''
  evalForm.dataset_version_id = frozenVersions.value[0]?.id ?? ''
  evalVisible.value = true
}

async function submitEvaluation() {
  if (!evalForm.model_version_id || !evalForm.dataset_version_id) {
    ElMessage.warning('请选择模型版本与冻结数据集版本')
    return
  }
  evalSaving.value = true
  try {
    const created = await api.createEvaluation({ ...evalForm }) as { data: { evaluation_id: string } }
    ElMessage.success('评估任务已排队')
    evalVisible.value = false
    await poll(
      async () => (await api.getEvaluation(created.data.evaluation_id) as { data: EvaluationJob }).data,
      (job) => job.status === 'succeeded' || job.status === 'failed',
      { interval: 2000, attempts: 30 }
    )
    await loadEvaluations()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '创建评估失败')
  } finally {
    evalSaving.value = false
  }
}

function openBatch() {
  batchForm.dataset_version_id = frozenVersions.value[0]?.id ?? ''
  batchForm.model_version_id = versions.value.find((v) => v.status === 'active')?.id ?? versions.value[0]?.id ?? ''
  batchForm.threshold = 0.5
  batchVisible.value = true
}

async function submitBatch() {
  if (!batchForm.dataset_version_id || !batchForm.model_version_id) {
    ElMessage.warning('请选择数据集版本与模型版本')
    return
  }
  batchSaving.value = true
  try {
    const created = await api.createInferenceBatch({
      dataset_version_id: batchForm.dataset_version_id,
      model_version_id: batchForm.model_version_id,
      params: { threshold: batchForm.threshold }
    }) as { data: { batch_id: string; total: number } }
    const batch: InferenceBatch = {
      id: created.data.batch_id,
      dataset_version_id: batchForm.dataset_version_id,
      model_version_id: batchForm.model_version_id,
      status: 'queued',
      total: created.data.total,
      succeeded: 0,
      failed: 0,
      progress: 0
    }
    batches.value.unshift(batch)
    batchVisible.value = false
    ElMessage.success(`批量推理已提交，共 ${batch.total} 张`)
    pollBatch(batch)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '提交批量推理失败')
  } finally {
    batchSaving.value = false
  }
}

async function pollBatch(batch: InferenceBatch) {
  await poll(
    async () => {
      const data = (await api.getInferenceBatch(batch.id) as { data: InferenceBatch }).data
      Object.assign(batch, data)
      return data
    },
    (data) => ['succeeded', 'partial', 'failed'].includes(data.status),
    { interval: 2000, attempts: 60 }
  )
}

async function convertBatch(batch: InferenceBatch) {
  converting.value = batch.id
  try {
    const resp = await api.batchToAnnotations(batch.id) as { data: { created: number; skipped: number } }
    ElMessage.success(`已生成 ${resp.data.created} 条预标注草稿，跳过 ${resp.data.skipped} 条`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '转标注草稿失败')
  } finally {
    converting.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">模型与指标</h3>
      <div v-if="canManage">
        <el-button @click="openRegister">注册版本</el-button>
        <el-button @click="openEvaluation">离线评估</el-button>
        <el-button type="primary" @click="openBatch">批量推理</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table :data="versions" border stripe>
        <el-table-column prop="version" label="版本" width="160" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="Dice" width="110">
          <template #default="{ row }">{{ metric(row, 'dice')?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="精确率" width="110">
          <template #default="{ row }">{{ metric(row, 'precision')?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="召回率" width="110">
          <template #default="{ row }">{{ metric(row, 'recall')?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="HD95(px)" width="110">
          <template #default="{ row }">{{ metric(row, 'hd95') }}</template>
        </el-table-column>
        <el-table-column prop="weights_sha256" label="权重 SHA256" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="canManage && row.status !== 'active'" size="small" type="primary" @click="activate(row)">启用</el-button>
            <span v-else-if="row.status === 'active'" class="muted">在线版本</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="canManage" shadow="never" style="margin-top: 16px">
      <template #header>离线评估</template>
      <el-table :data="evaluations" border stripe>
        <el-table-column label="模型版本" width="150">
          <template #default="{ row }">{{ versionLabel(row.model_version_id) }}</template>
        </el-table-column>
        <el-table-column label="数据集版本" width="150">
          <template #default="{ row }">{{ datasetLabel(row.dataset_version_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="Dice" width="110">
          <template #default="{ row }">{{ (row.metrics?.['A2+A1']?.dice ?? row.metrics?.dice)?.toFixed?.(4) ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="HD95" width="110">
          <template #default="{ row }">{{ row.metrics?.['A2+A1']?.hd95 ?? row.metrics?.hd95 ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="完成时间">
          <template #default="{ row }">{{ row.finished_at || '—' }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!evaluations.length" description="尚无评估任务" :image-size="60" />
    </el-card>

    <el-card v-if="canManage" shadow="never" style="margin-top: 16px">
      <template #header>批量推理进度</template>
      <el-table :data="batches" border stripe>
        <el-table-column prop="id" label="批次 ID" width="120" />
        <el-table-column label="数据集版本" width="150">
          <template #default="{ row }">{{ datasetLabel(row.dataset_version_id) }}</template>
        </el-table-column>
        <el-table-column label="模型版本" width="150">
          <template #default="{ row }">{{ versionLabel(row.model_version_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="进度">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.progress ?? 0) * 100)" :status="row.status === 'failed' ? 'exception' : undefined" />
            <span class="muted">成功 {{ row.succeeded }} / 失败 {{ row.failed }} / 共 {{ row.total }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button
              size="small"
              :disabled="!['succeeded', 'partial'].includes(row.status)"
              :loading="converting === row.id"
              @click="convertBatch(row)"
            >转标注草稿</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!batches.length" description="本次会话尚无批量任务" :image-size="60" />
    </el-card>

    <el-dialog v-model="registerVisible" title="注册模型版本" width="620px">
      <el-form label-width="110px">
        <el-form-item label="所属模型">
          <el-select v-model="registerForm.model_id" style="width: 100%">
            <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="registerForm.version" placeholder="如 v2-seed0" />
        </el-form-item>
        <el-form-item label="权重对象键">
          <el-input v-model="registerForm.weights_key" placeholder="models/<sha256>.pth" />
        </el-form-item>
        <el-form-item label="权重 SHA256">
          <el-input v-model="registerForm.weights_sha256" placeholder="64 位小写十六进制" />
        </el-form-item>
        <el-form-item label="配置 JSON">
          <el-input v-model="registerForm.config" type="textarea" :rows="8" />
        </el-form-item>
        <el-form-item label="指标 JSON">
          <el-input v-model="registerForm.metrics" type="textarea" :rows="4" placeholder="可选，登记的自报指标" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="registerVisible = false">取消</el-button>
        <el-button type="primary" :loading="registerSaving" @click="submitRegister">注册</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="evalVisible" title="离线评估" width="480px">
      <el-form label-width="120px">
        <el-form-item label="模型版本">
          <el-select v-model="evalForm.model_version_id" style="width: 100%">
            <el-option v-for="v in versions" :key="v.id" :label="`${v.version} (${v.status})`" :value="v.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据集版本">
          <el-select v-model="evalForm.dataset_version_id" style="width: 100%" placeholder="仅冻结版本可选">
            <el-option v-for="v in frozenVersions" :key="v.id" :label="v.version" :value="v.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="muted" style="font-size: 12px">评估在冻结测试集上运行，结果写入评估列表，不会覆盖模型登记指标。</div>
      <template #footer>
        <el-button @click="evalVisible = false">取消</el-button>
        <el-button type="primary" :loading="evalSaving" @click="submitEvaluation">开始评估</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchVisible" title="批量推理" width="480px">
      <el-form label-width="120px">
        <el-form-item label="数据集版本">
          <el-select v-model="batchForm.dataset_version_id" style="width: 100%" placeholder="仅冻结版本可选">
            <el-option v-for="v in frozenVersions" :key="v.id" :label="v.version" :value="v.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型版本">
          <el-select v-model="batchForm.model_version_id" style="width: 100%">
            <el-option v-for="v in versions" :key="v.id" :label="`${v.version} (${v.status})`" :value="v.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值">
          <el-input-number v-model="batchForm.threshold" :min="0.05" :max="0.95" :step="0.05" />
        </el-form-item>
      </el-form>
      <div class="muted" style="font-size: 12px">对所选冻结版本的全部影像创建推理任务，结果可在导入/标注流程中复用。</div>
      <template #footer>
        <el-button @click="batchVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSaving" @click="submitBatch">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
.muted { color: #909399; font-size: 12px; }
</style>
