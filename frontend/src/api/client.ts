import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiError } from '@/types'

export const http: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = sessionStorage.getItem('bidl_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  config.headers['X-Request-Id'] = `req_${Date.now().toString(36)}`
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error.response?.status
    const data = error.response?.data as ApiError | undefined
    const msg = data?.message || error.message || '网络错误'
    if (status === 401) {
      sessionStorage.removeItem('bidl_token')
      sessionStorage.removeItem('bidl_user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    } else if (status === 403) {
      ElMessage.error('无权限执行此操作（403）')
    } else if (status === 409) {
      ElMessage.warning(msg)
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export function unwrap<T>(resp: { data: { data: T } }): T {
  return resp.data.data
}