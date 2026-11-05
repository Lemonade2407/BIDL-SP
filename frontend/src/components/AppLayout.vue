<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

interface MenuItem { path: string; label: string; roles?: string[] }

const menus: MenuItem[] = [
  { path: '/dashboard', label: '总览' },
  { path: '/data/import', label: '数据接入', roles: ['admin', 'data_engineer'] },
  { path: '/data/images', label: '影像检索' },
  { path: '/data/datasets', label: '数据集版本' },
  { path: '/annotation/tasks', label: '标注任务', roles: ['annotator', 'admin', 'reviewer'] },
  { path: '/screening/worklist', label: '筛查工作台', roles: ['screener', 'admin', 'reviewer'] },
  { path: '/models', label: '模型与指标' },
  { path: '/stats', label: '统计看板' },
  { path: '/admin/users', label: '用户管理', roles: ['admin'] },
  { path: '/admin/audit', label: '审计日志', roles: ['admin'] }
]

const visible = computed(() => menus.filter((m) => !m.roles || auth.hasAny(...(m.roles as any))))

const active = computed(() => route.path)

async function onLogout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  auth.logout()
  router.push('/login')
}

const roleText: Record<string, string> = {
  admin: '管理员', data_engineer: '数据工程师', annotator: '标注员', screener: '筛查医生', reviewer: '审核医师'
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <div class="logo">BIDL-SP</div>
        <div class="sub">乳腺影像数据湖与辅助筛查平台</div>
      </div>
      <el-menu :default-active="active" router class="menu" background-color="#0f1115" text-color="#c0c4cc" active-text-color="#409eff">
        <el-menu-item v-for="m in visible" :key="m.path" :index="m.path">{{ m.label }}</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="disclaimer">仅供科研/教学使用，不作为临床诊断依据</div>
        <el-dropdown>
          <span class="user">
            <el-avatar :size="26" style="background: #409eff">{{ auth.user?.display_name?.charAt(0) || '?' }}</el-avatar>
            <span class="name">{{ auth.user?.display_name }}</span>
            <span class="role">{{ (auth.roles || []).map((r) => roleText[r] ?? r).join(' / ') }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="onLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
      <el-footer class="footer disclaimer">BIDL-SP · 本平台仅供科研/教学使用，不作为临床诊断依据</el-footer>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { height: 100vh; }
.aside { background: #0f1115; display: flex; flex-direction: column; }
.brand { padding: 16px; color: #fff; border-bottom: 1px solid #1f232b; }
.brand .logo { font-size: 18px; font-weight: 700; letter-spacing: 1px; }
.brand .sub { font-size: 11px; color: #8a8f99; margin-top: 4px; line-height: 1.4; }
.menu { border-right: none; flex: 1; }
.header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #ebeef5; background: #fff; }
.user { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.user .name { font-size: 14px; color: #303133; }
.user .role { font-size: 12px; color: #909399; }
.main { background: #f5f7fa; }
.footer { text-align: center; padding: 8px; }
</style>