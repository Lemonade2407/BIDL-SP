<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const MAP: Record<string, { type: 'success' | 'info' | 'warning' | 'danger' | 'primary'; label: string }> = {
  active: { type: 'success', label: '启用' },
  disabled: { type: 'info', label: '停用' },
  pending: { type: 'info', label: '待处理' },
  in_progress: { type: 'primary', label: '进行中' },
  submitted: { type: 'warning', label: '已提交' },
  approved: { type: 'success', label: '已通过' },
  rejected: { type: 'danger', label: '已驳回' },
  draft: { type: 'info', label: '草稿' },
  pending_review: { type: 'warning', label: '待审核' },
  signed: { type: 'success', label: '已签发' },
  frozen: { type: 'primary', label: '已冻结' },
  archived: { type: 'info', label: '已归档' },
  candidate: { type: 'info', label: '候选' },
  completed: { type: 'success', label: '已完成' },
  failed: { type: 'danger', label: '失败' },
  validating: { type: 'warning', label: '校验中' },
  importing: { type: 'warning', label: '导入中' },
  queued: { type: 'info', label: '排队中' },
  running: { type: 'warning', label: '运行中' },
  succeeded: { type: 'success', label: '成功' },
  done: { type: 'success', label: '已完成' }
}

const info = computed(() => MAP[props.status] ?? { type: 'info' as const, label: props.status })
</script>

<template>
  <el-tag :type="info.type" size="small">{{ info.label }}</el-tag>
</template>