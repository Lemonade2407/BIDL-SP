import { defineStore } from 'pinia'
import type { LoginPayload, Role, User } from '@/types'
import * as api from '@/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('bidl_token') || '',
    user: JSON.parse(localStorage.getItem('bidl_user') || 'null') as User | null
  }),
  getters: {
    isAuthed: (s) => !!s.token,
    roles: (s): Role[] => s.user?.roles ?? []
  },
  actions: {
    hasRole(role: Role) {
      return this.roles.includes(role)
    },
    hasAny(...roles: Role[]) {
      return roles.some((r) => this.roles.includes(r))
    },
    async login(payload: LoginPayload) {
      const resp = await api.login(payload)
      const data = (resp as { data: { access_token: string; user: User } }).data
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem('bidl_token', data.access_token)
      localStorage.setItem('bidl_user', JSON.stringify(data.user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('bidl_token')
      localStorage.removeItem('bidl_user')
    }
  }
})