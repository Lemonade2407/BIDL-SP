<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const form = reactive({ username: 'screener', password: 'demo123' })
const loading = ref(false)

const demoAccounts = [
  { u: 'admin', p: '任意', label: '管理员' },
  { u: 'data_engineer', p: '任意', label: '数据工程师' },
  { u: 'annotator', p: '任意', label: '标注员' },
  { u: 'screener', p: '任意', label: '筛查医生' },
  { u: 'reviewer', p: '任意', label: '审核医师' }
]

async function onSubmit() {
  loading.value = true
  try {
    await auth.login({ username: form.username, password: form.password })
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
  } catch {
    // 错误提示由拦截器处理
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <div class="brand">
        <h1>BIDL-SP</h1>
        <p>乳腺影像数据湖与辅助筛查平台</p>
      </div>
      <el-form :model="form" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="submit" :loading="loading" native-type="submit">登 录</el-button>
      </el-form>
      <div class="demo">
        <p class="tip">演示账号（Mock 环境密码任意）：</p>
        <el-tag v-for="d in demoAccounts" :key="d.u" class="acct" @click="form.username = d.u">{{ d.label }} · {{ d.u }}</el-tag>
      </div>
    </el-card>
    <div class="disclaimer">仅供科研/教学使用，不作为临床诊断依据</div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f1115 0%, #1d2230 100%);
}
.login-card { width: 380px; }
.brand { text-align: center; margin-bottom: 20px; }
.brand h1 { margin: 0; letter-spacing: 2px; }
.brand p { margin: 6px 0 0; color: #909399; font-size: 13px; }
.submit { width: 100%; }
.demo { margin-top: 16px; }
.demo .tip { font-size: 12px; color: #909399; margin: 0 0 6px; }
.acct { margin: 3px; cursor: pointer; }
.disclaimer { margin-top: 20px; color: rgba(255,255,255,0.5); font-size: 12px; }
</style>