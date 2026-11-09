<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { AuditLog, User } from '@/types'
import * as api from '@/api'

const logs = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const q = ref('')
const filters = ref({
  action: '',
  object_type: '',
  object_id: '',
  actor_id: '',
  range: null as [string, string] | null
})
const users = ref<User[]>([])
const exporting = ref(false)

function query() {
  const f = filters.value
  return {
    q: q.value || undefined,
    action: f.action || undefined,
    object_type: f.object_type || undefined,
    object_id: f.object_id || undefined,
    actor_id: f.actor_id || undefined,
    from: f.range ? new Date(`${f.range[0]}T00:00:00`).toISOString() : undefined,
    to: f.range ? new Date(`${f.range[1]}T23:59:59`).toISOString() : undefined
  }
}

async function fetch() {
  const resp = await api.getAuditLogs({ page: page.value, page_size: pageSize, ...query() })
  const r = resp as { data: AuditLog[]; meta?: { total?: number } }
  logs.value = r.data
  total.value = r.meta?.total ?? r.data.length
}

function search() {
  page.value = 1
  fetch()
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`
}

async function exportCsv() {
  exporting.value = true
  try {
    const rows: string[][] = [['ID', '时间', '操作人', '动作', '对象类型', '对象 ID', 'IP', '详情']]
    const limit = 50
    for (let p = 1; p <= limit; p++) {
      const resp = await api.getAuditLogs({ page: p, page_size: 100, ...query() })
      const r = resp as { data: AuditLog[]; meta?: { total?: number } }
      for (const log of r.data) {
        rows.push([
          String(log.id),
          log.created_at,
          log.actor?.display_name || '系统',
          log.action,
          log.object_type,
          log.object_id,
          log.ip || '',
          JSON.stringify(log.detail ?? {})
        ])
      }
      if (r.data.length < 100 || p * 100 >= (r.meta?.total ?? 0)) break
    }
    const csv = rows.map((row) => row.map(csvCell).join(',')).join('\r\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `audit-logs-${Date.now()}.csv`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 10000)
    ElMessage.success(`已导出 ${rows.length - 1} 条审计记录`)
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  await fetch()
  const resp = await api.getUsers({ page_size: 100 })
  users.value = (resp as { data: User[] }).data
})
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">审计日志</h3>
      <el-button type="primary" :loading="exporting" @click="exportCsv">导出 CSV</el-button>
    </div>
    <el-card shadow="never">
      <el-form inline @submit.prevent="search">
        <el-form-item>
          <el-input v-model="q" placeholder="关键词（动作 / 对象类型）" clearable style="width: 220px" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="filters.action" placeholder="动作，如 report.sign" clearable style="width: 200px" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="filters.object_type" placeholder="对象类型" clearable style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="filters.object_id" placeholder="对象 ID" clearable style="width: 200px" />
        </el-form-item>
        <el-form-item>
          <el-select v-model="filters.actor_id" placeholder="操作人" clearable style="width: 160px">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-date-picker
            v-model="filters.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 260px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button @click="filters = { action: '', object_type: '', object_id: '', actor_id: '', range: null }; q = ''; search()">重置</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="logs" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column label="操作人" width="120">
          <template #default="{ row }">{{ row.actor?.display_name || '系统' }}</template>
        </el-table-column>
        <el-table-column prop="action" label="动作" width="200" />
        <el-table-column prop="object_type" label="对象类型" width="140" />
        <el-table-column prop="object_id" label="对象 ID" width="140" />
        <el-table-column prop="ip" label="IP" width="120" />
        <el-table-column label="详情" show-overflow-tooltip>
          <template #default="{ row }">{{ row.detail ? JSON.stringify(row.detail) : '—' }}</template>
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
