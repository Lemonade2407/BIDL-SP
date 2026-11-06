import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { Role } from '@/types'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'data/import', name: 'data-import', component: () => import('@/views/DataImportView.vue'), meta: { roles: ['admin', 'data_engineer'] } },
      { path: 'data/images', name: 'data-images', component: () => import('@/views/DataImagesView.vue') },
      { path: 'data/datasets', name: 'data-datasets', component: () => import('@/views/DataDatasetsView.vue') },
      { path: 'annotation/tasks', name: 'annotation-tasks', component: () => import('@/views/AnnotationTasksView.vue'), meta: { roles: ['annotator', 'admin', 'reviewer'] } },
      { path: 'annotation/editor/:imageId', name: 'annotation-editor', component: () => import('@/views/AnnotationEditorView.vue'), meta: { roles: ['annotator', 'admin'] } },
      { path: 'screening/worklist', name: 'screening-worklist', component: () => import('@/views/ScreeningWorklistView.vue'), meta: { roles: ['screener', 'admin', 'reviewer'] } },
      { path: 'screening/studies/:id', name: 'screening-study', component: () => import('@/views/ScreeningStudyView.vue'), meta: { roles: ['screener', 'reviewer', 'admin'] } },
      { path: 'reports/:id', name: 'report', component: () => import('@/views/ReportView.vue'), meta: { roles: ['screener', 'reviewer', 'admin'] } },
      { path: 'models', name: 'models', component: () => import('@/views/ModelsView.vue') },
      { path: 'stats', name: 'stats', component: () => import('@/views/StatsView.vue') },
      { path: 'admin/users', name: 'admin-users', component: () => import('@/views/AdminUsersView.vue'), meta: { roles: ['admin'] } },
      { path: 'admin/audit', name: 'admin-audit', component: () => import('@/views/AdminAuditView.vue'), meta: { roles: ['admin'] } }
    ]
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.isAuthed) return { path: '/login', query: { redirect: to.fullPath } }
  const roles = to.meta.roles as Role[] | undefined
  if (roles && roles.length && !auth.hasAny(...roles)) {
    return { path: '/dashboard' }
  }
  return true
})

export default router