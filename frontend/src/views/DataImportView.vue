<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { Dataset, ImportJob } from '@/types'
import * as api from '@/api'

const datasets = ref<Dataset[]>([])
const datasetId = ref('')
const file = ref<File | null>(null)
const job = reactive<{ status: string; progress: number; total: number; success: number; duplicate: number }>({
  status: 'idle', progress: 0, total: 780, success: 0, duplicate: 0
})
let timer: number | undefined

onMounted(async () => {
  const resp = await api.getDatasets()
  datasets.value = (resp as { data: Dataset[] }).data
  if (datasets.value.length) datasetId.value = datasets.value[0].id
})

function onFileChange(f: { raw: File }) {
  file.value = f.raw
}

function onImport() {
  if (!file.value || !datasetId.value) {
    ElMessage.warning('请选择数据集并上传 ZIP 文件')
    return
  }
  job.status = 'validating'
  job.progress = 0
  const phases = ['validating', 'importing', 'importing', 'completed']
  let i = 0
  timer = window.setInterval(() => {
    i++
    if (i <= 2) job.status = phases[i]
    if (i === 2) { job.progress = 45; job.success = 351; job.duplicate = 0 }
    if (i === 3) { job.progress = 80; job.success = 624 }
    if (i >= 4) {
      job.status = 'completed'
      job.progress = 100
      job.success = 780
      window.clearInterval(timer)
      ElMessage.success('导入完成：780 张，重复 0')
    }
  }, 900)
}
</script>

<template>
  <div>
    <h3 class="page-title">数据接入</h3>
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>上传 BUSI 数据集</template>
          <el-form label-position="top">
            <el-form-item label="目标数据集">
              <el-select v-model="datasetId" placeholder="选择数据集" style="width: 100%">
                <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="ZIP 压缩包">
              <el-upload drag :auto-upload="false" :limit="1" accept=".zip" :on-change="onFileChange" style="width: 100%">
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖拽 ZIP 到此处，或<em>点击选择</em></div>
                <template #tip>
                  <div class="el-upload__tip">支持 .zip；解压后 ≤ 2GB、文件数 ≤ 2000</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-button type="primary" @click="onImport">开始导入</el-button>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>导入进度</template>
          <el-empty v-if="job.status === 'idle'" description="尚未开始导入" :image-size="80" />
          <template v-else>
            <el-steps :active="['idle','validating','importing','completed'].indexOf(job.status)" finish-status="success" align-center>
              <el-step title="校验" />
              <el-step title="导入" />
              <el-step title="完成" />
            </el-steps>
            <el-progress :percentage="job.progress" :status="job.status === 'completed' ? 'success' : undefined" style="margin: 24px 0" />
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="总数">780</el-descriptions-item>
              <el-descriptions-item label="成功">{{ job.success }}</el-descriptions-item>
              <el-descriptions-item label="失败">0</el-descriptions-item>
              <el-descriptions-item label="重复">{{ job.duplicate }}</el-descriptions-item>
            </el-descriptions>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
</style>