<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import type { RleMask } from '@/types'
import { decodeRle, encodeRle, emptyMask } from '@/utils/rle'

const props = withDefaults(
  defineProps<{
    imageWidth: number
    imageHeight: number
    view: { scale: number; tx: number; ty: number }
    tool: 'brush' | 'eraser' | 'polygon'
    brushSize: number
    modelValue: RleMask | null
  }>(),
  { brushSize: 4 }
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: RleMask | null): void
  (e: 'changed'): void
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const mask = ref<Uint8Array>(emptyMask(props.imageHeight, props.imageWidth))
const undoStack = ref<Uint8Array[]>([])
const redoStack = ref<Uint8Array[]>([])
const drawing = ref(false)
const points = ref<{ x: number; y: number }[]>([])

function syncFromModel() {
  mask.value = props.modelValue ? decodeRle(props.modelValue) : emptyMask(props.imageHeight, props.imageWidth)
  undoStack.value = []
  redoStack.value = []
  draw()
}

function emitMask() {
  const hasFg = mask.value.some((v) => v === 1)
  emit('update:modelValue', hasFg ? { size: [props.imageHeight, props.imageWidth], counts: encodeRle(mask.value, props.imageHeight, props.imageWidth) } : null)
}

function snapshot() {
  undoStack.value.push(mask.value.slice())
  if (undoStack.value.length > 60) undoStack.value.shift()
  redoStack.value = []
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
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
  ctx.clearRect(0, 0, cw, ch)
  ctx.save()
  ctx.translate(props.view.tx, props.view.ty)
  ctx.scale(props.view.scale, props.view.scale)
  ctx.imageSmoothingEnabled = false
  const px = Math.max(1, 1 / props.view.scale)
  ctx.fillStyle = 'rgba(244, 67, 54, 0.45)'
  for (let y = 0; y < props.imageHeight; y++) {
    for (let x = 0; x < props.imageWidth; x++) {
      if (mask.value[y * props.imageWidth + x]) ctx.fillRect(x, y, px, px)
    }
  }
  // 多边形预览
  if (points.value.length) {
    ctx.strokeStyle = '#ff7043'
    ctx.lineWidth = 2 / props.view.scale
    ctx.beginPath()
    ctx.moveTo(points.value[0].x, points.value[0].y)
    for (const p of points.value.slice(1)) ctx.lineTo(p.x, p.y)
    ctx.closePath()
    ctx.stroke()
    points.value.forEach((p) => {
      ctx.beginPath()
      ctx.arc(p.x, p.y, 3 / props.view.scale, 0, Math.PI * 2)
      ctx.fillStyle = '#ff7043'
      ctx.fill()
    })
  }
  ctx.restore()
}

function toImage(e: MouseEvent): { x: number; y: number } {
  const rect = canvasRef.value!.getBoundingClientRect()
  const sx = e.clientX - rect.left
  const sy = e.clientY - rect.top
  return { x: Math.floor((sx - props.view.tx) / props.view.scale), y: Math.floor((sy - props.view.ty) / props.view.scale) }
}

function paintAt(x: number, y: number) {
  const r = props.brushSize
  const v = props.tool === 'eraser' ? 0 : 1
  for (let dy = -r; dy <= r; dy++) {
    for (let dx = -r; dx <= r; dx++) {
      if (dx * dx + dy * dy > r * r) continue
      const px = x + dx
      const py = y + dy
      if (px < 0 || py < 0 || px >= props.imageWidth || py >= props.imageHeight) continue
      mask.value[py * props.imageWidth + px] = v
    }
  }
}

function onDown(e: MouseEvent) {
  if (props.tool === 'polygon') {
    const p = toImage(e)
    points.value.push(p)
    draw()
    return
  }
  drawing.value = true
  snapshot()
  const p = toImage(e)
  paintAt(p.x, p.y)
  draw()
}

function onMove(e: MouseEvent) {
  if (props.tool !== 'polygon' && drawing.value) {
    const p = toImage(e)
    paintAt(p.x, p.y)
    draw()
  }
}

function onUp() {
  if (drawing.value) {
    drawing.value = false
    emitMask()
    emit('changed')
  }
}

function closePolygon() {
  if (points.value.length < 3) {
    points.value = []
    draw()
    return
  }
  snapshot()
  fillPolygon(mask.value, props.imageWidth, props.imageHeight, points.value.map((p) => [p.x, p.y]))
  points.value = []
  emitMask()
  emit('changed')
  draw()
}

function fillPolygon(m: Uint8Array, w: number, h: number, poly: number[][]) {
  const minY = Math.max(0, Math.floor(Math.min(...poly.map((p) => p[1]))))
  const maxY = Math.min(h - 1, Math.ceil(Math.max(...poly.map((p) => p[1]))))
  for (let y = minY; y <= maxY; y++) {
    const xs: number[] = []
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i]
      const [x2, y2] = poly[(i + 1) % poly.length]
      if ((y1 <= y && y2 > y) || (y2 <= y && y1 > y)) {
        xs.push(x1 + ((y - y1) / (y2 - y1)) * (x2 - x1))
      }
    }
    xs.sort((a, b) => a - b)
    for (let i = 0; i < xs.length; i += 2) {
      const from = Math.max(0, Math.ceil(xs[i]))
      const to = Math.min(w - 1, Math.floor(xs[i + 1] ?? xs[i]))
      for (let x = from; x <= to; x++) m[y * w + x] = 1
    }
  }
}

function undo() {
  if (!undoStack.value.length) return
  redoStack.value.push(mask.value.slice())
  mask.value = undoStack.value.pop()!
  emitMask()
  emit('changed')
  draw()
}

function redo() {
  if (!redoStack.value.length) return
  undoStack.value.push(mask.value.slice())
  mask.value = redoStack.value.pop()!
  emitMask()
  emit('changed')
  draw()
}

function clear() {
  snapshot()
  mask.value = emptyMask(props.imageHeight, props.imageWidth)
  points.value = []
  emitMask()
  emit('changed')
  draw()
}

watch(() => props.modelValue, () => {
  if (!drawing.value) syncFromModel()
})

watch(() => [props.view.scale, props.view.tx, props.view.ty], () => draw())

onMounted(syncFromModel)

defineExpose({ undo, redo, clear, closePolygon })
</script>

<template>
  <canvas
    ref="canvasRef"
    class="mask-canvas"
    style="width: 100%; height: 100%"
    @mousedown="onDown"
    @mousemove="onMove"
    @mouseup="onUp"
    @mouseleave="onUp"
    @dblclick="tool === 'polygon' && closePolygon()"
  ></canvas>
</template>

<style scoped>
.mask-canvas {
  position: absolute;
  inset: 0;
  cursor: crosshair;
}
</style>