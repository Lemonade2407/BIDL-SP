<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Report, ReportContent } from '@/types'
import * as api from '@/api'
import ReportEditor from '@/components/ReportEditor.vue'
import StatusTag from '@/components/StatusTag.vue'

const route = useRoute()
const report = ref<Report | null>(null)

onMounted(async () => {
  const resp = await api.getReport(route.params.id as string)
  report.value = (resp as { data: Report }).data
})

function onContent(c: ReportContent) {
  if (report.value) report.value.content = c
}

async function save() {
  await api.createReport({ ...report.value!, content: report.value!.content })
  ElMessage.success('报告已保存')
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
          <el-button v-if="report.status === 'draft'" @click="save">保存</el-button>
          <el-button v-if="report.status === 'draft'" type="primary" @click="submit">提交审核</el-button>
          <el-button v-if="report.status === 'pending_review'" type="success" @click="sign">签发</el-button>
          <el-button v-if="report.status === 'pending_review'" type="danger" @click="reject">驳回</el-button>
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