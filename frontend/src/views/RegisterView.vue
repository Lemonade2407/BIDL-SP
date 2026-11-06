<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Lock, Postcard, User } from '@element-plus/icons-vue'
import * as api from '@/api'

const router = useRouter()
const form = reactive({ username: '', display_name: '', password: '', confirm: '' })
const loading = ref(false)

async function onSubmit() {
  if (form.password !== form.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    const resp = await api.register({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password
    }) as { data: { message?: string } }
    ElMessage.success(resp.data?.message || '注册成功，请联系管理员启用账号')
    router.push({ path: '/login', query: { username: form.username.trim() } })
  } catch {
    // 错误提示由拦截器处理
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="register-page">
    <section class="register-panel">
      <div class="brand">
        <div class="brand-mark">B</div>
        <div>
          <div class="brand-name">BIDL-SP</div>
          <div class="brand-sub">乳腺影像数据湖与辅助筛查平台</div>
        </div>
      </div>

      <div class="head">
        <span class="eyebrow">ACCOUNT REQUEST</span>
        <h3>注册科研账号</h3>
        <p>提交后需管理员启用账号并分配角色，方可登录</p>
      </div>

      <el-form :model="form" label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="3–64 字符，登录使用" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" placeholder="姓名或工号" size="large">
            <template #prefix><el-icon><Postcard /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="8–64 字符" size="large" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="form.confirm" type="password" placeholder="再次输入密码" size="large" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="submit" :loading="loading" native-type="submit">
          <span>提交注册</span>
          <el-icon class="submit-icon"><ArrowRight /></el-icon>
        </el-button>
      </el-form>

      <div class="back">
        <el-link type="primary" :underline="false" @click="router.push('/login')">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回登录</span>
        </el-link>
      </div>

      <div class="foot">仅供科研/教学使用，不作为临床诊断依据</div>
    </section>
  </div>
</template>

<style scoped>
.register-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(720px 480px at 12% 8%, rgba(45, 212, 191, 0.22), transparent 62%),
    radial-gradient(640px 460px at 88% 92%, rgba(13, 148, 136, 0.2), transparent 60%),
    linear-gradient(135deg, #062322 0%, #083b38 52%, #0b4a45 100%);
}

.register-panel {
  width: min(520px, 100%);
  padding: 38px clamp(26px, 5vw, 46px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 40px 90px -46px rgba(0, 0, 0, 0.7);
}

.brand { display: flex; align-items: center; gap: 12px; }
.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, #5eead4, #2dd4bf);
  color: #042f2e;
  font-size: 19px;
  font-weight: 800;
}
.brand-name { color: var(--ink); font-size: 17px; font-weight: 750; letter-spacing: 2px; }
.brand-sub { margin-top: 2px; color: var(--muted); font-size: 10.5px; }

.head { margin: 26px 0 18px; }
.eyebrow { color: var(--brand); font-size: 10px; font-weight: 750; letter-spacing: 2px; }
.head h3 { margin: 8px 0 6px; color: var(--ink); font-size: 24px; font-weight: 750; }
.head p { margin: 0; color: var(--muted); font-size: 12.5px; }

.submit {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 6px;
}
.submit-icon { font-size: 15px; }

.back { margin-top: 20px; text-align: center; font-size: 12.5px; }
.back .el-link { gap: 4px; }

.foot { margin-top: 22px; color: #8aa5a0; font-size: 10.5px; text-align: center; }
</style>
