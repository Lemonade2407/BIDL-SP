import { defineStore } from 'pinia'
import type { ScreenTask } from '@/types'
import * as api from '@/api'

interface WorklistState {
  tasks: ScreenTask[]
  status: string
  page: number
  pageSize: number
  total: number
  loading: boolean
}

export const useWorklistStore = defineStore('worklist', {
  state: (): WorklistState => ({
    tasks: [],
    status: '',
    page: 1,
    pageSize: 20,
    total: 0,
    loading: false
  }),
  actions: {
    async fetch() {
      this.loading = true
      try {
        const resp = await api.getScreenTasks({ page: this.page, page_size: this.pageSize, status: this.status || undefined })
        const r = resp as { data: ScreenTask[]; meta?: { total?: number } }
        this.tasks = r.data
        this.total = r.meta?.total ?? r.data.length
      } finally {
        this.loading = false
      }
    }
  }
})