import { defineStore } from 'pinia'
import type { LoginPayload, Role, User } from '@/types'
import * as api from '@/api'

function readToken(): string {
  const value = sessionStorage.getItem('bidl_token')
  return value && value !== 'undefined' && value !== 'null' ? value : ''
}

function readUser(): User | null {
  const raw = sessionStorage.getItem('bidl_user')
  if (!raw || raw === 'undefined' || raw === 'null') return null
  try {
    return JSON.parse(raw) as User
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: readToken(),
    user: readUser()
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
      sessionStorage.setItem('bidl_token', data.access_token)
      sessionStorage.setItem('bidl_user', JSON.stringify(data.user))
    },
    async logout() {
      try {
        await api.logout()
      } finally {
        this.token = ''
        this.user = null
        sessionStorage.removeItem('bidl_token')
        sessionStorage.removeItem('bidl_user')
      }
    }
  }
})