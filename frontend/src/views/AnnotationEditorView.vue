<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Image, InferenceTask, RleMask } from '@/types'
import * as api from '@/api'
import { usePoll } from '@/composables/usePoll'
import { useAuthStore } from '@/stores/auth'
import ImageViewer from '@/components/ImageViewer.vue'
import MaskCanvas from '@/components/MaskCanvas.vue'
import ResultPanel from '@/components/ResultPanel.vue'

const route = useRoute()
const auth = useAuthStore()
const image = ref<Image | null>(null)
const rle = ref<RleMask | null>(null)
const tool = ref<'brush' | 'eraser' | 'polygon'>('brush')
const brushSize = ref(4)
const view = reactive({ scale: 1, tx: 0, ty: 0 })
const canvasRef = ref<InstanceType<typeof MaskCanvas> | null>(null)
const annotationId = ref('')
const source = ref<'manual' | 'preannot'>('manual')
const preannotLoading = ref(false)
const { poll } = usePoll()

onMounted(async () => {
  const resp = await api.getImage(route.params.imageId as string)
  image.value = (resp as { data: Image }).data
  const hist = await api.getAnnotationHistory(route.params.imageId as string) as { data: any[] }
  const anns = hist.data
  const mine = anns.find((item) => item.annotator?.id === auth.user?.id)
  const approved = anns.find((item) => item.status === 'approved')
  const reference = mine ?? approved ?? anns[0]
  if (reference) {
    rle.value = reference.mask_rle ?? null
    if (reference.source === 'preannot' || reference.source === 'model') source.value = 'preannot'
    annotationId.value = reference.status === 'draft' && reference.annotator?.id === auth.user?.id ? reference.id : ''
  }
})

function onMask(v: RleMask | null) {
  rle.value = v
}

async function preannotate() {
  if (!image.value) return
  if (rle.value) {
    await ElMessageBox.confirm('当前掩膜将被模型结果覆盖，是否继续？', 'AI 预标注', { type: 'warning' })
  }
  preannotLoading.value = true
  try {
    const created = await api.createInference({ image_id: image.value.id }) as {
      data: { task_id?: string; id?: string }
    }
    const taskId = created.data.task_id || created.data.id
    if (!taskId) throw new Error('推理任务未返回 task_id')
    const outcome = await poll(
      async () => (await api.getInference(taskId) as { data: InferenceTask }).data,
      (task) => task.status === 'succeeded' || task.status === 'failed',
      { interval: 1000, attempts: 60 }
    )
    const task = outcome.value
    if (!outcome.done || !task) throw new Error('预标注超时，请稍后重试')
    if (task.status === 'failed') {
      const detail: any = task.error
      throw new Error(detail?.message || detail || '推理失败')
    }
    rle.value = task.result?.mask_rle ?? null
    source.value = 'preannot'
    ElMessage.success(task.result?.mask_rle ? '预标注完成，可继续修边' : '模型判断为无病灶（空掩膜）')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || error?.message || '预标注失败')
  } finally {
    preannotLoading.value = false
  }
}

async function save() {
  if (!image.value) return
  const hasForeground = !!rle.value?.counts.some((count, index) => index % 2 === 1 && count > 0)
  const mask = rle.value ?? {
    size: [image.value.height, image.value.width] as [number, number],
    counts: [image.value.height * image.value.width]
  }
  const resp = await api.saveAnnotation({
    image_id: image.value.id,
    mask_rle: mask,
    is_empty: !hasForeground,
    source: source.value
  }) as { data: { id: string } }
  annotationId.value = resp.data.id
  ElMessage.success(source.value === 'preannot' ? '预标注结果已保存（草稿）' : '标注已保存（草稿）')
}

async function submit() {
  if (!annotationId.value) {
    ElMessage.warning('请先保存草稿，再提交审核')
    return
  }
  await api.submitAnnotation(annotationId.value)
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
        <el-button type="warning" plain :loading="preannotLoading" @click="preannotate">
          {{ preannotLoading ? '预标注中…' : 'AI 预标注' }}
        </el-button>
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