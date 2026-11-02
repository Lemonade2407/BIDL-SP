<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ReportContent } from '@/types'

const props = defineProps<{ content: ReportContent; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update:content', v: ReportContent): void }>()

const local = ref<ReportContent>({ ...props.content })

watch(
  () => props.content,
  (v) => { local.value = { ...v } },
  { deep: true }
)

function emitChange() {
  emit('update:content', { ...local.value })
}
</script>

<template>
  <div class="report-editor">
    <el-form label-position="top" :disabled="readonly">
      <el-form-item label="超声所见（Findings）">
        <el-input v-model="local.findings" type="textarea" :rows="4" placeholder="描述病灶位置、大小、形态、边界、回声与血流情况…" @input="emitChange" />
      </el-form-item>
      <el-form-item label="超声印象（Impression）">
        <el-input v-model="local.impression" type="textarea" :rows="2" placeholder="如：BI-RADS 4a，建议穿刺活检" @input="emitChange" />
      </el-form-item>
      <el-form-item label="建议（Recommendation）">
        <el-input v-model="local.recommendation" type="textarea" :rows="2" placeholder="随访或进一步检查建议…" @input="emitChange" />
      </el-form-item>
    </el-form>
  </div>
</template>