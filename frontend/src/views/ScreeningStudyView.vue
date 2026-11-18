<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Annotation, Image, InferenceTask, Report, ReportTemplate, RleMask, Study } from '@/types'
import * as api from '@/api'
import { usePoll } from '@/composables/usePoll'
import ImageViewer from '@/components/ImageViewer.vue'
import MaskCanvas from '@/components/MaskCanvas.vue'
import MaskOverlay from '@/components/MaskOverlay.vue'
import ResultPanel from '@/components/ResultPanel.vue'

const route = useRoute()
const router = useRouter()
const { poll } = usePoll()
const study = ref<Study | null>(null)
const view = reactive({ scale: 1, tx: 0, ty: 0 })
const analysisState = ref<'idle' | 'running' | 'done'>('idle')
const overlayOpacity = ref(0.6)
const imageIndex = ref(0)
const continuous = ref(true)
const submitting = ref(false)

const modifyVisible = ref(false)
const modifySaving = ref(false)
const modifyRle = ref<RleMask | null>(null)
const modifyComment = ref('')
const modifyTool = ref<'brush' | 'eraser' | 'polygon'>('brush')
const modifyBrush = ref(4)
const modifyView = reactive({ scale: 1, tx: 0, ty: 0 })
const maskCanvasRef = ref<InstanceType<typeof MaskCanvas> | null>(null)
const rejectVisible = ref(false)
const rejectReason = ref('')
const rejectFollowUp = ref<'' | 're_infer' | 'manual' | 'transfer'>('')

const currentImage = computed<Image | null>(() => {
  const images = study.value?.images ?? []
  return images[imageIndex.value] ?? images[0] ?? null
})

onMounted(async () => {
  await load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

watch(
  () => route.params.id,
  () => {
    view.scale = 1
    view.tx = 0
    view.ty = 0
    overlayOpacity.value = 0.6
    analysisState.value = 'idle'
    load()
  }
)

async function load() {
  const resp = await api.getStudy(route.params.id as string)
  study.value = (resp as { data: Study }).data
  imageIndex.value = 0
  if (study.value.latest_inference) analysisState.value = 'done'
}

async function referenceMask(image: Image): Promise<RleMask | null> {
  try {
    const resp = await api.getAnnotationHistory(image.id) as { data: Annotation[] }
    const approved = resp.data.filter((item) => item.status === 'approved')
    if (approved.length) return approved[0].mask_rle ?? null
  } catch {
    // 网络异常时回退到推理掩膜
  }
  return study.value?.latest_inference?.mask_rle ?? null
}

function switchImage(index: number) {
  if (!study.value || index === imageIndex.value) return
  imageIndex.value = index
  view.scale = 1
  view.tx = 0
  view.ty = 0
}

async function runAnalysis() {
  const image = currentImage.value
  if (!image) {
    ElMessage.warning('该检查没有可分析的影像')
    return
  }
  analysisState.value = 'running'
  try {
    const created = await api.createInference({ image_id: image.id }) as { data: { task_id?: string; id?: string } }
    const taskId = created.data.task_id || created.data.id
    if (!taskId) throw new Error('推理任务未返回 task_id')

    const outcome = await poll(
      async () => (await api.getInference(taskId) as { data: InferenceTask }).data,
      (task) => task.status === 'succeeded' || task.status === 'failed',
      { interval: 1000, attempts: 60 }
    )
    const task = outcome.value
    if (!outcome.done || !task) throw new Error('推理超时，请稍后重试')
    if (task.status === 'failed') {
      const detail: any = task.error
      throw new Error(detail?.message || detail || '推理失败')
    }
    study.value!.latest_inference = task.result ?? null
    analysisState.value = 'done'
    ElMessage.success('推理完成')
  } catch (error: any) {
    analysisState.value = 'idle'
    ElMessage.error(error?.response?.data?.message || error?.message || '推理失败')
  }
}

async function openModify() {
  const image = currentImage.value
  if (!image) {
    ElMessage.warning('该检查没有可修改的影像')
    return
  }
  modifyRle.value = await referenceMask(image)
  modifyComment.value = ''
  modifyTool.value = 'brush'
  modifyView.scale = 1
  modifyView.tx = 0
  modifyView.ty = 0
  modifyVisible.value = true
}

function onModifyMask(v: RleMask | null) {
  modifyRle.value = v
}

async function submitModify() {
  const image = currentImage.value
  if (!study.value || !image) return
  const hasForeground = !!modifyRle.value?.counts.some((count, index) => index % 2 === 1 && count > 0)
  const mask = modifyRle.value ?? {
    size: [image.height, image.width] as [number, number],
    counts: [image.height * image.width]
  }
  modifySaving.value = true
  try {
    await api.reviewStudy(study.value.id, {
      decision: 'modify',
      image_id: image.id,
      mask_rle: mask,
      is_empty: !hasForeground,
      comment: modifyComment.value || undefined
    })
    modifyVisible.value = false
    ElMessage.success('掩膜修改已提交，检查复核完成')
    await nextCase()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '提交修改失败')
  } finally {
    modifySaving.value = false
  }
}

async function review(decision: string) {
  if (!study.value || submitting.value) return
  if (decision === 'modify') {
    await openModify()
    return
  }
  if (decision === 'reject') {
    openReject()
    return
  }
  await ElMessageBox.confirm('确认提交复核结论？', '复核确认', { type: 'warning' })
  submitting.value = true
  try {
    await api.reviewStudy(study.value.id, { decision })
    ElMessage.success('复核已提交')
    await nextCase()
  } finally {
    submitting.value = false
  }
}

async function nextCase() {
  if (!continuous.value) {
    router.push('/screening/worklist')
    return
  }
  try {
    const resp = await api.getScreenTasks({ status: 'pending', page_size: 1, sort: '-priority' }) as {
      data: { id: string; study_id: string }[]
    }
    const next = resp.data[0]
    if (!next) {
      ElMessage.info('没有更多待处理检查')
      router.push('/screening/worklist')
      return
    }
    await api.claimScreenTask(next.id)
    ElMessage.success('已提交，自动进入下一例')
    router.replace(`/screening/studies/${next.study_id}`)
  } catch {
    router.push('/screening/worklist')
  }
}

function onKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  if (modifyVisible.value) return
  const key = event.key.toLowerCase()
  if (key === 'a') review('accept')
  else if (key === 'r') review('reject')
  else if (key === 'm') review('modify')
  else if (key === 'arrowleft') switchImage(Math.max(0, imageIndex.value - 1))
  else if (key === 'arrowright') switchImage(Math.min((study.value?.images.length ?? 1) - 1, imageIndex.value + 1))
}

function openReject() {
  rejectReason.value = ''
  rejectFollowUp.value = ''
  rejectVisible.value = true
}

async function submitReject() {
  if (!study.value) return
  if (!rejectReason.value.trim()) {
    ElMessage.warning('请填写驳回原因')
    return
  }
  submitting.value = true
  try {
    await api.reviewStudy(study.value.id, {
      decision: 'reject',
      comment: rejectReason.value,
      follow_up: rejectFollowUp.value ? true : false
    })
    rejectVisible.value = false
    ElMessage.success('已驳回，任务已退回待处理')
    router.push('/screening/worklist')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '驳回失败')
  } finally {
    submitting.value = false
  }
}
async function toReport() {
  if (!study.value) return
  try {
    const templates = await api.getReportTemplates() as { data: ReportTemplate[] }
    const template = templates.data.find((item) => item.active)
    if (!template) {
      ElMessage.warning('没有启用的报告模板')
      return
    }
    const resp = await api.createReport({
      study_id: study.value.id,
      template_id: template.id,
      content: { findings: '', impression: '', recommendation: '' }
    }) as { data: Report }
    router.push(`/reports/${resp.data.id}`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '创建报告失败')
  }
}
</script>

<template>
  <div>
    <h3 class="page-title">检查复核 · {{ study?.study_no }}</h3>
    <el-card shadow="never" v-if="study">
      <el-descriptions :column="4" border size="small" style="margin-bottom: 12px">
        <el-descriptions-item label="患者编号">{{ study.patient.patient_no }}</el-descriptions-item>
        <el-descriptions-item label="性别">{{ study.patient.gender }}</el-descriptions-item>
        <el-descriptions-item label="出生年份">{{ study.patient.birth_year || '—' }}</el-descriptions-item>
        <el-descriptions-item label="设备">{{ study.device || '—' }}</el-descriptions-item>
        <el-descriptions-item label="检查日期">{{ study.study_date }}</el-descriptions-item>
        <el-descriptions-item label="申请指征" :span="4">{{ study.indication || '—' }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="study.images.length > 1" class="thumbs">
        <button
          v-for="(image, index) in study.images"
          :key="image.id"
          type="button"
          class="thumb"
          :class="{ active: index === imageIndex }"
          @click="switchImage(index)"
        >
          影像 {{ index + 1 }}<span class="muted"> · {{ image.class_label || '—' }}</span>
        </button>
      </div>
      <div class="layout">
        <div class="viewer-box">
          <ImageViewer :image="currentImage" :view="view" />
          <MaskOverlay
            v-if="currentImage"
            :rle="analysisState === 'done' ? study.latest_inference?.mask_rle ?? null : null"
            :image-width="currentImage.width"
            :image-height="currentImage.height"
            :view="view"
            :opacity="overlayOpacity"
          />
        </div>
        <div class="side">
          <ResultPanel :result="analysisState === 'done' ? (study.latest_inference ?? null) : null" />
          <el-card shadow="never" style="margin-top: 12px">
            <template #header>复核操作</template>
            <div class="actions">
              <el-slider v-model="overlayOpacity" :min="0" :max="1" :step="0.05" show-input size="small" style="width: 100%" />
              <div class="opacity-label">掩膜透明度</div>
              <el-button type="primary" :loading="analysisState === 'running'" @click="runAnalysis">
                {{ analysisState === 'running' ? '推理中…' : '模型分析' }}
              </el-button>
              <el-button type="success" :loading="submitting" @click="review('accept')">接受 A</el-button>
              <el-button type="warning" @click="review('modify')">修改 M</el-button>
              <el-button type="danger" @click="review('reject')">驳回 R</el-button>
              <el-button @click="toReport">撰写报告</el-button>
            </div>
            <div class="continuous">
              <el-switch v-model="continuous" size="small" />
              <span class="muted">连续阅片：提交后自动进入下一例</span>
            </div>
            <div class="muted shortcut">快捷键：A 接受 · M 修改 · R 驳回 · ←/→ 切换影像</div>
          </el-card>
        </div>
      </div>
      <el-card shadow="never" style="margin-top: 12px">
        <template #header>操作时间线</template>
        <el-timeline>
          <el-timeline-item v-for="(t, i) in study.timeline" :key="i" :timestamp="t.at" placement="top">
            <span>{{ t.action }}</span>
            <span v-if="t.actor" class="muted"> · {{ t.actor.display_name }}</span>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </el-card>

    <el-dialog v-model="modifyVisible" title="修改掩膜" width="920px" destroy-on-close>
      <div class="modify-toolbar">
        <el-radio-group v-model="modifyTool" size="small">
          <el-radio-button value="brush">画笔</el-radio-button>
          <el-radio-button value="eraser">橡皮</el-radio-button>
          <el-radio-button value="polygon">多边形</el-radio-button>
        </el-radio-group>
        <el-text size="small">画笔大小</el-text>
        <el-slider v-model="modifyBrush" :min="1" :max="16" style="width: 120px" />
        <el-button size="small" @click="maskCanvasRef?.undo()">撤销</el-button>
        <el-button size="small" @click="maskCanvasRef?.clear()">清空</el-button>
        <el-button v-if="modifyTool === 'polygon'" size="small" type="warning" @click="maskCanvasRef?.closePolygon()">
          闭合多边形
        </el-button>
      </div>
      <div class="modify-canvas">
        <ImageViewer :image="currentImage" :view="modifyView" />
        <MaskCanvas
          v-if="currentImage"
          ref="maskCanvasRef"
          :image-width="currentImage.width"
          :image-height="currentImage.height"
          :view="modifyView"
          :tool="modifyTool"
          :brush-size="modifyBrush"
          :model-value="modifyRle"
          @update:model-value="onModifyMask"
        />
      </div>
      <el-input
        v-model="modifyComment"
        type="textarea"
        :rows="2"
        placeholder="修改说明（可留空）"
        style="margin-top: 12px"
      />
      <template #footer>
        <el-button @click="modifyVisible = false">取消</el-button>
        <el-button type="primary" :loading="modifySaving" @click="submitModify">提交修改并完成复核</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="rejectVisible" title="驳回检查" width="520px">
      <el-form label-position="top">
        <el-form-item label="驳回原因（必填）">
          <el-input v-model="rejectReason" type="textarea" :rows="3" placeholder="说明驳回原因…" />
        </el-form-item>
        <el-form-item label="后续跟进方式">
          <el-radio-group v-model="rejectFollowUp">
            <el-radio value="re_infer">重跑推理</el-radio>
            <el-radio value="manual">人工标注替代</el-radio>
            <el-radio value="transfer">改派人工</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="submitting" @click="submitReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.layout { display: flex; gap: 12px; }
.viewer-box { flex: 1; position: relative; height: 480px; }
.side { width: 320px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions .el-button { flex: 1; margin-left: 0; }
.opacity-label { width: 100%; font-size: 12px; color: #909399; text-align: right; margin-top: -8px; }
.continuous { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.shortcut { margin-top: 4px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.thumb {
  padding: 6px 12px;
  border: 1px solid #e4efec;
  border-radius: 9px;
  background: #fbfefd;
  color: #475569;
  font-size: 12px;
  cursor: pointer;
}
.thumb.active { border-color: #2f9d8f; background: #eaf7f4; color: #175e55; }
.modify-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.modify-canvas { position: relative; height: 420px; background: #0f1115; }
.muted { color: #909399; font-size: 12px; }
</style>
