<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import type { RleMask } from '@/types'
import { decodeRle } from '@/utils/rle'

const props = defineProps<{
  rle: RleMask | null
  imageWidth: number
  imageHeight: number
  view: { scale: number; tx: number; ty: number }
  opacity: number
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let mask: Uint8Array | null = null
let maskCanvas: HTMLCanvasElement | null = null
let maskCtx: CanvasRenderingContext2D | null = null

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
  const data = ctx.createImageData(props.imageWidth, props.imageHeight)
  if (mask) {
    const pixels = data.data
    for (let i = 0; i < mask.length; i++) {
      if (!mask[i]) continue
      const offset = i * 4
      pixels[offset] = 244
      pixels[offset + 1] = 67
      pixels[offset + 2] = 54
      pixels[offset + 3] = 255
    }
  }
  ctx.putImageData(data, 0, 0)
}

function loadMask() {
  mask = props.rle ? decodeRle(props.rle) : null
  renderMask()
  draw()
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
  if (!mask || !maskCanvas) return
  ctx.save()
  ctx.translate(props.view.tx, props.view.ty)
  ctx.scale(props.view.scale, props.view.scale)
  ctx.imageSmoothingEnabled = false
  ctx.globalAlpha = props.opacity
  ctx.drawImage(maskCanvas, 0, 0, props.imageWidth, props.imageHeight)
  ctx.restore()
}

watch(() => props.rle, loadMask)
watch(
  () => [props.opacity, props.view.scale, props.view.tx, props.view.ty],
  () => draw()
)

onMounted(loadMask)
</script>

<template>
  <canvas ref="canvasRef" class="overlay" style="width: 100%; height: 100%"></canvas>
</template>

<style scoped>
.overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
</style>
