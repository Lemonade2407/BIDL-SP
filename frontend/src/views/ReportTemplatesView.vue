<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { ReportTemplate } from '@/types'
import * as api from '@/api'

const templates = ref<ReportTemplate[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const previewVisible = ref(false)
const previewHtml = ref('')
const previewing = ref(false)
const saving = ref(false)
const editingId = ref('')

const allVariables = [
  'patient_no', 'study_no', 'study_date', 'model_version', 'lesion_area_ratio',
  'review_conclusion', 'reviewer', 'signed_at', 'findings', 'impression', 'recommendation'
]
const disclaimerHint = '必须包含 {{ disclaimer }} 占位符'

const defaultBody = `<h1>乳腺影像辅助筛查报告</h1>
<p>患者编号：{{ patient_no }}</p><p>检查编号：{{ study_no }} / {{ study_date }}</p>
<p>模型版本：{{ model_version }}；面积占比：{{ lesion_area_ratio }}</p>
<h2>影像所见</h2><p>{{ findings }}</p><h2>复核意见</h2><p>{{ impression }}</p>
<h2>建议</h2><p>{{ recommendation }}</p><p>复核结论：{{ review_conclusion }}</p>
<p>{{ disclaimer }}</p>`

const form = reactive({
  name: '',
  body: defaultBody,
  variables: [] as string[]
})

async function fetch() {
  loading.value = true
  try {
    const resp = await api.getReportTemplates() as { data: ReportTemplate[] }
    templates.value = resp.data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  form.name = ''
  form.body = defaultBody
  form.variables = []
  dialogVisible.value = true
}

function openEdit(t: ReportTemplate) {
  editingId.value = t.id
  form.name = t.name
  form.body = t.body
  form.variables = [...t.variables]
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (!/{{\s*disclaimer\s*}}/.test(form.body)) {
    ElMessage.error('模板必须包含 {{ disclaimer }} 占位符')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await api.patchReportTemplate(editingId.value, {
        name: form.name,
        body: form.body,
        variables: form.variables
      })
      ElMessage.success('模板已更新（不影响已签发报告）')
    } else {
      await api.createReportTemplate({
        name: form.name,
        body: form.body,
        variables: form.variables,
        active: true
      })
      ElMessage.success('模板已创建')
    }
    dialogVisible.value = false
    await fetch()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function preview() {
  if (!/{{\s*disclaimer\s*}}/.test(form.body)) {
    ElMessage.error('模板必须包含 {{ disclaimer }} 占位符')
    return
  }
  previewing.value = true
  try {
    const resp = await api.previewReportTemplate({
      body: form.body,
      variables: form.variables
    }) as { data: { html: string } }
    previewHtml.value = resp.data.html
    previewVisible.value = true
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '预览失败')
  } finally {
    previewing.value = false
  }
}

async function toggleActive(t: ReportTemplate) {
  try {
    await api.patchReportTemplate(t.id, { active: t.active })
    ElMessage.success(t.active ? '模板已启用' : '模板已停用')
  } catch {
    t.active = !t.active
  }
}

onMounted(fetch)
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">报告模板</h3>
      <el-button type="primary" @click="openCreate">新建模板</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="templates" v-loading="loading" border stripe>
        <el-table-column prop="name" label="模板名称" width="200" />
        <el-table-column label="变量">
          <template #default="{ row }">
            <el-tag v-for="v in row.variables" :key="v" size="small" style="margin: 2px">{{ v }}</el-tag>
            <span v-if="!row.variables.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch v-model="row.active" @change="toggleActive(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="190" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑模板' : '新建模板'" width="760px">
      <el-form label-width="96px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 标准筛查报告" />
        </el-form-item>
        <el-form-item label="使用变量">
          <el-select v-model="form.variables" multiple clearable style="width: 100%" placeholder="免责声明由系统固定渲染">
            <el-option v-for="v in allVariables" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板正文">
          <el-input v-model="form.body" type="textarea" :rows="14" />
        </el-form-item>
      </el-form>
      <div class="muted" style="font-size: 12px">
        仅支持 h1–h3 / p / br / strong / em / ul / ol / li 标签与简单变量占位符，{{ disclaimerHint }}
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button :loading="previewing" @click="preview">样例预览</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="模板预览（样例数据）" width="760px">
      <div class="preview-body" v-html="previewHtml"></div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; }
.muted { color: #909399; font-size: 12px; }
.preview-body {
  max-height: 520px;
  overflow: auto;
  padding: 18px 22px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  color: #303133;
  line-height: 1.8;
}
.preview-body :deep(h1) { font-size: 20px; }
.preview-body :deep(h2) { font-size: 16px; margin-top: 14px; }
.preview-body :deep(p) { margin: 6px 0; }
</style>
