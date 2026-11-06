<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ScreenTask, Study } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const tasks = ref<ScreenTask[]>([])
const studies = ref<Study[]>([])
const status = ref('')
const loading = ref(false)

async function fetch() {
  loading.value = true
  try {
    const r1 = await api.getScreenTasks({ status: status.value || undefined })
    tasks.value = (r1 as { data: ScreenTask[] }).data
    studies.value = (await Promise.all(tasks.value.map(async (t) => (await api.getStudy(t.study_id)) as { data: Study }).map((p) => p.then((r) => r.data))))
  } finally {
    loading.value = false
  }
}

function studyOf(t: ScreenTask) {
  return studies.value.find((s) => s.id === t.study_id)
}

async function claim(t: ScreenTask) {
  await api.claimScreenTask(t.id)
  ElMessage.success('已领取检查')
  fetch()
}

function open(t: ScreenTask) {
  router.push(`/screening/studies/${t.study_id}`)
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">筛查工作列表</h3>
    <el-card shadow="never">
      <el-form inline @submit.prevent="fetch()">
        <el-form-item>
          <el-select v-model="status" placeholder="状态" clearable style="width: 160px" @change="fetch">
            <el-option label="待处理" value="pending" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已完成" value="done" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">刷新</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="tasks" v-loading="loading" border stripe>
        <el-table-column label="检查号" width="180">
          <template #default="{ row }">{{ studyOf(row)?.study_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="患者" width="120">
          <template #default="{ row }">{{ studyOf(row)?.patient.patient_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="设备" width="140">
          <template #default="{ row }">{{ studyOf(row)?.device || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="80" />
        <el-table-column label="领取人" width="120">
          <template #default="{ row }">{{ row.assignee?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" type="primary" @click="claim(row)">领取</el-button>
            <el-button size="small" @click="open(row)">进入复核</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
</style>