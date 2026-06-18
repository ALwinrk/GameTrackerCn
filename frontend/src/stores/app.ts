import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface GameItem {
  app_name: string
  icon_url: string
  detail_url: string
  package_name: string
  download_count: string
  version_name: string
  updated_at: string
  activity_desc: string
  status_badge: string
  game_status: string
}

export interface DailyData {
  '3839': GameItem[]
  taptap: GameItem[]
  poll_interval: number
  last_fetched_at?: string
}

export const useAppStore = defineStore('app', () => {
  // ── 主题 ──
  const isDark = ref(localStorage.getItem('china-game-dark') === 'true')
  function toggleDark() {
    isDark.value = !isDark.value
    localStorage.setItem('china-game-dark', String(isDark.value))
    applyTheme()
  }
  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  // ── API 基础地址 ──
  const apiBase = ref('http://127.0.0.1:8001')

  // ── 配置 ──
  const config = ref<Record<string, any>>({})

  async function fetchConfig() {
    try {
      const resp = await fetch(`${apiBase.value}/api/config`)
      if (resp.ok) config.value = await resp.json()
    } catch (e) {
      console.error('Failed to load config', e)
    }
  }

  async function updateConfig(changes: Record<string, any>) {
    const resp = await fetch(`${apiBase.value}/api/config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    })
    if (resp.ok) return await resp.json()
    throw new Error(`Config update failed: ${resp.status}`)
  }

  // ── 初始化 ──
  applyTheme()

  return {
    isDark, toggleDark, applyTheme,
    apiBase, config, fetchConfig, updateConfig,
  }
})
