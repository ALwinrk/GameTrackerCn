<template>
  <div class="settings-panel">
    <el-card shadow="never" class="settings-card">
      <template #header>
        <span class="settings-title">⚙️ 系统设置</span>
      </template>

      <el-form label-width="160px" label-position="left" size="default">
        <!-- 数据源 -->
        <el-divider content-position="left">📡 数据源</el-divider>
        <el-form-item label="好游快爆 (3839.com)">
          <el-switch v-model="form.enable_3839" @change="save" />
        </el-form-item>
        <el-form-item label="TapTap (taptap.cn)">
          <el-switch v-model="form.enable_taptap" @change="save" />
        </el-form-item>

        <!-- 更新频率 -->
        <el-divider content-position="left">🔄 更新频率</el-divider>
        <el-form-item label="定时抓取间隔(秒)">
          <el-input-number v-model="form.update_check_interval" :min="600" :max="86400" :step="300" @change="save" />
          <span class="hint">{{ formatInterval(form.update_check_interval) }}</span>
        </el-form-item>
        <el-form-item label="前端轮询间隔(秒)">
          <el-input-number v-model="form.frontend_poll_interval" :min="30" :max="3600" :step="30" @change="save" />
        </el-form-item>

        <!-- 展示限制 -->
        <el-divider content-position="left">📊 展示限制</el-divider>
        <el-form-item label="好游快爆展示条数">
          <el-input-number v-model="form.display_limit_3839" :min="10" :max="200" @change="save" />
        </el-form-item>
        <el-form-item label="TapTap 展示条数">
          <el-input-number v-model="form.display_limit_taptap" :min="10" :max="200" @change="save" />
        </el-form-item>

        <!-- 代理 -->
        <el-divider content-position="left">🌐 网络</el-divider>
        <el-form-item label="全局代理">
          <el-input v-model="form.proxy" placeholder="http://127.0.0.1:7897" @change="save" />
        </el-form-item>
        <el-form-item label="国内源代理">
          <el-input v-model="form.domestic_proxy" placeholder="留空=直连" @change="save" />
          <span class="hint">国内站点通常无需代理</span>
        </el-form-item>

        <!-- 爬虫 -->
        <el-divider content-position="left">🕷️ 爬虫</el-divider>
        <el-form-item label="请求超时(秒)">
          <el-input-number v-model="form.request_timeout" :min="3" :max="60" :step="1" @change="save" />
        </el-form-item>
        <el-form-item label="浏览器超时(秒)">
          <el-input-number v-model="form.stealth_timeout" :min="10" :max="120" :step="5" @change="save" />
        </el-form-item>
        <el-form-item label="重试次数">
          <el-input-number v-model="form.retry_times" :min="0" :max="5" @change="save" />
        </el-form-item>

        <!-- 公告 -->
        <el-divider content-position="left">📢 系统公告</el-divider>
        <el-form-item label="启用公告">
          <el-switch v-model="form.notice_enabled" @change="save" />
        </el-form-item>
        <el-form-item label="公告内容 (HTML)">
          <el-input v-model="form.notice_text" type="textarea" :rows="3" placeholder="支持 HTML..." @change="save" />
        </el-form-item>

        <!-- 操作 -->
        <el-divider />
        <el-form-item>
          <el-button type="primary" @click="testProxy">🔍 测试代理</el-button>
          <el-button @click="loadForm">🔄 重新加载</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const form = reactive<Record<string, any>>({
  enable_3839: true, enable_taptap: true,
  update_check_interval: 3600, frontend_poll_interval: 300,
  display_limit_3839: 60, display_limit_taptap: 60,
  proxy: '', domestic_proxy: '',
  request_timeout: 10, stealth_timeout: 30,
  retry_times: 2,
  notice_enabled: false, notice_text: '',
})

function formatInterval(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}分钟`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}小时${rm}分钟` : `${h}小时`
}

async function loadForm() {
  await store.fetchConfig()
  Object.assign(form, store.config)
}

async function save() {
  try {
    const changes: Record<string, any> = {}
    for (const key of Object.keys(form)) {
      if (form[key] !== store.config[key]) {
        changes[key] = form[key]
      }
    }
    if (Object.keys(changes).length === 0) return
    await store.updateConfig(changes)
    ElMessage.success('设置已保存')
    await store.fetchConfig()
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message || e}`)
  }
}

async function testProxy() {
  try {
    const resp = await fetch(`${store.apiBase}/api/test-proxy`, { method: 'POST' })
    const result = await resp.json()
    if (result.ok) {
      ElMessage.success(`代理连通 — 延迟: ${result.latency_ms}ms`)
    } else {
      ElMessage.warning(`代理测试失败: ${result.error}`)
    }
  } catch {
    ElMessage.error('代理测试请求失败')
  }
}

onMounted(async () => {
  await store.fetchConfig()
  Object.assign(form, store.config)
})
</script>

<style scoped>
.settings-card { border-radius: var(--radius-xl) !important; max-width: 800px; }
.settings-title { font-weight: 700; font-size: 17px; }
.hint { font-size: 12px; color: var(--text-muted); margin-left: 10px; }
</style>
