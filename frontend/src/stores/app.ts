import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface GameItem {
  app_name: string
  package_name: string
  icon_url?: string
  detail_url?: string
  download_count?: string
  version_name?: string
  version_code?: string
  updated_at?: string
  activity_desc?: string
  status_badge?: string
  game_status?: string
}

export interface DailyData {
  '3839': GameItem[]
  taptap: GameItem[]
  poll_interval: number
  last_fetched_at?: string
}

export interface AppConfig {
  proxy: string
  domestic_proxy: string
  scraper_concurrency: number
  playwright_concurrency: number
  retry_times: number
  retry_delay: number
  request_timeout: number
  stealth_timeout: number
  update_check_interval: number
  frontend_poll_interval: number
  enable_3839: boolean
  enable_taptap: boolean
  display_limit_3839: number
  display_limit_taptap: number
  panel_max_items: number
  log_level: string
  log_retention_days: number
  notice_enabled: boolean
  notice_text: string
}

export const API_BASE = 'http://127.0.0.1:8001'

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
  const apiBase = ref(API_BASE)

  // ── 配置 ──
  const config = ref<Partial<AppConfig>>({})

  async function fetchConfig(): Promise<Partial<AppConfig>> {
    try {
      const resp = await fetch(`${apiBase.value}/api/config`)
      if (resp.ok) {
        config.value = await resp.json()
        return config.value
      }
    } catch (e) {
      console.error('Failed to load config', e)
    }
    return {}
  }

  async function updateConfig(changes: Partial<AppConfig>): Promise<Partial<AppConfig>> {
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