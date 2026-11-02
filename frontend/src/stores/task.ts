import { defineStore } from 'pinia'

interface PollHandle {
  timer: number
  id: string
}

export const useTaskStore = defineStore('task', {
  state: () => ({
    polling: {} as Record<string, PollHandle>
  }),
  actions: {
    start(id: string, fn: () => Promise<boolean>, interval = 1000, timeout = 60000) {
      this.stop(id)
      const startAt = Date.now()
      const timer = window.setInterval(async () => {
        if (Date.now() - startAt > timeout) {
          this.stop(id)
          return
        }
        const done = await fn()
        if (done) this.stop(id)
      }, interval)
      this.polling[id] = { timer, id }
    },
    stop(id: string) {
      const h = this.polling[id]
      if (h) {
        window.clearInterval(h.timer)
        delete this.polling[id]
      }
    },
    stopAll() {
      Object.keys(this.polling).forEach((k) => this.stop(k))
    }
  }
})