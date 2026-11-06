<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, CircleCheck, Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const form = reactive({
  username: (route.query.username as string) || 'admin',
  password: 'DemoPassword!123'
})
const loading = ref(false)

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
  <div class="login-page">
    <section class="login-hero">
      <div class="hero-top">
        <div class="hero-mark">B</div>
        <div>
          <div class="hero-brand">BIDL-SP</div>
          <div class="hero-sub">乳腺影像数据湖与辅助筛查平台</div>
        </div>
      </div>

      <div class="hero-copy">
        <span class="hero-kicker">RESEARCH WORKSPACE</span>
        <h2>让每一份影像<br />都进入可追溯的科研闭环</h2>
        <p>数据接入 · 掩膜标注 · 模型评估 · 辅助筛查 · 报告审计</p>
      </div>

      <ul class="hero-points">
        <li><el-icon><CircleCheck /></el-icon><span>BUSI 数据湖与冻结数据集版本</span></li>
        <li><el-icon><CircleCheck /></el-icon><span>真实 TransUNet 推理与指标回归</span></li>
        <li><el-icon><CircleCheck /></el-icon><span>RBAC 权限、审计留痕与报告签发</span></li>
      </ul>

      <div class="hero-foot">仅供科研/教学使用，不作为临床诊断依据</div>
    </section>

    <section class="login-panel">
      <div class="panel-head">
        <span class="panel-eyebrow">BIDL-SP</span>
        <h3>登录工作台</h3>
        <p>使用院内账号进入平台</p>
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
        <el-button type="primary" size="large" class="submit" :loading="loading" native-type="submit">
          <span>进入平台</span>
          <el-icon class="submit-icon"><ArrowRight /></el-icon>
        </el-button>
      </el-form>

      <div class="demo">
        <p class="tip">演示管理员账号：<code>admin</code> / <code>DemoPassword!123</code></p>
      </div>

      <div class="switch">
        <span>还没有账号？</span>
        <el-link type="primary" :underline="false" @click="router.push('/register')">注册</el-link>
      </div>

      <div class="panel-foot">科研演示环境 · 登录后请遵守数据使用规范</div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  grid-template-columns: minmax(0, 1.15fr) minmax(400px, 0.85fr);
  overflow: hidden;
  background:
    radial-gradient(820px 560px at 8% 12%, rgba(45, 212, 191, 0.22), transparent 62%),
    radial-gradient(720px 520px at 92% 88%, rgba(13, 148, 136, 0.2), transparent 60%),
    linear-gradient(135deg, #062322 0%, #083b38 52%, #0b4a45 100%);
}

.login-page::after {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 42px 42px;
  content: '';
  opacity: 0.45;
  pointer-events: none;
}

.login-hero {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px clamp(40px, 7vw, 104px);
  color: #eafffb;
}

.hero-top { display: flex; align-items: center; gap: 14px; }

.hero-mark {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #5eead4, #2dd4bf);
  box-shadow: 0 16px 34px -16px rgba(45, 212, 191, 0.9);
  color: #042f2e;
  font-size: 22px;
  font-weight: 800;
}

.hero-brand { font-size: 20px; font-weight: 750; letter-spacing: 2px; }
.hero-sub { margin-top: 3px; color: #9ed3cc; font-size: 11px; letter-spacing: 0.4px; }

.hero-copy { margin-top: 74px; }
.hero-kicker { color: #5eead4; font-size: 10px; font-weight: 700; letter-spacing: 2.6px; }
.hero-copy h2 {
  margin: 14px 0 16px;
  color: #ffffff;
  font-size: clamp(30px, 3.4vw, 44px);
  font-weight: 750;
  letter-spacing: 0.5px;
  line-height: 1.28;
}
.hero-copy p { margin: 0; color: #9ed3cc; font-size: 13px; letter-spacing: 0.3px; }

.hero-points {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 42px 0 0;
  padding: 0;
  list-style: none;
}
.hero-points li { display: flex; align-items: center; gap: 10px; color: #c8e8e3; font-size: 12.5px; }
.hero-points .el-icon { color: #5eead4; font-size: 15px; }

.hero-foot { margin-top: auto; padding-top: 60px; color: #6f9d98; font-size: 11px; }

.login-panel {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin: 26px;
  padding: 40px clamp(28px, 4vw, 54px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 40px 90px -46px rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(18px);
}

.panel-head { margin-bottom: 26px; }
.panel-eyebrow { color: var(--brand); font-size: 10px; font-weight: 750; letter-spacing: 2px; }
.panel-head h3 { margin: 8px 0 6px; color: var(--ink); font-size: 26px; font-weight: 750; letter-spacing: 0.3px; }
.panel-head p { margin: 0; color: var(--muted); font-size: 12.5px; }

.submit {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
}
.submit-icon { font-size: 15px; }

.demo {
  margin-top: 18px;
  padding: 10px 12px;
  border: 1px dashed #cfe3df;
  border-radius: 10px;
  background: rgba(45, 212, 191, 0.06);
  text-align: center;
}
.demo .tip { margin: 0; color: var(--muted); font-size: 12px; }
.demo code {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(13, 148, 136, 0.12);
  color: #0f766e;
  font-size: 12px;
}

.switch {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px dashed #dbe7e5;
  color: var(--muted);
  font-size: 12.5px;
}

.panel-foot { margin-top: 26px; color: #8aa5a0; font-size: 10.5px; text-align: center; }

@media (max-width: 900px) {
  .login-page { grid-template-columns: 1fr; }
  .login-hero { display: none; }
  .login-panel { margin: 18px; }
}

@media (min-width: 901px) and (max-width: 1180px) {
  .login-hero { padding: 52px 44px; }
  .hero-copy h2 { font-size: 32px; }
}
</style>
