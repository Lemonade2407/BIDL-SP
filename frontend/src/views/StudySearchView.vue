<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { StudyRow } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const studies = ref<StudyRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const q = ref('')
const status = ref('')
const range = ref<[string, string] | null>(null)

async function fetch() {
  loading.value = true
  try {
    const resp = await api.getStudies({
      page: page.value,
      page_size: pageSize,
      q: q.value || undefined,
      status: status.value || undefined,
      from: range.value?.[0],
      to: range.value?.[1]
    }) as { data: StudyRow[]; meta?: { total?: number } }
    studies.value = resp.data
    total.value = resp.meta?.total ?? resp.data.length
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  fetch()
}

function openStudy(row: StudyRow) {
  if (!row.screen_task) return
  router.push(`/screening/studies/${row.id}`)
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">检查检索</h3>
    <el-card shadow="never">
      <el-form inline @submit.prevent="search">
        <el-form-item>
          <el-input v-model="q" placeholder="检查号 / 患者编号" clearable style="width: 220px" />
        </el-form-item>
        <el-form-item>
          <el-select v-model="status" placeholder="检查状态" clearable style="width: 150px">
            <el-option label="待处理" value="pending" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已复核" value="reviewed" />
            <el-option label="已出报告" value="reported" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 250px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="studies" v-loading="loading" border stripe>
        <el-table-column prop="study_no" label="检查号" width="170" />
        <el-table-column prop="patient_no" label="患者编号" width="130" />
        <el-table-column prop="gender" label="性别" width="70" />
        <el-table-column prop="study_date" label="检查日期" width="120" />
        <el-table-column prop="device" label="设备" width="130" />
        <el-table-column prop="image_count" label="影像数" width="80" />
        <el-table-column label="检查状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="筛查任务" width="120">
          <template #default="{ row }">
            <StatusTag v-if="row.screen_task" :status="row.screen_task.status" />
            <span v-else class="muted">未创建</span>
          </template>
        </el-table-column>
        <el-table-column label="报告" width="110">
          <template #default="{ row }">
            <StatusTag v-if="row.report" :status="row.report.status" />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button v-if="row.screen_task" size="small" @click="openStudy(row)">查看检查</el-button>
            <el-button v-if="row.report" size="small" type="primary" @click="router.push(`/reports/${row.report.id}`)">
              查看报告
            </el-button>
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
.page-title { margin: 0 0 16px; }
.muted { color: #909399; font-size: 12px; }
</style>
