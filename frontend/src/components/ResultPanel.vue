<script setup lang="ts">
import { computed } from 'vue'
import type { InferenceResult } from '@/types'

const props = defineProps<{ result: InferenceResult | null }>()

const flagText: Record<string, string> = {
  EMPTY_MASK: '空掩膜',
  AREA_TOO_LARGE: '面积过大',
  LOW_CONFIDENCE: '低置信度',
  MULTI_LESION: '多病灶',
  MASK_MISSING: '掩膜缺失'
}

const rows = computed(() => {
  const r = props.result
  if (!r) return []
  return [
    { label: '前景平均概率', value: (r.prob_mean * 100).toFixed(1) + '%' },
    { label: '病灶面积占比', value: (r.lesion_area_ratio * 100).toFixed(2) + '%' },
    { label: '推理耗时', value: r.elapsed_ms + ' ms' },
    { label: '质量标记', value: r.quality_flags.length ? r.quality_flags.map((f) => flagText[f] ?? f).join('、') : '无' }
  ]
})
</script>

<template>
  <el-card shadow="never" class="result-panel">
    <template #header>模型分析结果</template>
    <el-empty v-if="!result" description="尚未触发推理" :image-size="60" />
    <el-descriptions v-else :column="1" size="small" border>
      <el-descriptions-item v-for="row in rows" :key="row.label" :label="row.label">
        {{ row.value }}
      </el-descriptions-item>
    </el-descriptions>
  </el-card>
</template>