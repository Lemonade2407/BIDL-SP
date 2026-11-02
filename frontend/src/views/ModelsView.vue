<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { ModelVersion } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const versions = ref<ModelVersion[]>([])

onMounted(async () => {
  const resp = await api.getModelVersions('m-transunet')
  versions.value = (resp as { data: ModelVersion[] }).data
})

async function activate(v: ModelVersion) {
  if (v.status === 'active') return
  await api.activateModelVersion(v.id)
  ElMessage.success(`已启用 ${v.version}`)
  versions.value.forEach((x) => (x.status = x.id === v.id ? 'active' : 'candidate'))
}
</script>

<template>
  <div>
    <h3 class="page-title">模型与指标</h3>
    <el-card shadow="never">
      <el-table :data="versions" border stripe>
        <el-table-column prop="version" label="版本" width="160" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="Dice" width="110">
          <template #default="{ row }">{{ row.metrics?.dice?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="精确率" width="110">
          <template #default="{ row }">{{ row.metrics?.precision?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="召回率" width="110">
          <template #default="{ row }">{{ row.metrics?.recall?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="HD95(px)" width="110">
          <template #default="{ row }">{{ row.metrics?.hd95 }}</template>
        </el-table-column>
        <el-table-column prop="weights_sha256" label="权重 SHA256" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'active'" size="small" type="primary" @click="activate(row)">启用</el-button>
            <span v-else class="muted">在线版本</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.muted { color: #909399; }
</style>