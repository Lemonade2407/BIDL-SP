import { defineStore } from 'pinia'
import type { Notification } from '@/types'
import * as api from '@/api'

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    unread: 0,
    items: [] as Notification[],
    total: 0,
    loading: false
  }),
  actions: {
    async fetchUnread() {
      try {
        const resp = (await api.getUnreadCount()) as { data: number | { count: number } }
        const d = resp.data
        this.unread = typeof d === 'number' ? d : d?.count ?? 0
      } catch {
        this.unread = 0
      }
    },
    async fetchList(params: { page?: number; page_size?: number; unread_only?: boolean } = {}) {
      this.loading = true
      try {
        const resp = (await api.getNotifications(params)) as { data: Notification[]; meta?: { total?: number } }
        this.items = resp.data ?? []
        this.total = resp.meta?.total ?? this.items.length
      } catch {
        this.items = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },
    async markRead(id: string) {
      try {
        await api.markNotificationRead(id)
      } catch {
        /* 后端未就绪时静默 */
      }
      const it = this.items.find((n) => n.id === id)
      if (it && !it.read_at) {
        it.read_at = new Date().toISOString()
        this.unread = Math.max(0, this.unread - 1)
      }
    },
    async markAllRead() {
      try {
        await api.markAllNotificationsRead()
      } catch {
        /* 后端未就绪时静默 */
      }
      this.items.forEach((n) => {
        if (!n.read_at) n.read_at = new Date().toISOString()
      })
      this.unread = 0
    }
  }
})