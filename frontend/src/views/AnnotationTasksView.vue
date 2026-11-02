<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { AnnotationTask } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const tasks = ref<AnnotationTask[]>([])
const status = ref('')
const loading = ref(false)

async function fetch() {
  loading.value = true
  try {
    const resp = await api.getAnnotationTasks({ status: status.value || undefined })
    tasks.value = (resp as { data: AnnotationTask[] }).data
  } finally {
    loading.value = false
  }
}

async function claim(t: AnnotationTask) {
  await api.claimAnnotationTask(t.id)
  ElMessage.success('已领取任务')
  fetch()
}

function open(t: AnnotationTask) {
  router.push(`/annotation/editor/${t.image_id}`)
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">标注任务</h3>
    <el-card shadow="never">
      <el-form inline @submit.prevent="fetch()">
        <el-form-item>
          <el-select v-model="status" placeholder="状态" clearable style="width: 160px" @change="fetch">
            <el-option label="待处理" value="pending" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已提交" value="submitted" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">刷新</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="tasks" v-loading="loading" border stripe>
        <el-table-column prop="id" label="任务 ID" width="110" />
        <el-table-column prop="image_id" label="影像 ID" width="120" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="80" />
        <el-table-column label="领取人" width="130">
          <template #default="{ row }">{{ row.assignee?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" type="primary" @click="claim(row)">领取</el-button>
            <el-button v-if="row.status === 'in_progress'" size="small" @click="open(row)">进入编辑</el-button>
            <el-button v-if="row.status === 'approved'" size="small" @click="open(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
</style>