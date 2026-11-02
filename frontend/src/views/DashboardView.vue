<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { StatsOverview } from '@/types'
import * as api from '@/api'

const router = useRouter()
const stats = ref<StatsOverview | null>(null)

const cards = [
  { key: 'images', label: '影像总量', icon: 'Picture' },
  { key: 'annotations_approved', label: '已通过标注', icon: 'EditPen' },
  { key: 'dataset_versions', label: '数据集版本', icon: 'Files' },
  { key: 'model_versions', label: '模型版本', icon: 'Cpu' },
  { key: 'screen_tasks', label: '筛查任务', icon: 'View' },
  { key: 'reports_signed', label: '已签发报告', icon: 'DocumentChecked' }
] as const

onMounted(async () => {
  const resp = await api.getStatsOverview()
  stats.value = (resp as { data: StatsOverview }).data
})

function fmt(key: string, v: number) {
  if (key === 'positive_rate') return (v * 100).toFixed(0) + '%'
  return String(v)
}
</script>

<template>
  <div>
    <h3 class="page-title">总览</h3>
    <el-row :gutter="16">
      <el-col v-for="c in cards" :key="c.key" :span="8">
        <el-card shadow="hover" class="stat-card" @click="router.push('/stats')">
          <div class="stat">
            <div class="num">{{ stats ? stats[c.key as keyof StatsOverview] : '—' }}</div>
            <div class="lbl">{{ c.label }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="num">{{ stats ? fmt('positive_rate', stats.positive_rate) : '—' }}</div>
            <div class="lbl">阳性率</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="num">{{ stats ? stats.avg_review_seconds + 's' : '—' }}</div>
            <div class="lbl">平均复核耗时</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-card shadow="never" class="quick">
      <template #header>快捷入口</template>
      <el-space wrap>
        <el-button type="primary" plain @click="router.push('/screening/worklist')">筛查工作台</el-button>
        <el-button type="primary" plain @click="router.push('/annotation/tasks')">标注任务</el-button>
        <el-button type="primary" plain @click="router.push('/data/images')">影像检索</el-button>
        <el-button type="primary" plain @click="router.push('/models')">模型与指标</el-button>
      </el-space>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.stat { text-align: center; padding: 8px 0; }
.stat .num { font-size: 28px; font-weight: 700; color: #303133; }
.stat .lbl { color: #909399; margin-top: 6px; }
.quick { margin-top: 16px; }
</style>