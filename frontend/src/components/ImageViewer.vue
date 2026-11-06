<script setup lang="ts">
import { onMounted, ref, reactive, watch } from 'vue'
import type { Image } from '@/types'

const props = defineProps<{ image: Image | null; view: { scale: number; tx: number; ty: number } }>()
const emit = defineEmits<{ (e: 'viewport', v: { scale: number; tx: number; ty: number }): void }>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const dragging = ref(false)
const last = reactive({ x: 0, y: 0 })
let bitmap: HTMLImageElement | null = null

function loadBitmap() {
  const url = props.image?.preview_url || props.image?.thumbnail_url
  if (!url) {
    bitmap = null
    draw()
    return
  }
  const image = new Image()
  image.onload = () => {
    bitmap = image
    draw()
  }
  image.onerror = () => {
    bitmap = null
    draw()
  }
  image.src = url
}

function fitScale() {
  if (!canvasRef.value || !props.image) return
  const cw = canvasRef.value.clientWidth
  const ch = canvasRef.value.clientHeight
  return Math.min(cw / props.image.width, ch / props.image.height)
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas || !props.image) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
    canvas.width = cw * dpr
    canvas.height = ch * dpr
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#0f1115'
  ctx.fillRect(0, 0, cw, ch)
  ctx.save()
  ctx.translate(props.view.tx, props.view.ty)
  ctx.scale(props.view.scale, props.view.scale)
  if (bitmap) {
    ctx.drawImage(bitmap, 0, 0, props.image.width, props.image.height)
  } else {
    drawPlaceholder(ctx, props.image)
  }
  ctx.restore()
}

function drawPlaceholder(ctx: CanvasRenderingContext2D, img: Image) {
  const w = img.width
  const h = img.height
  // 模拟超声扇形视野
  ctx.fillStyle = '#08090c'
  ctx.fillRect(0, 0, w, h)
  const grad = ctx.createRadialGradient(w / 2, h * 0.35, 10, w / 2, h * 0.35, w * 0.7)
  grad.addColorStop(0, '#3a3f4a')
  grad.addColorStop(1, '#0b0d12')
  ctx.fillStyle = grad
  ctx.beginPath()
  ctx.moveTo(0, h)
  ctx.arc(w / 2, h * 0.35, w * 0.75, 0, Math.PI)
  ctx.closePath()
  ctx.fill()
  // 病灶
  if (img.class_label && img.class_label !== 'normal') {
    const malignant = img.class_label === 'malignant'
    ctx.fillStyle = malignant ? '#8a8f9c' : '#6a6f7a'
    ctx.beginPath()
    if (malignant) {
      ctx.moveTo(w * 0.5, h * 0.42)
      ctx.quadraticCurveTo(w * 0.62, h * 0.38, w * 0.66, h * 0.5)
      ctx.quadraticCurveTo(w * 0.7, h * 0.62, w * 0.56, h * 0.66)
      ctx.quadraticCurveTo(w * 0.46, h * 0.68, w * 0.42, h * 0.56)
      ctx.quadraticCurveTo(w * 0.38, h * 0.46, w * 0.5, h * 0.42)
    } else {
      ctx.ellipse(w * 0.5, h * 0.55, w * 0.12, h * 0.1, 0, 0, Math.PI * 2)
    }
    ctx.fill()
    if (malignant) {
      ctx.fillStyle = 'rgba(0,0,0,0.35)'
      ctx.beginPath()
      ctx.ellipse(w * 0.52, h * 0.75, w * 0.1, h * 0.06, 0, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.strokeStyle = 'rgba(255,255,255,0.25)'
  ctx.lineWidth = 1
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1)
  ctx.fillStyle = '#e4e7ed'
  ctx.font = '11px sans-serif'
  ctx.fillText(`${img.class_label ?? 'unknown'} · ${img.width}×${img.height}`, 6, 14)
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
  const ns = Math.min(20, Math.max(0.2, props.view.scale * factor))
  const k = ns / props.view.scale
  props.view.tx = mx - (mx - props.view.tx) * k
  props.view.ty = my - (my - props.view.ty) * k
  props.view.scale = ns
  emit('viewport', { ...props.view })
  draw()
}

function onDown(e: MouseEvent) {
  dragging.value = true
  last.x = e.clientX
  last.y = e.clientY
}

function onMove(e: MouseEvent) {
  if (!dragging.value) return
  props.view.tx += e.clientX - last.x
  props.view.ty += e.clientY - last.y
  last.x = e.clientX
  last.y = e.clientY
  draw()
}

function onUp() {
  dragging.value = false
}

function resetView() {
  const s = fitScale()
  if (s) {
    props.view.scale = s
    props.view.tx = 0
    props.view.ty = 0
    emit('viewport', { ...props.view })
  }
  draw()
}

onMounted(() => {
  loadBitmap()
  resetView()
})
watch(() => props.image, () => { loadBitmap(); resetView() }, { deep: true })
defineExpose({ resetView, draw })
</script>

<template>
  <div
    class="im-viewer"
    @wheel.prevent="onWheel"
    @mousedown="onDown"
    @mousemove="onMove"
    @mouseup="onUp"
    @mouseleave="onUp"
    @dblclick="resetView"
  >
    <canvas ref="canvasRef" style="width: 100%; height: 100%"></canvas>
    <div class="hint">滚轮缩放 · 拖拽平移 · 双击复位</div>
  </div>
</template>

<style scoped>
.im-viewer {
  width: 100%;
  height: 100%;
  min-height: 300px;
}
.hint {
  position: absolute;
  left: 8px;
  bottom: 8px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  pointer-events: none;
}
</style>