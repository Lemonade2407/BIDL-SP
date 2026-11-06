<script setup lang="ts">
import { ref, onMounted } from 'vue'
import * as api from '@/api'
import MetricChart from '@/components/MetricChart.vue'

const overview = ref<any>(null)
const ann = ref<any>(null)
const models = ref<any>(null)
const screening = ref<any>(null)

onMounted(async () => {
  overview.value = ((await api.getStatsOverview()) as { data: any }).data
  ann.value = ((await api.getStatsAnnotations()) as { data: any }).data
  models.value = ((await api.getStatsModels()) as { data: any }).data
  screening.value = ((await api.getStatsScreening()) as { data: any }).data
})
</script>

<template>
  <div>
    <h3 class="page-title">统计看板</h3>
    <el-row :gutter="16">
      <el-col :span="6"><el-card shadow="never"><div class="num">{{ overview?.images }}</div><div class="lbl">影像总量</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="num">{{ overview?.annotations_approved }}</div><div class="lbl">已通过标注</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="num">{{ overview?.reports_signed }}</div><div class="lbl">已签发报告</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="num">{{ overview ? (overview.positive_rate * 100).toFixed(0) + '%' : '—' }}</div><div class="lbl">阳性率</div></el-card></el-col>
    </el-row>
    <el-card shadow="never" style="margin-top: 16px">
      <template #header>模型指标（3 种子均值 ± 标准差）</template>
      <MetricChart v-if="models" :variants="models.versions" />
    </el-card>
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>标注进度</template>
          <div v-if="ann">
            <div class="def muted">{{ ann.definition }}</div>
            <el-progress :percentage="Math.round(ann.completion_rate * 100)" style="margin: 12px 0" />
            <el-tag v-for="(v, k) in ann.by_status" :key="k" style="margin: 3px">{{ k }}：{{ v }}</el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>筛查统计</template>
          <div v-if="screening">
            <div class="def muted">{{ screening.definition }}</div>
            <p>复核结论：接受 {{ screening.by_decision.accept }} / 修改 {{ screening.by_decision.modify }} / 驳回 {{ screening.by_decision.reject }}</p>
            <p>平均复核耗时：{{ screening.avg_review_seconds.toFixed(2) }}s</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.num { font-size: 26px; font-weight: 700; }
.lbl { color: #909399; margin-top: 4px; }
.def { font-size: 12px; margin-bottom: 8px; }
.muted { color: #909399; }
</style>