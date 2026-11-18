<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ScreenTask, User } from '@/types'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const auth = useAuthStore()
const canManage = computed(() => auth.hasAny('screener', 'admin'))
const isAdmin = computed(() => auth.hasRole('admin'))
const tasks = ref<ScreenTask[]>([])
const status = ref('')
const scope = ref<'mine' | 'all'>('mine')
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)

const reassignVisible = ref(false)
const reassignTarget = ref<ScreenTask | null>(null)
const reassignUserId = ref('')
const candidates = ref<User[]>([])
const reassigning = ref(false)

async function fetch() {
  loading.value = true
  try {
    const r1 = await api.getScreenTasks({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
      assignee: scope.value === 'mine' ? 'me' : undefined,
      sort: '-priority'
    }) as { data: ScreenTask[]; meta?: { total?: number } }
    tasks.value = r1.data
    total.value = r1.meta?.total ?? r1.data.length
  } finally {
    loading.value = false
  }
}

function onScopeChange() {
  page.value = 1
  fetch()
}

function isMine(t: ScreenTask) {
  return t.assignee?.id === auth.user?.id
}

async function claim(t: ScreenTask) {
  await api.claimScreenTask(t.id)
  ElMessage.success('已领取检查')
  fetch()
}

async function release(t: ScreenTask) {
  await ElMessageBox.confirm('释放后该检查将回到待处理队列，确认释放？', '释放检查', { type: 'warning' })
  await api.releaseScreenTask(t.id)
  ElMessage.success('已释放')
  fetch()
}

async function openReassign(t: ScreenTask) {
  reassignTarget.value = t
  reassignUserId.value = ''
  if (!candidates.value.length) {
    const [screeners, admins] = await Promise.all([
      api.getUsers({ role: 'screener', status: 'active', page_size: 100 }),
      api.getUsers({ role: 'admin', status: 'active', page_size: 100 })
    ])
    const merged = [
      ...(screeners as { data: User[] }).data,
      ...(admins as { data: User[] }).data
    ]
    candidates.value = merged.filter((u, i) => merged.findIndex((x) => x.id === u.id) === i)
  }
  reassignVisible.value = true
}

async function submitReassign() {
  if (!reassignTarget.value || !reassignUserId.value) {
    ElMessage.warning('请选择被指派人')
    return
  }
  reassigning.value = true
  try {
    await api.reassignScreenTask(reassignTarget.value.id, reassignUserId.value)
    ElMessage.success('已改派')
    reassignVisible.value = false
    fetch()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '改派失败')
  } finally {
    reassigning.value = false
  }
}

function open(t: ScreenTask) {
  router.push(`/screening/studies/${t.study_id}`)
}

onMounted(fetch)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">筛查工作列表</h3>
      <el-button v-if="canManage" type="primary" @click="router.push('/screening/new')">新建检查</el-button>
    </div>
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
            <el-option label="已完成" value="done" />
            <el-option label="已退回" value="returned" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">刷新</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="tasks" v-loading="loading" border stripe>
        <el-table-column label="检查号" width="180">
          <template #default="{ row }">{{ row.study_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="患者" width="120">
          <template #default="{ row }">{{ row.patient_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="设备" width="140">
          <template #default="{ row }">{{ row.device || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="80" />
        <el-table-column label="领取人" width="120">
          <template #default="{ row }">{{ row.assignee?.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="退回原因" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.return_reason || (row.status === 'returned' ? '—' : '') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button v-if="canManage && row.status === 'pending'" size="small" type="primary" @click="claim(row)">领取</el-button>
            <el-button v-if="canManage && row.status === 'in_progress'" size="small" @click="open(row)">进入复核</el-button>
            <el-button v-if="row.status === 'done'" size="small" @click="open(row)">查看</el-button>
            <el-button v-if="row.status === 'returned'" size="small" @click="open(row)">查看</el-button>
            <el-button
              v-if="row.status === 'in_progress' && (isMine(row) || isAdmin)"
              size="small"
              @click="release(row)"
            >释放</el-button>
            <el-button v-if="isAdmin && row.status !== 'done'" size="small" @click="openReassign(row)">改派</el-button>
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

    <el-dialog v-model="reassignVisible" title="改派检查" width="420px">
      <el-form label-width="90px">
        <el-form-item label="检查">
          <span>{{ reassignTarget?.study_no || reassignTarget?.study_id || '—' }}</span>
        </el-form-item>
        <el-form-item label="指派给">
          <el-select v-model="reassignUserId" style="width: 100%" placeholder="选择筛查医生">
            <el-option v-for="u in candidates" :key="u.id" :label="`${u.display_name}（${u.username}）`" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reassignVisible = false">取消</el-button>
        <el-button type="primary" :loading="reassigning" @click="submitReassign">确认改派</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
</style>
