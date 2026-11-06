<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ArrowDown, Cpu, DataAnalysis, DataBoard, Document, EditPen, Files, Picture,
  SwitchButton, UploadFilled, User, View
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

interface MenuItem { path: string; label: string; icon: Component; roles?: string[] }

const menus: MenuItem[] = [
  { path: '/dashboard', label: '总览', icon: DataBoard },
  { path: '/data/import', label: '数据接入', icon: UploadFilled, roles: ['admin', 'data_engineer'] },
  { path: '/data/images', label: '影像检索', icon: Picture },
  { path: '/data/datasets', label: '数据集版本', icon: Files },
  { path: '/annotation/tasks', label: '标注任务', icon: EditPen, roles: ['annotator', 'admin', 'reviewer'] },
  { path: '/screening/worklist', label: '筛查工作台', icon: View, roles: ['screener', 'admin', 'reviewer'] },
  { path: '/models', label: '模型与指标', icon: Cpu },
  { path: '/stats', label: '统计看板', icon: DataAnalysis },
  { path: '/admin/users', label: '用户管理', icon: User, roles: ['admin'] },
  { path: '/admin/audit', label: '审计日志', icon: Document, roles: ['admin'] }
]

const visible = computed(() => menus.filter((m) => !m.roles || auth.hasAny(...(m.roles as any))))
const active = computed(() => route.path)
const currentLabel = computed(() => {
  const hit = menus.find((m) => route.path === m.path || route.path.startsWith(m.path + '/'))
  return hit?.label ?? '总览'
})

async function onLogout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  await auth.logout()
  router.push('/login')
}

const roleText: Record<string, string> = {
  admin: '管理员', data_engineer: '数据工程师', annotator: '标注员', screener: '筛查医生', reviewer: '审核医师'
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="244px" class="aside">
      <div class="brand">
        <div class="brand-mark">B</div>
        <div class="brand-copy">
          <div class="logo">BIDL-SP</div>
          <div class="sub">乳腺影像数据湖与辅助筛查</div>
        </div>
      </div>
      <div class="menu-caption">工作台</div>
      <el-menu :default-active="active" router class="menu">
        <el-menu-item v-for="m in visible" :key="m.path" :index="m.path">
          <el-icon class="menu-icon"><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>
      </el-menu>
      <div class="aside-foot">
        <span class="status-dot" />
        <span>科研演示环境</span>
      </div>
    </el-aside>

    <el-container class="workspace">
      <el-header class="header">
        <div class="head-left">
          <span class="eyebrow">BIDL-SP / 工作台</span>
          <span class="head-title">{{ currentLabel }}</span>
        </div>
        <div class="head-right">
          <div class="head-badge"><span class="status-dot" />系统在线</div>
          <el-dropdown trigger="click">
            <span class="user">
              <el-avatar :size="30" class="avatar">{{ auth.user?.display_name?.charAt(0) || '?' }}</el-avatar>
              <span class="user-copy">
                <span class="name">{{ auth.user?.display_name }}</span>
                <span class="role">{{ (auth.roles || []).map((r) => roleText[r] ?? r).join(' / ') }}</span>
              </span>
              <el-icon class="caret"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  <el-icon><User /></el-icon>{{ auth.user?.username }}
                </el-dropdown-item>
                <el-dropdown-item divided @click="onLogout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>

      <el-footer class="footer">
        BIDL-SP · 本平台仅供科研/教学使用，不作为临床诊断依据
      </el-footer>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(420px 260px at 0% 0%, rgba(45, 212, 191, 0.18), transparent 62%),
    linear-gradient(180deg, var(--sidebar) 0%, var(--sidebar-2) 100%);
  box-shadow: 18px 0 44px -34px rgba(8, 47, 46, 0.8);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--accent), #0d9488);
  box-shadow: 0 10px 24px -12px rgba(45, 212, 191, 0.8);
  color: #042f2e;
  font-size: 19px;
  font-weight: 800;
}

.brand-copy { min-width: 0; }
.brand .logo { color: #f8fffe; font-size: 17px; font-weight: 750; letter-spacing: 1.2px; }
.brand .sub { margin-top: 4px; color: #8fb9b4; font-size: 10.5px; line-height: 1.35; }

.menu-caption {
  padding: 18px 22px 8px;
  color: #6f9d98;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 1.4px;
  text-transform: uppercase;
}

.menu {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px;
  background: transparent;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #a9c9c4;
  --el-menu-active-color: #ffffff;
  --el-menu-hover-bg-color: rgba(45, 212, 191, 0.1);
  --el-menu-item-height: 44px;
}

.menu :deep(.el-menu-item) {
  position: relative;
  margin: 3px 0;
  border-radius: 10px;
  font-size: 13.5px;
  font-weight: 520;
}

.menu :deep(.el-menu-item:hover) {
  color: #eafffb;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(45, 212, 191, 0.22), rgba(45, 212, 191, 0.06));
  box-shadow: inset 0 0 0 1px rgba(45, 212, 191, 0.2);
  color: #ffffff;
  font-weight: 650;
}

.menu :deep(.el-menu-item.is-active)::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 3px;
  border-radius: 3px;
  background: var(--accent);
  content: '';
}

.menu-icon { margin-right: 10px; font-size: 17px; }

.aside-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 16px 16px;
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  color: #8fb9b4;
  font-size: 11px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.12);
}

.workspace { min-width: 0; }

.header {
  display: flex;
  height: 68px;
  align-items: center;
  justify-content: space-between;
  padding: 0 26px;
  border-bottom: 1px solid rgba(219, 231, 229, 0.8);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px);
}

.head-left { display: flex; flex-direction: column; gap: 3px; }
.eyebrow { color: #8aa5a0; font-size: 10px; font-weight: 650; letter-spacing: 1.3px; text-transform: uppercase; }
.head-title { color: var(--ink); font-size: 18px; font-weight: 700; letter-spacing: 0.2px; }

.head-right { display: flex; align-items: center; gap: 18px; }

.head-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  border: 1px solid #d9ebe7;
  border-radius: 999px;
  background: #f4fbf9;
  color: #4b6f6a;
  font-size: 11px;
  font-weight: 550;
}

.user { display: flex; align-items: center; gap: 9px; cursor: pointer; }
.avatar { background: linear-gradient(135deg, var(--brand), #0d9488); font-weight: 700; }
.user-copy { display: flex; flex-direction: column; line-height: 1.2; }
.user .name { color: var(--ink); font-size: 13px; font-weight: 650; }
.user .role { color: var(--muted); font-size: 10.5px; }
.caret { color: #94a3b8; font-size: 12px; }

.main {
  padding: 26px;
  overflow: auto;
  background:
    radial-gradient(700px 320px at 100% 0%, rgba(45, 212, 191, 0.06), transparent 65%),
    transparent;
}

.footer {
  padding: 10px 20px;
  color: #8aa5a0;
  font-size: 11px;
  text-align: center;
}

@media (max-width: 980px) {
  .aside { width: 76px !important; }
  .brand { justify-content: center; padding: 18px 10px; }
  .brand-copy, .menu-caption, .aside-foot span:last-child { display: none; }
  .menu { padding: 6px; }
  .menu :deep(.el-menu-item) { justify-content: center; padding: 0 !important; }
  .menu :deep(.el-menu-item span) { display: none; }
  .menu-icon { margin-right: 0; }
  .head-badge { display: none; }
}

@media (max-width: 640px) {
  .header { padding: 0 16px; }
  .head-title { font-size: 16px; }
  .user-copy { display: none; }
  .main { padding: 16px; }
}
</style>
