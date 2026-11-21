<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '@/stores/notification'

const router = useRouter()
const store = useNotificationStore()
const unreadOnly = ref(false)
const page = ref(1)
const pageSize = 20

async function load() {
  await store.fetchList({ page: page.value, page_size: pageSize, unread_only: unreadOnly.value })
}

function onFilter() {
  page.value = 1
  load()
}

function open(n: { link?: string | null }) {
  if (n.link) {
    router.push(n.link)
  }
}

onMounted(() => {
  load()
  store.fetchUnread()
})
</script>

<template>
  <div>
    <div class="head">
      <h3 class="page-title">通知中心</h3>
      <div>
        <el-switch v-model="unreadOnly" active-text="只看未读" @change="onFilter" />
        <el-button style="margin-left: 12px" @click="store.markAllRead()">全部已读</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-empty v-if="!store.items.length && !store.loading" description="暂无通知" />
      <div v-else v-loading="store.loading" class="list">
        <div
          v-for="n in store.items"
          :key="n.id"
          class="item"
          :class="{ unread: !n.read_at }"
          @click="store.markRead(n.id); open(n)"
        >
          <span class="dot" />
          <div class="body">
            <div class="line1">
              <span class="title">{{ n.title }}</span>
              <el-tag v-if="!n.read_at" type="danger" size="small" effect="plain">未读</el-tag>
            </div>
            <div class="desc">{{ n.body }}</div>
            <div class="meta">{{ n.type }} · {{ n.created_at }}</div>
          </div>
        </div>
      </div>
      <el-pagination
        v-if="store.total > pageSize"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="store.total"
        layout="total, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @current-change="load"
      />
    </el-card>
  </div>
</template>

<style scoped>
.page-title { margin: 0 0 16px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.head h3 { margin: 0; }
.list { display: flex; flex-direction: column; gap: 10px; }
.item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  border: 1px solid #e6e9ef;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.item:hover { border-color: #c0d3cf; background: #f7fbfa; }
.item.unread { border-color: #cfe8e2; background: #f2fbf9; }
.dot { flex: 0 0 8px; width: 8px; height: 8px; border-radius: 50%; background: #d0d7e0; margin-top: 6px; }
.item.unread .dot { background: #10b981; }
.body { min-width: 0; flex: 1; }
.line1 { display: flex; align-items: center; gap: 8px; }
.title { font-size: 14px; font-weight: 650; color: #1f2937; }
.desc { margin-top: 4px; color: #4b5563; font-size: 13px; }
.meta { margin-top: 6px; color: #9ca3af; font-size: 12px; }
</style>