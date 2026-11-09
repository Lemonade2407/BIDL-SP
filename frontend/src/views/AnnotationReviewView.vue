<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Annotation, Image } from '@/types'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import { decodeRle } from '@/utils/rle'
import ImageViewer from '@/components/ImageViewer.vue'
import MaskOverlay from '@/components/MaskOverlay.vue'
import StatusTag from '@/components/StatusTag.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const annotation = ref<Annotation | null>(null)
const image = ref<Image | null>(null)
const pendingPeers = ref<Annotation[]>([])
const view = reactive({ scale: 1, tx: 0, ty: 0 })
const opacity = ref(0.6)
const loading = ref(false)
const isOwn = computed(() => annotation.value?.annotator?.id === auth.user?.id)
const isArbitration = computed(() => pendingPeers.value.length > 1)

const pairIou = computed(() => {
  if (pendingPeers.value.length !== 2) return null
  const [a, b] = pendingPeers.value
  if (!a.mask_rle || !b.mask_rle) return null
  const left = decodeRle(a.mask_rle)
  const right = decodeRle(b.mask_rle)
  let intersection = 0
  let union = 0
  for (let i = 0; i < left.length; i++) {
    const x = left[i] ? 1 : 0
    const y = right[i] ? 1 : 0
    if (x & y) intersection++
    if (x | y) union++
  }
  return union ? intersection / union : 1
})

onMounted(async () => {
  const annotationResp = await api.getAnnotation(route.params.annotationId as string) as { data: Annotation }
  annotation.value = annotationResp.data
  const imageResp = await api.getImage(annotationResp.data.image_id) as { data: Image }
  image.value = imageResp.data
  const history = await api.getAnnotationHistory(annotationResp.data.image_id) as { data: Annotation[] }
  pendingPeers.value = history.data.filter((item) => item.status === 'pending')
})

function switchPeer(peer: Annotation) {
  if (peer.id === annotation.value?.id) return
  annotation.value = peer
  view.scale = 1
  view.tx = 0
  view.ty = 0
}

async function review(decision: 'approve' | 'reject', comment?: string) {
  if (!annotation.value) return
  loading.value = true
  try {
    await api.reviewAnnotation(annotation.value.id, { decision, comment })
    ElMessage.success(decision === 'approve' ? '标注已通过' : '标注已驳回')
    router.push('/annotation/tasks')
  } catch {
    // 错误提示由拦截器处理
  } finally {
    loading.value = false
  }
}

async function approve() {
  await ElMessageBox.confirm('确认通过该标注版本？', '审核确认', { type: 'warning' })
  await review('approve', '审核通过')
}

async function reject() {
  const { value } = await ElMessageBox.prompt('请输入驳回原因，标注员会看到该意见', '驳回标注', {
    inputPlaceholder: '例如：边缘需重新修整',
    inputValidator: (input) => (input && input.trim() ? true : '驳回必须填写意见')
  })
  await review('reject', value.trim())
}
</script>

<template>
  <div>
    <div class="head">
      <div>
        <h3 class="page-title">标注审核</h3>
        <div v-if="annotation" class="meta">
          <StatusTag :status="annotation.status" />
          <span>版本 v{{ annotation.version }}</span>
          <span>标注人：{{ annotation.annotator?.display_name || '—' }}</span>
          <span v-if="annotation.note">备注：{{ annotation.note }}</span>
        </div>
      </div>
      <el-button @click="router.push('/annotation/tasks')">返回任务列表</el-button>
    </div>

    <el-card v-if="isArbitration" shadow="never" class="arbitration" style="margin-bottom: 12px">
      <template #header>双人标注仲裁</template>
      <div class="peer-bar">
        <button
          v-for="peer in pendingPeers"
          :key="peer.id"
          type="button"
          class="peer"
          :class="{ active: peer.id === annotation?.id }"
          @click="switchPeer(peer)"
        >
          {{ peer.annotator?.display_name || '标注员' }} · v{{ peer.version }}
        </button>
        <el-tag v-if="pairIou !== null" :type="pairIou >= 0.8 ? 'success' : 'danger'">
          一致性 IoU {{ pairIou.toFixed(4) }}
        </el-tag>
        <span class="muted">选择更准确的版本后点击「通过」，另一版本将自动驳回</span>
      </div>
    </el-card>

    <el-row v-if="annotation && image" :gutter="16">
      <el-col :span="17">
        <el-card shadow="never">
          <div class="viewer-box">
            <ImageViewer :image="image" :view="view" />
            <MaskOverlay
              :rle="annotation.mask_rle"
              :image-width="image.width"
              :image-height="image.height"
              :view="view"
              :opacity="opacity"
            />
          </div>
          <div class="slider">
            <span class="muted">掩膜透明度</span>
            <el-slider v-model="opacity" :min="0" :max="1" :step="0.05" style="width: 240px" />
          </div>
        </el-card>
      </el-col>

      <el-col :span="7">
        <el-card shadow="never">
          <template #header>影像信息</template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="影像 ID">{{ image.id }}</el-descriptions-item>
            <el-descriptions-item label="类别">{{ image.class_label || '—' }}</el-descriptions-item>
            <el-descriptions-item label="尺寸">{{ image.width }}×{{ image.height }}</el-descriptions-item>
            <el-descriptions-item label="掩膜">{{ annotation.is_empty ? '空掩膜' : '含前景' }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ annotation.source }}</el-descriptions-item>
          </el-descriptions>

          <div class="review-box">
            <template v-if="annotation.status === 'pending' && !isOwn">
              <el-button type="success" :loading="loading" style="width: 100%" @click="approve">通过</el-button>
              <el-button type="danger" :loading="loading" style="width: 100%; margin: 10px 0 0" @click="reject">驳回</el-button>
            </template>
            <el-alert v-else-if="isOwn" type="warning" :closable="false" show-icon title="不能审核本人标注，请由其他审核医师处理" />
            <el-alert v-else type="info" :closable="false" show-icon
              :title="`当前状态：${annotation.status}，无需再次审核`" />
          </div>

          <div v-if="annotation.review_comment" class="comment">
            <div class="comment-title">历史审核意见</div>
            <div class="muted">{{ annotation.review_comment }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-else description="加载中…" />
  </div>
</template>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0 0 8px; }
.meta { display: flex; flex-wrap: wrap; gap: 10px; color: #909399; font-size: 12px; }
.viewer-box { position: relative; height: 520px; }
.slider { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.muted { color: #909399; font-size: 12px; }
.review-box { margin-top: 16px; }
.comment { margin-top: 16px; }
.comment-title { margin-bottom: 6px; font-size: 12px; font-weight: 600; }
.peer-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.peer {
  padding: 7px 14px;
  border: 1px solid #e4efec;
  border-radius: 9px;
  background: #fbfefd;
  color: #475569;
  font-size: 12px;
  cursor: pointer;
}
.peer.active { border-color: #2f9d8f; background: #eaf7f4; color: #175e55; }
</style>
