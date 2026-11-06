<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight, Cpu, DataLine, DocumentChecked, EditPen, Files, Picture, Refresh, Timer, View
} from '@element-plus/icons-vue'
import type { StatsOverview } from '@/types'
import * as api from '@/api'

const router = useRouter()
const stats = ref<StatsOverview | null>(null)
const loading = ref(false)

const cards = [
  { key: 'images', label: '影像总量', icon: Picture, tone: 'teal', path: '/data/images' },
  { key: 'annotations_approved', label: '已通过标注', icon: EditPen, tone: 'blue', path: '/annotation/tasks' },
  { key: 'dataset_versions', label: '数据集版本', icon: Files, tone: 'violet', path: '/data/datasets' },
  { key: 'model_versions', label: '模型版本', icon: Cpu, tone: 'amber', path: '/models' },
  { key: 'screen_tasks', label: '筛查任务', icon: View, tone: 'rose', path: '/screening/worklist' },
  { key: 'reports_signed', label: '已签发报告', icon: DocumentChecked, tone: 'green', path: '/stats' }
] as const

const quick = [
  { label: '筛查工作台', desc: '领取检查、模型分析与复核', icon: View, path: '/screening/worklist' },
  { label: '标注任务', desc: '掩膜编辑、预标注与审核', icon: EditPen, path: '/annotation/tasks' },
  { label: '影像检索', desc: '按类别、来源与标注状态筛选', icon: Picture, path: '/data/images' },
  { label: '模型与指标', desc: '版本、Dice 与启用回滚', icon: Cpu, path: '/models' }
]

async function load() {
  loading.value = true
  try {
    const resp = await api.getStatsOverview()
    stats.value = (resp as { data: StatsOverview }).data
  } finally {
    loading.value = false
  }
}

onMounted(load)

function valueOf(key: string) {
  if (!stats.value) return '—'
  const value = stats.value[key as keyof StatsOverview]
  return value === undefined || value === null ? '—' : String(value)
}

function fmtRate() {
  return stats.value ? (stats.value.positive_rate * 100).toFixed(0) + '%' : '—'
}

function fmtReview() {
  return stats.value ? stats.value.avg_review_seconds.toFixed(2) + 's' : '—'
}
</script>

<template>
  <div class="dashboard">
    <div class="page-head">
      <div>
        <h3 class="page-title">总览</h3>
        <p class="page-sub">平台数据、模型与筛查任务的运行概览</p>
      </div>
      <el-button plain :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-row v-loading="loading" :gutter="16" class="stat-grid">
      <el-col v-for="c in cards" :key="c.key" :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card" :class="`tone-${c.tone}`" @click="router.push(c.path)">
          <div class="stat">
            <div class="stat-icon"><el-icon><component :is="c.icon" /></el-icon></div>
            <div class="stat-copy">
              <div class="num">{{ valueOf(c.key) }}</div>
              <div class="lbl">{{ c.label }}</div>
            </div>
            <el-icon class="arrow"><ArrowRight /></el-icon>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card tone-cyan">
          <div class="stat">
            <div class="stat-icon"><el-icon><DataLine /></el-icon></div>
            <div class="stat-copy">
              <div class="num">{{ fmtRate() }}</div>
              <div class="lbl">阳性率</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card tone-slate">
          <div class="stat">
            <div class="stat-icon"><el-icon><Timer /></el-icon></div>
            <div class="stat-copy">
              <div class="num">{{ fmtReview() }}</div>
              <div class="lbl">平均复核耗时</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <div class="lower-grid">
      <el-card shadow="never" class="quick-card">
        <template #header>快捷入口</template>
        <div class="quick-grid">
          <button v-for="q in quick" :key="q.path" class="quick-item" type="button" @click="router.push(q.path)">
            <span class="quick-icon"><el-icon><component :is="q.icon" /></el-icon></span>
            <span class="quick-copy"><b>{{ q.label }}</b><small>{{ q.desc }}</small></span>
            <el-icon class="quick-arrow"><ArrowRight /></el-icon>
          </button>
        </div>
      </el-card>

      <el-card shadow="never" class="tip-card">
        <template #header>工作提示</template>
        <ul class="tips">
          <li><span>01</span>数据接入后先冻结数据集版本，再生成标注任务。</li>
          <li><span>02</span>模型结果仅作参考，复核与签发需由医生完成。</li>
          <li><span>03</span>所有导入、推理、复核与签发都会写入审计日志。</li>
        </ul>
        <div class="tip-foot">仅供科研/教学使用，不作为临床诊断依据</div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.page-head .page-sub { margin-top: -8px; }

.stat-grid { margin-top: 2px; }

.stat-card {
  margin-bottom: 16px;
  cursor: pointer;
  transition: transform 0.22s ease, box-shadow 0.22s ease;
}

.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 26px 48px -30px rgba(15, 23, 42, 0.36);
}

.stat-card :deep(.el-card__body) { padding: 18px 20px; }

.stat { display: flex; align-items: center; gap: 14px; }

.stat-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 14px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 21px;
}

.stat-copy { min-width: 0; flex: 1; }
.stat .num { color: var(--ink); font-size: 27px; font-weight: 750; letter-spacing: 0.2px; line-height: 1.1; }
.stat .lbl { margin-top: 4px; color: var(--muted); font-size: 12px; }

.arrow { color: #b6c9c5; font-size: 14px; transition: transform 0.2s ease; }
.stat-card:hover .arrow { transform: translateX(3px); color: var(--brand); }

.tone-blue .stat-icon { background: #eaf2ff; color: #2563eb; }
.tone-violet .stat-icon { background: #f1ebff; color: #7c3aed; }
.tone-amber .stat-icon { background: #fff5df; color: #b45309; }
.tone-rose .stat-icon { background: #ffedf0; color: #e11d48; }
.tone-green .stat-icon { background: #e9f9ef; color: #15803d; }
.tone-cyan .stat-icon { background: #e6f9f8; color: #0e7490; }
.tone-slate .stat-icon { background: #eef2f7; color: #475569; }

.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.9fr);
  gap: 16px;
  margin-top: 4px;
}

.quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }

.quick-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e4efec;
  border-radius: 13px;
  background: #fbfefd;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}

.quick-item:hover {
  border-color: #b9dbd6;
  background: #f3fbf9;
  transform: translateY(-1px);
}

.quick-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 11px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 18px;
}

.quick-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; }
.quick-copy b { font-size: 13px; font-weight: 650; }
.quick-copy small { overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.quick-arrow { color: #b6c9c5; font-size: 13px; }

.tips { display: flex; flex-direction: column; gap: 14px; margin: 0; padding: 0; list-style: none; }
.tips li { display: flex; gap: 10px; color: #475569; font-size: 12.5px; line-height: 1.6; }
.tips li span {
  color: var(--brand);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.5px;
}
.tip-foot { margin-top: 20px; padding-top: 14px; border-top: 1px dashed #e2ece9; color: #8aa5a0; font-size: 10.5px; }

@media (max-width: 1100px) {
  .lower-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .quick-grid { grid-template-columns: 1fr; }
}
</style>
