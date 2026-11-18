<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Report, ReportContent } from '@/types'
import * as api from '@/api'
import ReportEditor from '@/components/ReportEditor.vue'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isAdmin = computed(() => auth.hasRole('admin'))
const report = ref<Report | null>(null)
const pdfLoading = ref(false)

onMounted(async () => {
  const resp = await api.getReport(route.params.id as string)
  report.value = (resp as { data: Report }).data
})

function onContent(c: ReportContent) {
  if (report.value) report.value.content = c
}

async function save() {
  const current = report.value
  if (!current) return
  const resp = await api.createReport({
    study_id: current.study_id,
    inference_result_id: current.inference_result_id ?? null,
    template_id: current.template_id,
    content: current.content
  }) as { data: Report }
  report.value = resp.data
  router.replace(`/reports/${resp.data.id}`)
  ElMessage.success('报告已保存为新版本')
}

async function submit() {
  await api.submitReport(report.value!.id)
  ElMessage.success('已提交审核')
  report.value!.status = 'pending_review'
}

async function sign() {
  await ElMessageBox.confirm('确认签发该报告？', '签发确认', { type: 'warning' })
  await api.signReport(report.value!.id, { decision: 'sign' })
  ElMessage.success('报告已签发')
  report.value!.status = 'signed'
}

async function reject() {
  const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回报告', { inputPlaceholder: '原因…' })
  await api.signReport(report.value!.id, { decision: 'reject', comment: value })
  ElMessage.success('已驳回')
  report.value!.status = 'rejected'
}

async function doVoid() {
  const { value } = await ElMessageBox.prompt('作废已签发报告需填写原因（不可恢复）', '作废报告', { inputPlaceholder: '作废原因…', inputValidator: (v) => (v && v.trim() ? true : '原因必填') })
  await api.voidReport(report.value!.id, { reason: value })
  ElMessage.success('报告已作废')
  report.value!.status = 'voided'
}

async function exportPdf(mode: 'download' | 'print') {
  const current = report.value
  if (!current) return
  pdfLoading.value = true
  try {
    const blob = await api.getReportPdf(current.id) as unknown as Blob
    const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
    if (mode === 'print') {
      window.open(url, '_blank')
    } else {
      const link = document.createElement('a')
      link.href = url
      link.download = `report-${current.id}-v${current.version}.pdf`
      link.click()
      ElMessage.success(current.status === 'signed' ? '已下载签发版 PDF' : '已下载草稿预览 PDF（含水印）')
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch {
    ElMessage.error('PDF 生成或下载失败')
  } finally {
    pdfLoading.value = false
  }
}
</script>

<template>
  <div>
    <h3 class="page-title">报告编辑与审核</h3>
    <el-card shadow="never" v-if="report">
      <div class="head">
        <el-space>
          <span class="muted">报告 ID：{{ report.id }}</span>
          <StatusTag :status="report.status" />
          <span class="muted">版本 v{{ report.version }}</span>
        </el-space>
        <div>
          <el-button :loading="pdfLoading" @click="exportPdf('download')">下载 PDF</el-button>
          <el-button :loading="pdfLoading" @click="exportPdf('print')">打印</el-button>
          <el-button v-if="report.status === 'draft'" @click="save">保存</el-button>
          <el-button v-if="report.status === 'draft'" type="primary" @click="submit">提交审核</el-button>
          <el-button v-if="report.status === 'pending_review'" type="success" @click="sign">签发</el-button>
          <el-button v-if="report.status === 'pending_review'" type="danger" @click="reject">驳回</el-button>
          <el-button v-if="isAdmin && report.status === 'signed'" type="danger" plain @click="doVoid">作废</el-button>
        </div>
      </div>
      <el-divider />
      <ReportEditor :content="report.content" :readonly="report.status === 'signed'" @update:content="onContent" />
      <div class="disclaimer" style="margin-top: 12px">
        本报告仅供科研/教学使用，不作为临床诊断依据。签发人：{{ report.reviewer?.display_name || '—' }}
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.head { display: flex; justify-content: space-between; align-items: center; }
.muted { color: #909399; font-size: 13px; }
</style>