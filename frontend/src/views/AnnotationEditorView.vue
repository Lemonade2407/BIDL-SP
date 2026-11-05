<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Image, RleMask } from '@/types'
import * as api from '@/api'
import ImageViewer from '@/components/ImageViewer.vue'
import MaskCanvas from '@/components/MaskCanvas.vue'
import ResultPanel from '@/components/ResultPanel.vue'

const route = useRoute()
const image = ref<Image | null>(null)
const rle = ref<RleMask | null>(null)
const tool = ref<'brush' | 'eraser' | 'polygon'>('brush')
const brushSize = ref(4)
const view = reactive({ scale: 1, tx: 0, ty: 0 })
const canvasRef = ref<InstanceType<typeof MaskCanvas> | null>(null)

onMounted(async () => {
  const resp = await api.getImage(route.params.imageId as string)
  image.value = (resp as { data: Image }).data
  const hist = await api.getAnnotationHistory(route.params.imageId as string)
  const anns = (hist as { data: any[] }).data
  if (anns.length) rle.value = anns[0].mask_rle ?? null
})

function onMask(v: RleMask | null) {
  rle.value = v
}

async function save() {
  await api.saveAnnotation({ image_id: image.value!.id, mask_rle: rle.value, is_empty: !rle.value, source: 'manual', status: 'draft' })
  ElMessage.success('标注已保存（草稿）')
}

async function submit() {
  await api.submitAnnotation('ann-1')
  ElMessage.success('已提交审核')
}
</script>

<template>
  <div>
    <h3 class="page-title">掩膜编辑 · {{ image?.id }}</h3>
    <el-card shadow="never">
      <div class="toolbar">
        <el-radio-group v-model="tool">
          <el-radio-button value="brush">画笔 B</el-radio-button>
          <el-radio-button value="eraser">橡皮 E</el-radio-button>
          <el-radio-button value="polygon">多边形</el-radio-button>
        </el-radio-group>
        <span class="sep" />
        <el-text size="small">画笔大小</el-text>
        <el-slider v-model="brushSize" :min="1" :max="16" style="width: 140px" />
        <span class="sep" />
        <el-button size="small" @click="canvasRef?.undo()">撤销 Ctrl+Z</el-button>
        <el-button size="small" @click="canvasRef?.redo()">重做</el-button>
        <el-button size="small" @click="canvasRef?.clear()">清空</el-button>
        <el-button v-if="tool === 'polygon'" size="small" type="warning" @click="canvasRef?.closePolygon()">闭合多边形</el-button>
        <span class="flex" />
        <el-button type="primary" @click="save">保存草稿</el-button>
        <el-button type="success" @click="submit">提交审核</el-button>
      </div>
      <div class="editor">
        <div class="canvas-box">
          <ImageViewer :image="image" :view="view" />
          <MaskCanvas
            v-if="image"
            ref="canvasRef"
            :image-width="image.width"
            :image-height="image.height"
            :view="view"
            :tool="tool"
            :brush-size="brushSize"
            :model-value="rle"
            @update:model-value="onMask"
          />
        </div>
        <div class="side">
          <ResultPanel :result="null" />
          <el-card shadow="never" style="margin-top: 12px">
            <template #header>操作说明</template>
            <ul class="help">
              <li>Space 平移 · +/- 缩放 · B 画笔 · E 橡皮</li>
              <li>Ctrl+Z 撤销 · 双击复位视图</li>
              <li>多边形：单击加点，双击或按钮闭合</li>
              <li>保存草稿后请「提交审核」进入审核流程</li>
            </ul>
          </el-card>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.sep { width: 1px; height: 20px; background: #ebeef5; }
.flex { flex: 1; }
.editor { display: flex; gap: 12px; }
.canvas-box { flex: 1; position: relative; height: 560px; }
.side { width: 300px; }
.help { margin: 0; padding-left: 18px; color: #606266; font-size: 13px; line-height: 1.8; }
</style>