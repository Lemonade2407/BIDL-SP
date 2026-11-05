<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Image } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const images = ref<Image[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const classLabel = ref('')
const q = ref('')
const loading = ref(false)

async function fetch() {
  loading.value = true
  try {
    const resp = await api.getImages({ page: page.value, page_size: pageSize, class_label: classLabel.value || undefined, q: q.value || undefined })
    const r = resp as { data: Image[]; meta?: { total?: number } }
    images.value = r.data
    total.value = r.meta?.total ?? r.data.length
  } finally {
    loading.value = false
  }
}

onMounted(fetch)
</script>

<template>
  <div>
    <h3 class="page-title">影像检索</h3>
    <el-card shadow="never">
      <el-form inline @submit.prevent="page = 1; fetch()">
        <el-form-item>
          <el-input v-model="q" placeholder="按 ID / SHA256 检索" clearable style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-select v-model="classLabel" placeholder="类别" clearable style="width: 140px">
            <el-option label="良性 benign" value="benign" />
            <el-option label="恶性 malignant" value="malignant" />
            <el-option label="正常 normal" value="normal" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="images" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="120" />
        <el-table-column prop="class_label" label="类别" width="100" />
        <el-table-column prop="source" label="来源" width="90" />
        <el-table-column prop="format" label="格式" width="80" />
        <el-table-column label="尺寸" width="110">
          <template #default="{ row }">{{ row.width }}×{{ row.height }}</template>
        </el-table-column>
        <el-table-column label="参考掩膜" width="100">
          <template #default="{ row }">{{ row.mask_available ? '有' : '无' }}</template>
        </el-table-column>
        <el-table-column label="标注状态" width="110">
          <template #default="{ row }">
            <StatusTag v-if="row.annotation_status" :status="row.annotation_status" />
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="sha256" label="SHA256" show-overflow-tooltip />
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