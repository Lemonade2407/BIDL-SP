import { onBeforeUnmount, ref } from 'vue'

export interface PollOptions {
  interval?: number
  attempts?: number
  maxInterval?: number
}

/**
 * 统一轮询：固定间隔起步，失败或长任务时逐步退避；组件卸载自动停止。
 */
export function usePoll() {
  const polling = ref(false)
  let stopped = false

  onBeforeUnmount(() => {
    stopped = true
  })

  function stop() {
    stopped = true
    polling.value = false
  }

  async function poll<T>(
    fetcher: () => Promise<T>,
    isDone: (value: T) => boolean,
    options: PollOptions = {}
  ): Promise<{ value: T | null; done: boolean }> {
    const { interval = 1000, attempts = 60, maxInterval = 5000 } = options
    polling.value = true
    let current = interval
    try {
      for (let attempt = 0; attempt < attempts; attempt++) {
        if (stopped) return { value: null, done: false }
        try {
          const value = await fetcher()
          if (isDone(value)) return { value, done: true }
          current = Math.min(maxInterval, Math.round(current * 1.15))
        } catch {
          // 单次失败不终止轮询，继续退避重试
        }
        await new Promise((resolve) => window.setTimeout(resolve, current))
      }
      return { value: null, done: false }
    } finally {
      polling.value = false
    }
  }

  return { polling, poll, stop }
}
