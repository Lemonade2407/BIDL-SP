<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Report } from '@/types'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const auth = useAuthStore()
const reports = ref<Report[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const status = ref('')
const scope = ref<'all' | 'mine' | 'review'>('all')
const downloading = ref('')

const canSign = computed(() => auth.hasAny('reviewer', 'admin'))

async function fetch() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined
    }
    if (scope.value === 'mine') params.author_id = auth.user?.id
    if (scope.value === 'review') {
      params.status = 'pending_review'
    }
    const resp = await api.getReports(params) as { data: Report[]; meta?: { total?: number } }
    reports.value = resp.data
    total.value = resp.meta?.total ?? resp.data.length
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  fetch()
}

async function exportPdf(report: Report) {
  downloading.value = report.id
  try {
    const blob = await api.getReportPdf(report.id) as unknown as Blob
    const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `report-${report.id}-v${report.version}.pdf`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
    ElMessage.success(report.status === 'signed' ? '已下载签发版 PDF' : '已下载草稿预览 PDF')
  } catch {
    ElMessage.error('PDF 生成或下载失败')
  } finally {
    downloading.value = ''
  }
}

onMounted(fetch)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">报告中心</h3>
      <el-button @click="fetch">刷新</el-button>
    </div>
    <el-card shadow="never">
      <el-tabs v-model="scope" @tab-change="search">
        <el-tab-pane label="全部报告" name="all" />
        <el-tab-pane label="我起草的" name="mine" />
        <el-tab-pane v-if="canSign" label="待签发" name="review" />
      </el-tabs>
      <el-form inline @submit.prevent="search">
        <el-form-item>
          <el-select v-model="status" placeholder="状态" clearable style="width: 160px" @change="search">
            <el-option label="草稿" value="draft" />
            <el-option label="待审核" value="pending_review" />
            <el-option label="已签发" value="signed" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="reports" v-loading="loading" border stripe>
        <el-table-column prop="id" label="报告 ID" width="120" />
        <el-table-column prop="study_id" label="检查 ID" width="120" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="起草人" width="120">
          <template #default="{ row }">{{ row.author?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="审核/签发" width="120">
          <template #default="{ row }">{{ row.reviewer?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="signed_at" label="签发时间" width="190" />
        <el-table-column prop="updated_at" label="更新时间" width="190" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="router.push(`/reports/${row.id}`)">查看/编辑</el-button>
            <el-button size="small" :loading="downloading === row.id" @click="exportPdf(row)">PDF</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @current-change="fetch"
      />
    </el-card>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
</style>
