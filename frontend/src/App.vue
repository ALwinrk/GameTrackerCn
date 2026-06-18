<template>
  <div class="app-shell" :class="{ dark: store.isDark }">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <span class="app-logo">🇨🇳</span>
        <h1 class="app-title">国内游戏每日新游排查</h1>
        <span class="app-version">v1.0</span>
      </div>
      <div class="header-right">
        <el-switch
          v-model="store.isDark"
          inline-prompt
          :active-icon="Moon"
          :inactive-icon="Sunny"
          @change="store.toggleDark"
          size="small"
        />
        <span class="status-dot" :class="backendReady ? 'online' : 'offline'"></span>
        <span class="status-text">{{ backendReady ? '已连接' : '连接中...' }}</span>
      </div>
    </header>

    <!-- Notice Bar -->
    <div v-if="store.config.notice_enabled && store.config.notice_text" class="notice-bar">
      <span v-html="sanitizedNotice"></span>
    </div>

    <!-- Main Content -->
    <main class="app-main">
      <el-tabs v-model="activeTab" type="border-card" class="main-tabs">
        <el-tab-pane label="📅 每日新游" name="daily">
          <DailyPanel />
        </el-tab-pane>
        <el-tab-pane label="⚙️ 设置" name="settings">
          <SettingsPanel />
        </el-tab-pane>
      </el-tabs>
    </main>

    <!-- Footer -->
    <footer class="app-footer">
      <span>好游快爆 · TapTap 新游监控</span>
      <span class="footer-divider">|</span>
      <span>数据定时更新</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Moon, Sunny } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { useAppStore } from './stores/app'
import DailyPanel from './components/DailyPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'

const store = useAppStore()
const activeTab = ref('daily')
const backendReady = ref(false)

// XSS 防护: DOMPurify 白名单 (仅允许安全标签)
const sanitizedNotice = computed(() => {
  const raw = store.config.notice_text || ''
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['br', 'b', 'i', 'a', 'strong', 'em', 'u', 'p', 'span'],
    ALLOWED_ATTR: ['href', 'target', 'rel'],
  })
})

onMounted(async () => {
  // 后台就绪检查 (指数退避)
  let delay = 500
  for (let i = 0; i < 15; i++) {
    try {
      const resp = await fetch(`${store.apiBase}/api/health`)
      if (resp.ok) {
        backendReady.value = true
        break
      }
    } catch {}
    await new Promise(r => setTimeout(r, delay))
    delay = Math.min(delay * 1.5, 5000)
  }

  await store.fetchConfig()
})
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-page);
  color: var(--text-primary);
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
  backdrop-filter: blur(16px);
}
.header-left { display: flex; align-items: center; gap: 10px; }
.app-logo { font-size: 24px; }
.app-title { font-size: 18px; font-weight: 700; margin: 0; letter-spacing: 1px; }
.app-version { font-size: 11px; color: var(--text-muted); background: var(--bg-tag); padding: 2px 8px; border-radius: 10px; }
.header-right { display: flex; align-items: center; gap: 10px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: #67c23a; box-shadow: 0 0 6px #67c23a; }
.status-dot.offline { background: #f56c6c; animation: pulse 1.5s infinite; }
.status-text { font-size: 13px; color: var(--text-secondary); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.notice-bar {
  padding: 8px 24px;
  background: var(--color-warning-bg, #fdf6ec);
  border-bottom: 1px solid var(--color-warning-border, #faecd8);
  font-size: 13px; color: var(--color-warning-text, #e6a23c); text-align: center;
}

.app-main {
  flex: 1;
  padding: 8px 8px;
  width: 100%;
}
.main-tabs { border-radius: 12px; overflow: hidden; }

.app-footer {
  text-align: center; padding: 12px; font-size: 12px;
  color: var(--text-muted); border-top: 1px solid var(--border-color);
}
.footer-divider { margin: 0 8px; opacity: 0.4; }
</style>
