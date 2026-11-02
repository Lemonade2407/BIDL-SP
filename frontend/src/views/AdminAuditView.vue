<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { AuditLog } from '@/types'
import * as api from '@/api'

const logs = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const q = ref('')

async function fetch() {
  const resp = await api.getAuditLogs({ page: page.value, page_size: pageSize, q: q.value || undefined })
  const r = resp as { data: AuditLog[]; meta?: { total?: number } }
  logs.value = r.data
  total.value = r.meta?.total ?? r.data.length
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">审计日志</h3>
    <el-card shadow="never">
      <el-form inline @submit.prevent="page = 1; fetch()">
        <el-form-item>
          <el-input v-model="q" placeholder="按动作 / 对象类型检索" clearable style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
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
</style>