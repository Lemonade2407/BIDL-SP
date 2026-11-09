<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import MetricChart from '@/components/MetricChart.vue'

const overview = ref<any>(null)
const ann = ref<any>(null)
const models = ref<any>(null)
const screening = ref<any>(null)
const range = ref<[string, string] | null>(null)

function isoBounds(): { from?: string; to?: string } {
  if (!range.value) return {}
  const [start, end] = range.value
  const from = new Date(`${start}T00:00:00`)
  const to = new Date(`${end}T23:59:59`)
  return { from: from.toISOString(), to: to.toISOString() }
}

async function loadScreening() {
  screening.value = ((await api.getStatsScreening(isoBounds())) as { data: any }).data
}

async function load() {
  overview.value = ((await api.getStatsOverview()) as { data: any }).data
  ann.value = ((await api.getStatsAnnotations()) as { data: any }).data
  models.value = ((await api.getStatsModels()) as { data: any }).data
  await loadScreening()
}

function download(name: string, rows: (string | number)[][]) {
  const csv = rows
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\r\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10000)
}

function exportCsv() {
  if (!screening.value) {
    ElMessage.warning('暂无统计数据')
    return
  }
  const s = screening.value
  const rows: (string | number)[][] = [
    ['指标', '值'],
    ['统计区间', range.value ? `${range.value[0]} ~ ${range.value[1]}` : '全部'],
    ['影像总量', overview.value?.images ?? ''],
    ['已通过标注', overview.value?.annotations_approved ?? ''],
    ['已签发报告', overview.value?.reports_signed ?? ''],
    ['阳性率', s.positive_rate],
    ['参考阳性', s.positive],
    ['参考阴性', s.negative],
    ['平均复核秒数', s.avg_review_seconds],
    ['说明', s.definition]
  ]
  for (const [key, value] of Object.entries(s.by_status ?? {})) rows.push([`任务状态 ${key}`, value as number])
  for (const [key, value] of Object.entries(s.by_decision ?? {})) rows.push([`复核结论 ${key}`, value as number])
  download(`stats-screening-${Date.now()}.csv`, rows)
}

onMounted(load)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">统计看板</h3>
      <el-space>
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px"
          @change="loadScreening"
        />
        <el-button @click="loadScreening">刷新筛查统计</el-button>
        <el-button type="primary" @click="exportCsv">导出 CSV</el-button>
      </el-space>
    </div>
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
            <p>复核结论：接受 {{ screening.by_decision.accept ?? 0 }} / 修改 {{ screening.by_decision.modify ?? 0 }} / 驳回 {{ screening.by_decision.reject ?? 0 }}</p>
            <p>任务状态：待处理 {{ screening.by_status.pending ?? 0 }} / 进行中 {{ screening.by_status.in_progress ?? 0 }} / 已完成 {{ screening.by_status.done ?? 0 }}</p>
            <p>参考阳性 {{ screening.positive }} / 阴性 {{ screening.negative }}（阳性率 {{ (screening.positive_rate * 100).toFixed(1) }}%）</p>
            <p>平均复核耗时：{{ screening.avg_review_seconds.toFixed(2) }}s</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
.num { font-size: 26px; font-weight: 700; }
.lbl { color: #909399; margin-top: 4px; }
.def { font-size: 12px; margin-bottom: 8px; }
.muted { color: #909399; }
</style>
