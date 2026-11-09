<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { AnnotationTask, UserRef } from '@/types'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const auth = useAuthStore()
const tasks = ref<AnnotationTask[]>([])
const status = ref('')
const scope = ref<'mine' | 'all'>('mine')
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)

async function fetch() {
  loading.value = true
  try {
    const resp = await api.getAnnotationTasks({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
      assignee: scope.value === 'mine' ? 'me' : undefined,
      sort: '-priority'
    }) as { data: AnnotationTask[]; meta?: { total?: number } }
    tasks.value = resp.data
    total.value = resp.meta?.total ?? resp.data.length
  } finally {
    loading.value = false
  }
}

function onScopeChange() {
  page.value = 1
  fetch()
}

async function claim(t: AnnotationTask) {
  await api.claimAnnotationTask(t.id)
  ElMessage.success('已领取任务')
  fetch()
}

async function join(t: AnnotationTask) {
  await api.joinAnnotationTask(t.id)
  ElMessage.success('已加入双人标注任务')
  fetch()
}

async function release(t: AnnotationTask) {
  await ElMessageBox.confirm('释放后任务将回到待领取队列，已保存草稿会保留，确认释放？', '释放任务', { type: 'warning' })
  await api.releaseAnnotationTask(t.id)
  ElMessage.success('已释放')
  fetch()
}

function open(t: AnnotationTask) {
  router.push(`/annotation/editor/${t.image_id}`)
}

function openReview(t: AnnotationTask) {
  if (!t.annotation_id) {
    ElMessage.warning('该任务尚未关联标注版本')
    return
  }
  router.push(`/annotation/review/${t.annotation_id}`)
}

function canReview(t: AnnotationTask) {
  return t.status === 'submitted' && t.assignee?.id !== auth.user?.id
}

function isParticipant(t: AnnotationTask) {
  if (t.assignee?.id === auth.user?.id) return true
  return (t.participants ?? []).some((p) => p.id === auth.user?.id)
}

function canJoin(t: AnnotationTask) {
  if ((t.required_annotators ?? 1) < 2) return false
  if (!['pending', 'in_progress'].includes(t.status)) return false
  if (isParticipant(t)) return false
  return (t.participants?.length ?? 0) < (t.required_annotators ?? 1)
}

function participantNames(participants?: UserRef[]) {
  return (participants ?? []).map((p) => p.display_name).join(' / ')
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">标注任务</h3>
    <el-card shadow="never">
      <el-tabs v-model="scope" @tab-change="onScopeChange">
        <el-tab-pane label="我的任务" name="mine" />
        <el-tab-pane label="全部任务" name="all" />
      </el-tabs>
      <el-form inline @submit.prevent="page = 1; fetch()">
        <el-form-item>
          <el-select v-model="status" placeholder="状态" clearable style="width: 160px" @change="page = 1; fetch()">
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
        <el-table-column prop="image_id" label="影像 ID" width="110" />
        <el-table-column prop="filename" label="文件" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="80" />
        <el-table-column label="模式" width="100">
          <template #default="{ row }">
            <el-tag v-if="(row.required_annotators ?? 1) > 1" size="small" type="warning">
              双人 {{ row.submitted_count ?? 0 }}/{{ row.required_annotators }}
            </el-tag>
            <span v-else class="muted">单人</span>
          </template>
        </el-table-column>
        <el-table-column label="参与人" width="150">
          <template #default="{ row }">
            <span v-if="row.participants?.length">
              {{ participantNames(row.participants) }}
            </span>
            <span v-else>{{ row.assignee?.display_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="一致性" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.consistency" size="small" :type="row.consistency.auto ? 'success' : 'danger'">
              IoU {{ row.consistency.iou }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending' && !isParticipant(row)" size="small" type="primary" @click="claim(row)">
              领取
            </el-button>
            <el-button v-if="canJoin(row)" size="small" type="primary" plain @click="join(row)">加入标注</el-button>
            <el-button
              v-if="row.status === 'in_progress' && isParticipant(row)"
              size="small"
              @click="open(row)"
            >进入编辑</el-button>
            <el-button
              v-if="row.status === 'in_progress' && isParticipant(row)"
              size="small"
              @click="release(row)"
            >释放</el-button>
            <el-button v-if="canReview(row)" size="small" type="warning" @click="openReview(row)">审核 / 仲裁</el-button>
            <el-tag v-else-if="row.status === 'submitted'" size="small" type="info">待他人审核</el-tag>
            <el-button v-if="row.status === 'approved'" size="small" @click="open(row)">查看</el-button>
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
