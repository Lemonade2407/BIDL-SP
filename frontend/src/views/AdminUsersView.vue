<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { Role, User } from '@/types'
import * as api from '@/api'

const users = ref<User[]>([])
const roles: Role[] = ['admin', 'data_engineer', 'annotator', 'screener', 'reviewer']
const roleText: Record<string, string> = { admin: '管理员', data_engineer: '数据工程师', annotator: '标注员', screener: '筛查医生', reviewer: '审核医师' }

onMounted(async () => {
  const resp = await api.getUsers()
  users.value = (resp as { data: User[] }).data
})

async function toggleRole(u: User, role: Role) {
  const next = u.roles.includes(role) ? u.roles.filter((r) => r !== role) : [...u.roles, role]
  await api.patchUser(u.id, { roles: next })
  u.roles = next
  ElMessage.success('角色已更新')
}

async function toggleStatus(u: User) {
  const next = u.status === 'active' ? 'disabled' : 'active'
  await api.patchUser(u.id, { status: next })
  u.status = next
  ElMessage.success('状态已更新')
}
</script>

<template>
  <div>
    <h3 class="page-title">用户管理</h3>
    <el-card shadow="never">
      <el-table :data="users" border stripe>
        <el-table-column prop="username" label="用户名" width="140" />
        <el-table-column prop="display_name" label="显示名" width="120" />
        <el-table-column label="角色" min-width="260">
          <template #default="{ row }">
            <el-checkbox-group :model-value="row.roles" @change="(v: Role[]) => (row.roles = v)">
              <el-checkbox v-for="r in roles" :key="r" :value="r" @change="toggleRole(row, r)">{{ roleText[r] }}</el-checkbox>
            </el-checkbox-group>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" :type="row.status === 'active' ? 'danger' : 'success'" @click="toggleStatus(row)">
              {{ row.status === 'active' ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
</style>