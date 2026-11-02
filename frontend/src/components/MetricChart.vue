<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

interface Variant {
  version: string
  dice: number
  precision: number
  recall: number
  hd95: number
  seeds: number[]
}

const props = defineProps<{ variants: Variant[] }>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const sd = (arr: number[], mean: number) =>
    Math.sqrt(arr.reduce((s, x) => s + (x - mean) ** 2, 0) / arr.length)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Dice', 'Precision', 'Recall'] },
    xAxis: { type: 'category', data: props.variants.map((v) => v.version) },
    yAxis: { type: 'value', min: 0, max: 1 },
    series: [
      {
        name: 'Dice',
        type: 'bar',
        barWidth: 24,
        data: props.variants.map((v) => ({
          value: v.dice,
          itemStyle: { color: '#409eff' }
        })),
        label: {
          show: true,
          position: 'top',
          formatter: (p: any) => {
            const v = props.variants[p.dataIndex]
            return `${v.dice.toFixed(4)} ± ${sd(v.seeds, v.dice).toFixed(4)}`
          },
          fontSize: 10
        }
      },
      { name: 'Precision', type: 'line', data: props.variants.map((v) => v.precision), smooth: true },
      { name: 'Recall', type: 'line', data: props.variants.map((v) => v.recall), smooth: true }
    ]
  })
}

function resize() { chart?.resize() }

onMounted(() => { render(); window.addEventListener('resize', resize) })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
watch(() => props.variants, render, { deep: true })
</script>

<template>
  <div ref="el" class="metric-chart"></div>
</template>

<style scoped>
.metric-chart {
  width: 100%;
  height: 320px;
}
</style>