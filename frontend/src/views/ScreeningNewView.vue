<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Image, Patient, Study } from '@/types'
import * as api from '@/api'

const router = useRouter()
const currentYear = new Date().getFullYear()
const loading = ref(false)
const images = ref<Image[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const selected = ref<Image[]>([])
const tableRef = ref<{ clearSelection: () => void } | null>(null)

const form = reactive({
  gender: 'F' as 'M' | 'F' | 'O',
  birth_year: 1975,
  remark: '',
  study_no: '',
  modality: 'US' as 'US' | 'MG',
  device: '',
  study_date: new Date().toISOString().slice(0, 10),
  indication: '',
  createTask: true,
  priority: 3
})

const filter = reactive({ q: '', class_label: '' })

async function fetchImages() {
  const resp = await api.getImages({
    page: page.value,
    page_size: pageSize,
    unassigned: true,
    q: filter.q || undefined,
    class_label: filter.class_label || undefined
  }) as { data: Image[]; meta?: { total?: number } }
  images.value = resp.data
  total.value = resp.meta?.total ?? resp.data.length
}

function search() {
  page.value = 1
  fetchImages()
}

function onSelection(rows: Image[]) {
  selected.value = rows
}

function clearSelection() {
  selected.value = []
  tableRef.value?.clearSelection()
}

async function submit() {
  if (!selected.value.length) {
    ElMessage.warning('请至少选择一张影像')
    return
  }
  loading.value = true
  try {
    const patient = await api.createPatient({
      gender: form.gender,
      birth_year: form.birth_year || null,
      remark: form.remark || null
    }) as { data: Patient }
    const study = await api.createStudy({
      patient_id: patient.data.id,
      study_no: form.study_no || undefined,
      modality: form.modality,
      device: form.device || null,
      study_date: form.study_date,
      indication: form.indication || null,
      image_ids: selected.value.map((item) => item.id)
    }) as { data: Study }
    if (form.createTask) {
      await api.createScreenTask({ study_id: study.data.id, priority: form.priority })
    }
    ElMessage.success(form.createTask ? '检查已创建并进入筛查队列' : '检查已创建')
    router.push('/screening/worklist')
  } catch {
    // 错误提示由拦截器处理
  } finally {
    loading.value = false
  }
}

onMounted(fetchImages)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">新建检查</h3>
      <el-button @click="router.push('/screening/worklist')">返回工作台</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>患者与检查信息</template>
          <el-form label-position="top" :model="form">
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="性别">
                  <el-select v-model="form.gender" style="width: 100%">
                    <el-option label="女" value="F" />
                    <el-option label="男" value="M" />
                    <el-option label="其他" value="O" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="出生年份">
                  <el-input-number v-model="form.birth_year" :min="1900" :max="currentYear" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="患者备注">
              <el-input v-model="form.remark" maxlength="255" placeholder="可选，不填写姓名等身份信息" />
            </el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="检查号">
                  <el-input v-model="form.study_no" placeholder="留空自动生成" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="检查日期">
                  <el-date-picker v-model="form.study_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="模态">
                  <el-select v-model="form.modality" style="width: 100%">
                    <el-option label="超声 US" value="US" />
                    <el-option label="钼靶 MG" value="MG" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="设备">
                  <el-input v-model="form.device" placeholder="可选" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="申请指征">
              <el-input v-model="form.indication" type="textarea" :rows="2" maxlength="255" placeholder="可选" />
            </el-form-item>
            <el-form-item label="筛查任务">
              <el-checkbox v-model="form.createTask">创建后立即进入筛查工作台</el-checkbox>
            </el-form-item>
            <el-form-item v-if="form.createTask" label="优先级">
              <el-select v-model="form.priority" style="width: 160px">
                <el-option v-for="n in 5" :key="n" :label="`P${n}`" :value="n" />
              </el-select>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>选择影像（仅未关联检查）</span>
              <span class="muted">已选 {{ selected.length }} 张</span>
            </div>
          </template>
          <el-form inline @submit.prevent="search">
            <el-form-item>
              <el-input v-model="filter.q" placeholder="文件名 / ID" clearable style="width: 200px" />
            </el-form-item>
            <el-form-item>
              <el-select v-model="filter.class_label" placeholder="类别" clearable style="width: 140px">
                <el-option label="良性" value="benign" />
                <el-option label="恶性" value="malignant" />
                <el-option label="正常" value="normal" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit">查询</el-button>
            </el-form-item>
            <el-form-item>
              <el-button :disabled="!selected.length" @click="clearSelection">清空已选</el-button>
            </el-form-item>
          </el-form>

          <el-table
            ref="tableRef"
            :data="images"
            border
            stripe
            row-key="id"
            max-height="420"
            @selection-change="onSelection"
          >
            <el-table-column type="selection" width="44" reserve-selection />
            <el-table-column label="影像 ID" width="120">
              <template #default="{ row }">{{ row.id.slice(0, 8) }}</template>
            </el-table-column>
            <el-table-column prop="class_label" label="类别" width="90" />
            <el-table-column label="尺寸" width="120">
              <template #default="{ row }">{{ row.width }}×{{ row.height }}</template>
            </el-table-column>
            <el-table-column label="标注" width="100">
              <template #default="{ row }">{{ row.annotation_status || '—' }}</template>
            </el-table-column>
            <el-table-column prop="sha256" label="SHA256" show-overflow-tooltip />
          </el-table>

          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="fetchImages"
          />
        </el-card>
      </el-col>
    </el-row>

    <div class="actions">
      <el-button @click="router.push('/screening/worklist')">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">创建检查</el-button>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.muted { color: #909399; font-size: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
