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

function loadMask() {
  mask = props.rle ? decodeRle(props.rle) : null
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
  if (!mask) return
  ctx.save()
  ctx.translate(props.view.tx, props.view.ty)
  ctx.scale(props.view.scale, props.view.scale)
  ctx.imageSmoothingEnabled = false
  const px = Math.max(1, 1 / props.view.scale)
  ctx.fillStyle = `rgba(244, 67, 54, ${props.opacity})`
  for (let y = 0; y < props.imageHeight; y++) {
    for (let x = 0; x < props.imageWidth; x++) {
      if (mask[y * props.imageWidth + x]) {
        ctx.fillRect(x, y, px, px)
      }
    }
  }
  ctx.restore()
}

watch(() => [props.rle, props.opacity, props.view.scale, props.view.tx, props.view.ty], () => {
  if (props.rle !== undefined) loadMask()
  else draw()
})

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