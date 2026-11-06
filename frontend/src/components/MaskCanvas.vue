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

// 离屏掩膜画布：绘制时只做一次 drawImage，避免每次移动遍历整张影像。
let maskCanvas: HTMLCanvasElement | null = null
let maskCtx: CanvasRenderingContext2D | null = null
let lastPoint: { x: number; y: number } | null = null
// 父组件回传自己刚 emit 的值时不要重建掩膜，否则撤销栈会被清空。
let lastEmitted: RleMask | null = null

function maskSurface() {
  if (!maskCanvas) maskCanvas = document.createElement('canvas')
  if (maskCanvas.width !== props.imageWidth || maskCanvas.height !== props.imageHeight) {
    maskCanvas.width = props.imageWidth
    maskCanvas.height = props.imageHeight
    maskCtx = maskCanvas.getContext('2d')
  }
  if (!maskCtx) maskCtx = maskCanvas.getContext('2d')
  return maskCtx!
}

function renderMask() {
  const ctx = maskSurface()
  const w = props.imageWidth
  const h = props.imageHeight
  const data = ctx.createImageData(w, h)
  const pixels = data.data
  for (let i = 0; i < mask.value.length; i++) {
    if (!mask.value[i]) continue
    const offset = i * 4
    pixels[offset] = 244
    pixels[offset + 1] = 67
    pixels[offset + 2] = 54
    pixels[offset + 3] = 255
  }
  ctx.putImageData(data, 0, 0)
}

function syncFromModel() {
  mask.value = props.modelValue ? decodeRle(props.modelValue) : emptyMask(props.imageHeight, props.imageWidth)
  undoStack.value = []
  redoStack.value = []
  renderMask()
  draw()
}

function emitMask() {
  const hasFg = mask.value.some((v) => v === 1)
  const value = hasFg
    ? { size: [props.imageHeight, props.imageWidth] as [number, number], counts: encodeRle(mask.value, props.imageHeight, props.imageWidth) }
    : null
  lastEmitted = value
  emit('update:modelValue', value)
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
  if (maskCanvas) {
    ctx.globalAlpha = 0.45
    ctx.drawImage(maskCanvas, 0, 0, props.imageWidth, props.imageHeight)
    ctx.globalAlpha = 1
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

function toImage(e: { clientX: number; clientY: number }): { x: number; y: number } {
  const rect = canvasRef.value!.getBoundingClientRect()
  const sx = e.clientX - rect.left
  const sy = e.clientY - rect.top
  return {
    x: Math.floor((sx - props.view.tx) / props.view.scale),
    y: Math.floor((sy - props.view.ty) / props.view.scale)
  }
}

function paintAt(x: number, y: number) {
  const radius = props.brushSize
  const eraser = props.tool === 'eraser'
  const ctx = maskSurface()
  ctx.save()
  ctx.globalCompositeOperation = eraser ? 'destination-out' : 'source-over'
  ctx.fillStyle = '#f44336'
  ctx.beginPath()
  ctx.arc(x + 0.5, y + 0.5, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
  const value = eraser ? 0 : 1
  for (let dy = -radius; dy <= radius; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      if (dx * dx + dy * dy > radius * radius) continue
      const px = x + dx
      const py = y + dy
      if (px < 0 || py < 0 || px >= props.imageWidth || py >= props.imageHeight) continue
      mask.value[py * props.imageWidth + px] = value
    }
  }
}

// 快速拖动时按笔刷半径插值，避免出现断点。
function paintLine(from: { x: number; y: number }, to: { x: number; y: number }) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const distance = Math.hypot(dx, dy)
  const steps = Math.max(1, Math.ceil(distance / Math.max(1, props.brushSize / 2)))
  for (let i = 1; i <= steps; i++) {
    paintAt(Math.round(from.x + (dx * i) / steps), Math.round(from.y + (dy * i) / steps))
  }
}

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  e.preventDefault()
  canvasRef.value?.setPointerCapture?.(e.pointerId)
  if (props.tool === 'polygon') {
    points.value.push(toImage(e))
    draw()
    return
  }
  drawing.value = true
  snapshot()
  const p = toImage(e)
  lastPoint = p
  paintAt(p.x, p.y)
  draw()
}

function onPointerMove(e: PointerEvent) {
  if (!drawing.value || props.tool === 'polygon') return
  const p = toImage(e)
  if (lastPoint) paintLine(lastPoint, p)
  else paintAt(p.x, p.y)
  lastPoint = p
  draw()
}

function finishStroke(e?: PointerEvent) {
  if (e) canvasRef.value?.releasePointerCapture?.(e.pointerId)
  if (!drawing.value) return
  drawing.value = false
  lastPoint = null
  emitMask()
  emit('changed')
}

function onPointerLeave(e: PointerEvent) {
  // 指针捕获成功时继续接收 move/up，不提前结束笔画。
  if (canvasRef.value?.hasPointerCapture?.(e.pointerId)) return
  finishStroke()
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
  renderMask()
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
  renderMask()
  emitMask()
  emit('changed')
  draw()
}

function redo() {
  if (!redoStack.value.length) return
  undoStack.value.push(mask.value.slice())
  mask.value = redoStack.value.pop()!
  renderMask()
  emitMask()
  emit('changed')
  draw()
}

function clear() {
  snapshot()
  mask.value = emptyMask(props.imageHeight, props.imageWidth)
  points.value = []
  renderMask()
  emitMask()
  emit('changed')
  draw()
}

watch(
  () => props.modelValue,
  (value) => {
    if (drawing.value || value === lastEmitted) return
    syncFromModel()
  }
)

watch(() => [props.view.scale, props.view.tx, props.view.ty], () => draw())

onMounted(syncFromModel)

defineExpose({ undo, redo, clear, closePolygon })
</script>

<template>
  <canvas
    ref="canvasRef"
    class="mask-canvas"
    style="width: 100%; height: 100%"
    @pointerdown.prevent="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="finishStroke"
    @pointercancel="finishStroke"
    @pointerleave="onPointerLeave"
    @contextmenu.prevent
    @dblclick="tool === 'polygon' && closePolygon()"
  ></canvas>
</template>

<style scoped>
.mask-canvas {
  position: absolute;
  inset: 0;
  cursor: crosshair;
  touch-action: none;
  user-select: none;
}
</style>
