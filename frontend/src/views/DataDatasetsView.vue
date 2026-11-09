<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ClassLabel, Dataset, DatasetVersion } from '@/types'
import * as api from '@/api'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const datasets = ref<Dataset[]>([])
const versions = ref<DatasetVersion[]>([])

const dialogVisible = ref(false)
const submitting = ref(false)
const form = reactive({
  version: null as DatasetVersion | null,
  count: 20,
  priority: 3,
  required_annotators: 1,
  class_labels: [] as ClassLabel[]
})

const classOptions: { value: ClassLabel; label: string }[] = [
  { value: 'benign', label: '良性' },
  { value: 'malignant', label: '恶性' },
  { value: 'normal', label: '正常' }
]

const frozenVersions = computed(() => versions.value.filter((v) => v.status === 'frozen'))

onMounted(async () => {
  const r1 = await api.getDatasets()
  datasets.value = (r1 as { data: Dataset[] }).data
  const r2 = await api.getDatasetVersions()
  versions.value = (r2 as { data: DatasetVersion[] }).data
})

async function freeze(v: DatasetVersion) {
  if (v.status === 'frozen') return
  await api.freezeDatasetVersion(v.id)
  ElMessage.success('版本已冻结')
  v.status = 'frozen'
}

async function archive(v: DatasetVersion) {
  await ElMessageBox.confirm(
    '归档后版本不再参与新的训练/标注任务，已冻结的 manifest 与成员保持不变。确认归档？',
    '归档版本',
    { type: 'warning' }
  )
  await api.archiveDatasetVersion(v.id)
  v.status = 'archived'
  ElMessage.success('版本已归档')
}

function openTaskDialog(v: DatasetVersion) {
  form.version = v
  form.count = Math.min(20, v.counts.train + v.counts.val + v.counts.test || 20)
  form.priority = 3
  form.class_labels = []
  dialogVisible.value = true
}

async function createTasks() {
  if (!form.version) return
  submitting.value = true
  try {
    const resp = await api.createAnnotationTasks({
      dataset_version_id: form.version.id,
      count: form.count,
      class_labels: form.class_labels.length ? form.class_labels : undefined,
      priority: form.priority,
      required_annotators: form.required_annotators
    }) as { data: { created: number } }
    const created = resp.data.created
    dialogVisible.value = false
    if (!created) {
      ElMessage.warning('没有可创建的标注任务（候选影像可能已存在未完成任务）')
      return
    }
    ElMessage.success(`已创建 ${created} 个标注任务`)
    router.push('/annotation/tasks')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '创建标注任务失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <h3 class="page-title">数据集版本</h3>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card v-for="d in datasets" :key="d.id" shadow="never" style="margin-bottom: 16px">
          <template #header>数据集</template>
          <p><strong>{{ d.name }}</strong></p>
          <p class="muted">{{ d.description }}</p>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="影像数">{{ d.image_count }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ d.created_at }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never">
          <template #header>版本列表</template>
          <el-table :data="versions" border stripe>
            <el-table-column prop="version" label="版本" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><StatusTag :status="row.status" /></template>
            </el-table-column>
            <el-table-column prop="split_seed" label="种子" width="70" />
            <el-table-column label="划分" width="180">
              <template #default="{ row }">{{ row.counts.train }} / {{ row.counts.val }} / {{ row.counts.test }}</template>
            </el-table-column>
            <el-table-column prop="frozen_at" label="冻结时间" />
            <el-table-column label="操作" width="260">
              <template #default="{ row }">
                <el-button v-if="row.status === 'draft'" size="small" type="primary" @click="freeze(row)">冻结</el-button>
                <el-button v-if="row.status === 'frozen'" size="small" @click="openTaskDialog(row)">生成标注任务</el-button>
                <el-button v-if="row.status === 'frozen'" size="small" type="danger" plain @click="archive(row)">归档</el-button>
                <span v-if="row.status === 'archived'" class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" title="生成标注任务" width="480px">
      <el-form label-width="96px">
        <el-form-item label="数据集版本">
          <span>{{ form.version?.version }}</span>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.count" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="1" :max="10" />
          <span class="muted" style="margin-left: 8px">数字越大越优先</span>
        </el-form-item>
        <el-form-item label="标注人数">
          <el-radio-group v-model="form.required_annotators">
            <el-radio-button :value="1">单人</el-radio-button>
            <el-radio-button :value="2">双人（一致性校验）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="类别筛选">
          <el-select v-model="form.class_labels" multiple clearable placeholder="不限" style="width: 100%">
            <el-option v-for="opt in classOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="muted" style="font-size: 12px">
        仅从已冻结版本中挑选尚无未完成标注任务的影像，最多创建 {{ form.count }} 个。
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="createTasks">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.muted { color: #909399; }
</style>
