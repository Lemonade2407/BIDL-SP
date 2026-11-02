<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { Dataset, DatasetVersion } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const datasets = ref<Dataset[]>([])
const versions = ref<DatasetVersion[]>([])

onMounted(async () => {
  const r1 = await api.getDatasets()
  datasets.value = (r1 as { data: Dataset[] }).data
  const r2 = await api.getDatasetVersions()
  versions.value = (r2 as { data: DatasetVersion[] }).data
})

async function freeze(v: DatasetVersion) {
  if (v.status === 'frozen') return
  await api.freezeDatasetVersion(v.id)
  ElMessage.success('版本已冻结')
  v.status = 'frozen'
}
</script>

<template>
  <div>
    <h3 class="page-title">数据集版本</h3>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card v-for="d in datasets" :key="d.id" shadow="never" style="margin-bottom: 16px">
          <template #header>数据集</template>
          <p><strong>{{ d.name }}</strong></p>
          <p class="muted">{{ d.description }}</p>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="影像数">{{ d.image_count }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ d.created_at }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never">
          <template #header>版本列表</template>
          <el-table :data="versions" border stripe>
            <el-table-column prop="version" label="版本" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><StatusTag :status="row.status" /></template>
            </el-table-column>
            <el-table-column prop="split_seed" label="种子" width="70" />
            <el-table-column label="划分" width="180">
              <template #default="{ row }">{{ row.counts.train }} / {{ row.counts.val }} / {{ row.counts.test }}</template>
            </el-table-column>
            <el-table-column prop="frozen_at" label="冻结时间" />
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button v-if="row.status === 'draft'" size="small" type="primary" @click="freeze(row)">冻结</el-button>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.muted { color: #909399; }
</style>