<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { InferenceTask, Report, ReportTemplate, Study } from '@/types'
import * as api from '@/api'
import ImageViewer from '@/components/ImageViewer.vue'
import MaskOverlay from '@/components/MaskOverlay.vue'
import ResultPanel from '@/components/ResultPanel.vue'

const route = useRoute()
const router = useRouter()
const study = ref<Study | null>(null)
const view = reactive({ scale: 1, tx: 0, ty: 0 })
const analysisState = ref<'idle' | 'running' | 'done'>('idle')
const overlayOpacity = ref(0.6)

onMounted(async () => {
  const resp = await api.getStudy(route.params.id as string)
  study.value = (resp as { data: Study }).data
  if (study.value.latest_inference) analysisState.value = 'done'
})

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function runAnalysis() {
  if (!study.value?.images.length) {
    ElMessage.warning('该检查没有可分析的影像')
    return
  }
  analysisState.value = 'running'
  try {
    const created = await api.createInference({
      image_id: study.value.images[0].id
    }) as { data: { task_id?: string; id?: string } }
    const taskId = created.data.task_id || created.data.id
    if (!taskId) throw new Error('推理任务未返回 task_id')

    for (let attempt = 0; attempt < 60; attempt++) {
      const resp = await api.getInference(taskId) as { data: InferenceTask }
      const task = resp.data
      if (task.status === 'succeeded') {
        study.value.latest_inference = task.result ?? null
        analysisState.value = 'done'
        ElMessage.success('推理完成')
        return
      }
      if (task.status === 'failed') {
        const detail: any = task.error
        throw new Error(detail?.message || detail || '推理失败')
      }
      await wait(1000)
    }
    throw new Error('推理超时，请稍后重试')
  } catch (error: any) {
    analysisState.value = 'idle'
    ElMessage.error(error?.response?.data?.message || error?.message || '推理失败')
  }
}

async function review(decision: string) {
  if (decision === 'modify') {
    ElMessage.info('修改掩膜请在标注编辑器中完成，再回到本页复核')
    return
  }
  if (decision === 'reject') {
    const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回检查', {
      inputPlaceholder: '原因…'
    })
    await api.reviewStudy(study.value!.id, { decision, comment: value })
    ElMessage.success('已驳回')
    return
  }
  await ElMessageBox.confirm('确认提交复核结论？', '复核确认', { type: 'warning' })
  await api.reviewStudy(study.value!.id, { decision })
  ElMessage.success('复核已提交')
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
      <div class="layout">
        <div class="viewer-box">
          <ImageViewer :image="study.images[0]" :view="view" />
          <MaskOverlay
            v-if="study.images[0]"
            :rle="analysisState === 'done' ? study.latest_inference?.mask_rle ?? null : null"
            :image-width="study.images[0].width"
            :image-height="study.images[0].height"
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
              <el-button type="success" @click="review('accept')">接受</el-button>
              <el-button type="warning" @click="review('modify')">修改</el-button>
              <el-button type="danger" @click="review('reject')">驳回</el-button>
              <el-button @click="toReport">撰写报告</el-button>
            </div>
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
.muted { color: #909399; }
</style>