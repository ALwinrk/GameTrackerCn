<template>
  <div class="daily-panel">
    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="panel-header">
          <div class="header-left">
            <span class="panel-title">📰 国内新游实时监控</span>
            <span v-if="lastFetchedAt" class="fetched-time">数据更新于 {{ lastFetchedAt }}</span>
          </div>
          <div class="header-actions">
            <!-- 数据源选择器 -->
            <el-popover placement="bottom" :width="200" trigger="click">
              <template #reference>
                <el-button size="small" round>
                  📡 数据源 ({{ selectedSources.length }}/2)
                </el-button>
              </template>
              <div class="source-selector">
                <div class="source-actions">
                  <el-button size="small" text @click="selectAllSources">全选</el-button>
                  <el-button size="small" text @click="clearSources">清空</el-button>
                </div>
                <el-checkbox-group v-model="selectedSources" @change="persistSources">
                  <el-checkbox v-for="s in allSources" :key="s.value" :label="s.value" class="source-checkbox">
                    {{ s.label }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </el-popover>
            <el-button size="small" @click="refreshPanel" :loading="loadingPanel" :disabled="!selectedSources.length" round>
              🔄 刷新面板
            </el-button>
            <el-button size="small" :icon="Refresh" @click="refreshIncremental"
              :loading="loadingIncr" :disabled="!selectedSources.length" round>
              增量刷新
            </el-button>
            <el-button size="small" type="primary" :icon="Refresh" @click="refreshFull"
              :loading="loadingFull" :disabled="!selectedSources.length" round>
              全量刷新
            </el-button>
          </div>
        </div>
      </template>

      <div class="panel-body">
        <div class="panel-left">
          <el-tabs v-model="activeSource">
            <!-- 好游快爆 — 卡片时间轴 -->
            <el-tab-pane label="🔥 好游快爆新游" name="3839">
              <div v-if="data['3839']?.length" class="timeline-rows">
                <div v-for="(group, gi) in groupedItems(data['3839'])" :key="gi" class="date-group" :style="{ animationDelay: gi * 0.06 + 's' }">
                  <!-- 日期头部 -->
                  <div class="date-header" @click="toggleGroup('3839', group.date)">
                    <span class="fold-arrow">{{ isGroupCollapsed('3839', group.date) ? '▶' : '▼' }}</span>
                    <span class="date-line"></span>
                    <span class="date-text">{{ formatDateLabel(group.date) }}</span>
                    <span class="date-count">{{ group.items.length }} 款游戏</span>
                  </div>
                  <!-- 卡片行 -->
                  <div class="card-row" v-show="!isGroupCollapsed('3839', group.date)">
                    <div
                      v-for="item in group.items" :key="item.package_name"
                      class="game-card"
                      :class="cardStatusClass(item.game_status)"
                      @click="item.detail_url && openDetail(item.detail_url)"
                      @contextmenu.prevent="onContextMenu($event, item, '3839')"
                    >
                      <!-- 图标: 绝对定位, 不参与 flex 流 -->
                      <div class="card-icon-wrap">
                        <img v-if="item.icon_url && !imgFailed[item.package_name]" :src="item.icon_url" class="card-icon" loading="lazy"
                          referrerpolicy="no-referrer" @error="onImgError(item.package_name)" />
                        <span v-else class="card-icon-placeholder">🎮</span>
                      </div>
                      <!-- Row 1: 名称 (2 行 clamp) -->
                      <span class="card-name">{{ item.app_name }}</span>
                      <!-- Row 2: 评分 + 状态徽章 -->
                      <div v-if="item.version_name || item.status_badge" class="card-badges">
                        <span v-if="item.version_name" class="card-score">{{ item.version_name }}</span>
                        <span v-if="item.status_badge" class="card-status-badge" :class="badgeClass(item.status_badge)">{{ item.status_badge }}</span>
                      </div>
                      <div v-else class="card-badges card-badges--empty"></div>
                      <!-- Row 3: 标签徽章 -->
                      <div v-if="item.download_count" class="card-tags">
                        <span v-for="tag in splitTags(item.download_count)" :key="tag"
                          class="tag-badge" :style="{ background: tagBg(tag), color: tagFg(tag) }">{{ tag }}</span>
                      </div>
                      <div v-else class="card-tags card-tags--empty"></div>
                      <!-- Row 4: 活动描述 (flex:1, 完整展示, 不折叠) -->
                      <div v-if="item.activity_desc" class="card-desc">{{ item.activity_desc }}</div>
                      <div v-else class="card-desc card-desc--empty"></div>
                      <!-- Row 5: 游戏类型 -->
                      <div v-if="item.game_status" class="card-footer">
                        <span class="card-game-status" :class="statusClass(item.game_status)">{{ item.game_status }}</span>
                      </div>
                      <div v-else class="card-footer card-footer--empty"></div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-hint">
                <span>暂无好游快爆数据</span>
                <span class="empty-sub">点击上方「全量刷新」开始首次抓取</span>
              </div>
            </el-tab-pane>

            <!-- TapTap — 卡片时间轴 -->
            <el-tab-pane label="🎮 TapTap 新游日历" name="taptap">
              <div v-if="data.taptap?.length" class="timeline-rows">
                <div v-for="(group, gi) in groupedItems(data.taptap)" :key="gi" class="date-group" :style="{ animationDelay: gi * 0.06 + 's' }">
                  <div class="date-header" @click="toggleGroup('taptap', group.date)">
                    <span class="fold-arrow">{{ isGroupCollapsed('taptap', group.date) ? '▶' : '▼' }}</span>
                    <span class="date-line"></span>
                    <span class="date-text">{{ formatDateLabel(group.date) }}</span>
                    <span class="date-count">{{ group.items.length }} 款游戏</span>
                  </div>
                  <div class="card-row" v-show="!isGroupCollapsed('taptap', group.date)">
                    <div
                      v-for="item in group.items" :key="item.package_name"
                      class="game-card"
                      :class="cardStatusClass(item.game_status)"
                      @click="item.detail_url && openDetail(item.detail_url)"
                      @contextmenu.prevent="onContextMenu($event, item, 'taptap')"
                    >
                      <!-- 图标: 绝对定位, 不参与 flex 流 -->
                      <div class="card-icon-wrap">
                        <img v-if="item.icon_url && !imgFailed[item.package_name]" :src="item.icon_url" class="card-icon" loading="lazy"
                          referrerpolicy="no-referrer" @error="onImgError(item.package_name)" />
                        <span v-else class="card-icon-placeholder">🎮</span>
                      </div>
                      <!-- Row 1: 名称 (2 行 clamp) -->
                      <span class="card-name">{{ item.app_name }}</span>
                      <!-- Row 2: 评分 + 状态徽章 -->
                      <div v-if="item.version_name || item.status_badge" class="card-badges">
                        <span v-if="item.version_name" class="card-score">{{ item.version_name }}</span>
                        <span v-if="item.status_badge" class="card-status-badge" :class="badgeClass(item.status_badge)">{{ item.status_badge }}</span>
                      </div>
                      <div v-else class="card-badges card-badges--empty"></div>
                      <!-- Row 3: 标签徽章 (含逗号 → 标签列表) -->
                      <div v-if="item.download_count && hasTags(item.download_count)" class="card-tags">
                        <span v-for="tag in splitTags(item.download_count)" :key="tag"
                          class="tag-badge" :style="{ background: tagBg(tag), color: tagFg(tag) }">{{ tag }}</span>
                      </div>
                      <div v-else class="card-tags card-tags--empty"></div>
                      <!-- Row 4: 活动描述 (纯文本, flex:1, 完整展示) -->
                      <div v-if="item.activity_desc" class="card-desc">{{ item.activity_desc }}</div>
                      <div v-else class="card-desc card-desc--empty"></div>
                      <!-- Row 5: 游戏类型 -->
                      <div v-if="item.game_status" class="card-footer">
                        <span class="card-game-status" :class="statusClass(item.game_status)">{{ item.game_status }}</span>
                      </div>
                      <div v-else class="card-footer card-footer--empty"></div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-hint">
                <span>暂无 TapTap 数据</span>
                <span class="empty-sub">点击上方「全量刷新」开始首次抓取</span>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>

      <!-- 底部状态条 -->
      <div class="status-bar">
        <div class="status-bar-inner">
          <div class="sb-item">
            <span class="status-dot" :class="crawlStatus.running ? 'running' : 'idle'"></span>
            <span>爬虫 {{ crawlStatus.running ? '运行中' : '空闲' }}</span>
            <span v-if="crawlStatus.sources.length" class="sb-source">| 抓取: {{ crawlStatus.sources.join(', ') }}</span>
          </div>
          <div class="sb-item">
            📊 快爆 <b>{{ data['3839']?.length || 0 }}</b> 条 | TapTap <b>{{ data.taptap?.length || 0 }}</b> 条
            <span v-if="lastFetchedAt" class="sb-update">| 更新于 {{ lastFetchedAt }}</span>
          </div>
          <div class="sb-item sb-log">
            <span v-if="crawlLog.length" class="sb-log-text">
              📋 {{ crawlLog[crawlLog.length-1].time }} [{{ crawlLog[crawlLog.length-1].source === '3839' ? '快爆' : 'TapTap' }}] {{ crawlLog[crawlLog.length-1].message }}
            </span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 右键复制菜单 -->
    <div
      v-if="ctxMenu.show"
      class="ctx-menu"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @mouseleave="hideMenu"
    >
      <div class="ctx-menu-item" @click="copyIdentifier">📋 复制唯一标识</div>
      <div class="ctx-menu-item" @click="copyGameName">📝 复制游戏名</div>
      <div v-if="ctxMenu.detailUrl" class="ctx-menu-item" @click="openDetail(ctxMenu.detailUrl)">
        🔗 打开详情页
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '../stores/app'
import type { GameItem, DailyData } from '../stores/app'

const store = useAppStore()

// ── 数据源选择 ──
const allSources = [
  { value: '3839', label: '好游快爆新游预约' },
  { value: 'taptap', label: 'TapTap 新游日历' },
]
const STORAGE_KEY = 'china_daily_sources'
const savedSources = localStorage.getItem(STORAGE_KEY)
const selectedSources = ref<string[]>(
  savedSources ? JSON.parse(savedSources) : allSources.map(s => s.value)
)
function persistSources() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(selectedSources.value))
}
function selectAllSources() {
  selectedSources.value = allSources.map(s => s.value)
  persistSources()
}
function clearSources() {
  selectedSources.value = []
  persistSources()
}

// ── 面板数据 ──
const data = ref<DailyData>({
  '3839': [], taptap: [],
  poll_interval: 300,
})
const loading = ref(false)
const activeSource = ref('3839')
const lastFetchedAt = ref('')
let pollTimer: number | null = null
let lastModified: string | null = null

// ── 爬虫状态 + 事件日志 ──
const crawlStatus = reactive({ running: false, sources: [] as string[] })
const crawlLog = ref<Array<{ time: string; source: string; event: string; message: string }>>([])

// ── 图片加载失败回退 ──
const imgFailed = reactive<Record<string, boolean>>({})
function onImgError(pkg: string) { imgFailed[pkg] = true }
let statusPollTimer: number | null = null

async function fetchCrawlLog() {
  try {
    const resp = await fetch(`${store.apiBase}/api/crawl-log?limit=15`)
    if (resp.ok) {
      const json = await resp.json()
      crawlLog.value = json.entries || []
      crawlStatus.running = json.refreshing?.length > 0
      crawlStatus.sources = json.refreshing || []
    }
  } catch {}
}

function startStatusPolling() {
  fetchCrawlLog()
  if (statusPollTimer) clearInterval(statusPollTimer)
  statusPollTimer = window.setInterval(fetchCrawlLog, 2000)
}

// ── 右键菜单 ──
const ctxMenu = reactive({
  show: false, x: 0, y: 0,
  identifier: '', gameName: '', detailUrl: '',
})
function onContextMenu(e: MouseEvent, row: GameItem, _source: string) {
  ctxMenu.show = true
  let mx = e.clientX + 4
  let my = e.clientY + 4
  if (mx + 160 > window.innerWidth) mx = e.clientX - 160
  if (my + 120 > window.innerHeight) my = e.clientY - 120
  ctxMenu.x = mx
  ctxMenu.y = my
  ctxMenu.identifier = row.package_name
  ctxMenu.gameName = row.app_name
  ctxMenu.detailUrl = row.detail_url
}
function copyIdentifier() {
  navigator.clipboard.writeText(ctxMenu.identifier).then(() => {
    ElMessage.success({ message: `已复制 ${ctxMenu.identifier}`, duration: 1500 })
  }).catch(() => ElMessage.error('复制失败'))
  ctxMenu.show = false
}
function copyGameName() {
  navigator.clipboard.writeText(ctxMenu.gameName).then(() => {
    ElMessage.success({ message: `已复制 ${ctxMenu.gameName}`, duration: 1500 })
  }).catch(() => ElMessage.error('复制失败'))
  ctxMenu.show = false
}
function hideMenu() { ctxMenu.show = false }
function openDetail(url: string) { window.open(url, '_blank') }

// ── 工具函数 ──
function chunkItems(items: GameItem[], size: number): GameItem[][] {
  const chunks: GameItem[][] = []
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size))
  }
  return chunks
}

// ── 日期分组 ──
interface DateGroup { date: string; items: GameItem[]; collapsed: boolean }
function groupedItems(items: GameItem[]): DateGroup[] {
  // 计算昨天日期，过滤掉前天及更早的历史数据
  const yest = new Date()
  yest.setDate(yest.getDate() - 1)
  const yestStr = yest.toISOString().slice(0, 10)

  // 1. 按日期分组（只保留昨天及以后）
  const map = new Map<string, GameItem[]>()
  for (const item of items) {
    const date = item.updated_at || '未知日期'
    if (date < yestStr) continue
    if (!map.has(date)) map.set(date, [])
    map.get(date)!.push(item)
  }
  // 2. 组内排序：预约 > 试玩 > 下载 > 其它
  const statusOrder: Record<string, number> = { '预约': 0, '试玩': 1, '下载': 2 }
  for (const [, list] of map) {
    list.sort((a, b) => (statusOrder[a.game_status] ?? 3) - (statusOrder[b.game_status] ?? 3))
  }
  // 3. 日期升序，今天排最前
  const today = new Date().toISOString().slice(0, 10)
  return Array.from(map.entries())
    .sort(([a], [b]) => {
      if (a === today) return -1
      if (b === today) return 1
      return a.localeCompare(b)
    })
    .map(([date, items]) => ({ date, items, collapsed: date !== today }))
}

// ── 折叠/展开日期组 (记录用户手动切换, 昨天及以前默认折叠) ──
const manualToggles = reactive(new Map<string, boolean>())
function groupKey(source: string, date: string) { return `${source}::${date}` }
function isGroupCollapsed(source: string, date: string): boolean {
  const key = groupKey(source, date)
  const today = new Date().toISOString().slice(0, 10)
  // 默认: N-1天及以前折叠, N天及以后展开
  const defaultCollapsed = date < today
  // 用户手动切换过 → 以用户选择为准; 否则用默认
  return manualToggles.has(key) ? manualToggles.get(key)! : defaultCollapsed
}
function toggleGroup(source: string, date: string) {
  const key = groupKey(source, date)
  manualToggles.set(key, !isGroupCollapsed(source, date))
}

// ── 日期格式化: 2026-06-08 → "06月08日" ──
function formatDateLabel(dateStr: string): string {
  const today = new Date().toISOString().slice(0, 10)
  const m = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (m) {
    const label = `${m[2]}月${m[3]}日`
    return dateStr === today ? `今天 · ${label}` : label
  }
  return dateStr
}

// ── 判断 download_count 是标签列表还是普通文本 ──
function hasTags(tagStr: string): boolean {
  // 含逗号(中/英)说明是标签列表; 否则是普通描述文本
  return /[,，]/.test(tagStr)
}

// ── 标签拆分 (download_count 存逗号分隔标签) ──
function splitTags(tagStr: string): string[] {
  return tagStr.split(/[,，]/).map(t => t.trim()).filter(Boolean)
}

// ── 标签颜色池 ──
const TAG_COLORS = [
  { bg: '#ecf5ff', fg: '#409eff' },  // 蓝
  { bg: '#fef0f0', fg: '#f56c6c' },  // 红
  { bg: '#f0f9eb', fg: '#67c23a' },  // 绿
  { bg: '#fdf6ec', fg: '#e6a23c' },  // 橙
  { bg: '#f4f0fe', fg: '#9b6ef3' },  // 紫
  { bg: '#e6faf7', fg: '#1aadbc' },  // 青
  { bg: '#fef5e7', fg: '#e07b28' },  // 深橙
  { bg: '#fce4ec', fg: '#e91e63' },  // 粉
]
function tagColor(tag: string): typeof TAG_COLORS[0] {
  let hash = 0
  for (let i = 0; i < tag.length; i++) hash = ((hash << 5) - hash) + tag.charCodeAt(i) | 0
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length]
}
function tagBg(tag: string): string { return tagColor(tag).bg }
function tagFg(tag: string): string { return tagColor(tag).fg }

// ── 状态徽章样式 ──
function badgeClass(badge: string): string {
  const map: Record<string, string> = {
    '测试': 'badge-test',
    '招募中': 'badge-recruit',
    '内测': 'badge-test',
    '公测': 'badge-launch',
  }
  return map[badge] || 'badge-default'
}

// ── 卡片状态 class ──
function cardStatusClass(status: string): string {
  const map: Record<string, string> = {
    '预约': 'card-reserve',
    '试玩': 'card-trial',
    '下载': 'card-release',
  }
  return map[status] || 'card-release'
}

// ── 游戏状态样式 ──
function statusClass(status: string): string {
  const map: Record<string, string> = {
    '预约': 'status-reserve',
    '下载': 'status-download',
    '试玩': 'status-trial',
  }
  return map[status] || 'status-default'
}

// ── 数据获取 ──
async function fetchUpdates(force: boolean = false): Promise<void> {
  loading.value = true
  try {
    const headers: Record<string, string> = {}
    if (!force && lastModified) headers['If-Modified-Since'] = lastModified
    const resp = await fetch(`${store.apiBase}/api/daily-updates?limit=60`, { headers })
    if (resp.status === 304) return
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const json = await resp.json()
    data.value = json
    lastFetchedAt.value = json.last_fetched_at || ''
    const lm = resp.headers.get('Last-Modified')
    if (lm) lastModified = lm
    if (json.poll_interval) resetPollTimer(json.poll_interval * 1000)
  } catch (e) {
    console.error('Daily updates fetch failed', e)
    ElMessage.error('面板数据加载失败')
  } finally {
    loading.value = false
  }
}

function resetPollTimer(ms: number): void {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = window.setInterval(() => fetchUpdates(), ms)
}

// ── 刷新动作 ──
const loadingIncr = ref(false)
const loadingFull = ref(false)
const loadingPanel = ref(false)
const refreshPolling = ref(false)

async function refreshPanel(): Promise<void> {
  if (!selectedSources.value.length) { ElMessage.warning('请先选择数据源'); return }
  loadingPanel.value = true
  try {
    await fetchUpdates(true)
    ElMessage.success('面板已刷新')
  } catch { ElMessage.warning('面板数据加载失败') }
  finally { loadingPanel.value = false }
}

function startRefreshPolling(label: string): void {
  if (refreshPolling.value) return
  refreshPolling.value = true
  let attempts = 0
  const maxAttempts = 24
  const timer = setInterval(async () => {
    attempts++
    await fetchUpdates(true)
    try {
      const sr = await fetch(`${store.apiBase}/api/daily-updates/refresh-status`)
      const sj = await sr.json()
      if (!sj.running || attempts >= maxAttempts) {
        clearInterval(timer)
        refreshPolling.value = false
        if (attempts >= maxAttempts) ElMessage.warning(`${label}：等待超时，请稍后手动刷新面板`)
        else ElMessage.success(`${label}完成`)
      }
    } catch {
      clearInterval(timer)
      refreshPolling.value = false
    }
  }, 5000)
}

async function refreshIncremental(): Promise<void> {
  if (!selectedSources.value.length) { ElMessage.warning('请先选择数据源'); return }
  loadingIncr.value = true
  persistSources()
  try {
    const resp = await fetch(`${store.apiBase}/api/daily-updates/refresh-incremental`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sources: selectedSources.value }),
    })
    const result = await resp.json()
    if (result.status === 'started') {
      ElMessage.info('增量刷新已启动，后台抓取中...')
      startRefreshPolling('增量刷新')
    } else if (result.status === 'busy') {
      ElMessage.warning('刷新已在后台运行中')
    } else {
      ElMessage.warning(result.message || '未知状态')
    }
  } catch { ElMessage.error('刷新请求失败') }
  finally { loadingIncr.value = false }
}

async function refreshFull(): Promise<void> {
  if (!selectedSources.value.length) { ElMessage.warning('请先选择数据源'); return }
  loadingFull.value = true
  persistSources()
  try {
    const resp = await fetch(`${store.apiBase}/api/daily-updates/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sources: selectedSources.value }),
    })
    const result = await resp.json()
    if (result.status === 'started') {
      ElMessage.info('全量刷新已启动，后台抓取中...')
      startRefreshPolling('全量刷新')
    } else if (result.status === 'busy') {
      ElMessage.warning('刷新已在后台运行中')
    } else {
      ElMessage.warning(result.message || '未知状态')
    }
  } catch { ElMessage.error('刷新请求失败') }
  finally { loadingFull.value = false }
}

onMounted(async () => {
  await fetchUpdates()
  startStatusPolling()
  const intervalMs = (data.value.poll_interval || 300) * 1000
  pollTimer = window.setInterval(() => fetchUpdates(), intervalMs)
  document.addEventListener('click', hideMenu)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (statusPollTimer) clearInterval(statusPollTimer)
  document.removeEventListener('click', hideMenu)
})
</script>

<style scoped>
/* ================================================================
   面板级布局
   ================================================================ */
.panel-card { border-radius: 0 !important; border: none !important; box-shadow: none !important; width: 100%; }

.panel-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.header-left { display: flex; align-items: center; gap: 14px; }
.header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.panel-title { font-weight: 700; font-size: 17px; }
.fetched-time { font-size: 13px; color: var(--text-muted); font-style: italic; }

/* 全宽布局 */
.panel-body { display: flex; flex-direction: column; gap: 16px; }
.panel-left { width: 100%; }

/* 底部状态条 */
.status-bar {
  margin-top: 12px;
  padding: 10px 16px;
  background: var(--bg-card, rgba(255,255,255,0.85));
  border: 1px solid var(--border-lighter, #f2f6fc);
  border-radius: 8px;
}
.status-bar-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  font-size: 12px;
  color: var(--text-secondary, #909399);
  flex-wrap: wrap;
}
.sb-item { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.sb-item b { color: var(--color-primary, #409eff); }
.sb-source { color: var(--text-muted, #c0c4cc); }
.sb-update { color: var(--text-muted, #c0c4cc); font-style: italic; }
.sb-log { flex: 1; min-width: 0; overflow: hidden; }
.sb-log-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }

/* ================================================================
   状态指示器 (底部条 + 通用)
   ================================================================ */
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.status-dot.idle { background: var(--text-muted); }
.status-dot.running { background: var(--color-success); animation: pulse-dot 1.2s infinite; }

.source-selector { display: flex; flex-direction: column; gap: 4px; }
.source-actions { display: flex; gap: 8px; margin-bottom: 4px; }
.source-checkbox { margin: 4px 0; }

.empty-hint {
  text-align: center; padding: 60px 0; color: var(--text-muted);
  display: flex; flex-direction: column; gap: 8px;
}
.empty-sub { font-size: 12px; opacity: 0.7; }

/* ================================================================
   时间轴容器 — 双列 Grid
   ================================================================ */
.timeline-wrapper {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

/* TapTap 专用: 单列全宽垂直堆叠 */
.timeline-rows {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* ── 日期分组 ── */
.date-group {
  animation: fadeInUp 0.4s ease-out both;
  min-width: 0;
}

/* ── 日期头部: 蓝色竖线 + 日期文字 ── */
.date-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-left: 2px;
  cursor: pointer;
  user-select: none;
}
.date-header:hover .fold-arrow { color: var(--color-primary, #409eff); }
.fold-arrow {
  font-size: 14px;
  color: var(--text-muted, #c0c4cc);
  transition: color 0.2s;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}
.date-line {
  width: 3px;
  height: 22px;
  border-radius: 2px;
  background: var(--color-primary, #409eff);
  flex-shrink: 0;
}
.date-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary, #303133);
}
.date-count {
  font-size: 14px;
  color: var(--text-muted, #c0c4cc);
  margin-left: 4px;
}

/* ── 卡片行: Grid 固定列宽 垂直90°对齐 ── */
.card-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, 220px);
  gap: 12px;
  align-items: stretch;
}

/* ================================================================
   游戏卡片 — flex column 独立行布局
   ================================================================ */
.game-card {
  position: relative;
  max-width: 100%;
  min-height: 240px;
  border-radius: 14px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.22s ease;
  border: 1px solid var(--border-light, #ebeef5);
  display: flex;
  flex-direction: column;
  gap: 6px;
  user-select: none;
}
.game-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
  border-color: var(--color-primary-light-5, #a0cfff);
}

/* 预约游戏: 蓝色背景 */
.card-reserve { background: #e8f2ff; border-color: #b3d8ff; }
.card-trial { background: #fef7e8; border-color: #f5d9a0; }
.card-release { background: #e8f8ed; border-color: #b3e6c8; }
.game-card:not(.card-reserve):not(.card-trial):not(.card-release) { background: #ffffff; }

/* ── 图标: 绝对定位左上角 ── */
.card-icon-wrap {
  position: absolute;
  top: 18px; left: 18px;
  width: 48px; height: 48px;
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
  background: #f5f7fa;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
}
.card-icon { width: 48px; height: 48px; object-fit: cover; }
.card-icon-placeholder { font-size: 24px; line-height: 1; }

/* ── Row 1: 名称 (2 行 clamp, 避让图标) ── */
.card-name {
  padding-left: 58px;
  height: 44px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #303133);
  line-height: 1.4;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── Row 2: 评分 + 状态徽章 ── */
.card-badges {
  padding-left: 58px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  height: 24px;
}
.card-score {
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: var(--color-primary, #409eff);
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  line-height: 1.5;
}
.card-status-badge {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 500;
  flex-shrink: 0;
}
.badge-test { background: #fef0f0; color: #f56c6c; }
.badge-recruit { background: #f0f9eb; color: #67c23a; }
.badge-launch { background: #fdf6ec; color: #e6a23c; }
.badge-default { background: #ecf5ff; color: #409eff; }

/* ── Row 3: 标签徽章 (2 行 max) ── */
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  height: 52px;
  overflow: hidden;
}
.tag-badge {
  font-size: 13px;
  padding: 3px 10px;
  border-radius: 5px;
  font-weight: 500;
  white-space: nowrap;
  line-height: 1.5;
}

/* ── Row 4: 活动描述 (flex:1, 完整展示, 不折叠!) ── */
.card-desc {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #303133);
  line-height: 1.5;
  word-break: break-all;
  /* 注意: 无 overflow:hidden, 无 line-clamp — 详情必须完整可见 */
}

/* ── Row 5: 游戏类型页脚 ── */
.card-footer {
  display: flex;
  align-items: center;
  height: 26px;
  padding-top: 4px;
  border-top: 1px solid var(--border-lighter, #f2f6fc);
}
.card-game-status {
  font-size: 13px;
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 600;
}
.status-reserve { background: #ecf5ff; color: #409eff; }
.status-download { background: #f0f9eb; color: #67c23a; }
.status-trial { background: #fdf6ec; color: #e6a23c; }
.status-default { background: #f5f7fa; color: #909399; }

/* ================================================================
   右键菜单
   ================================================================ */
.ctx-menu {
  position: fixed; z-index: 9999;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px; padding: 4px 0;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
  min-width: 160px;
}
.ctx-menu-item {
  padding: 8px 16px; cursor: pointer;
  font-size: 13px; white-space: nowrap;
  color: var(--text-primary);
}
.ctx-menu-item:hover {
  background: var(--color-primary-light-9, #ecf5ff);
  color: var(--color-primary);
}

/* ================================================================
   动画
   ================================================================ */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pulse-dot {
  0%, 100% { box-shadow: 0 0 0 0 rgba(103, 194, 58, 0.6); }
  50% { box-shadow: 0 0 0 6px rgba(103, 194, 58, 0); }
}
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ================================================================
   暗色主题覆盖
   ================================================================ */
html.dark .card-reserve { background: #1a2a3a; border-color: #2a4a6a; }
html.dark .card-trial { background: #2a2218; border-color: #5a4a28; }
html.dark .card-release { background: #1a2a1e; border-color: #2a4a2a; }
html.dark .game-card:not(.card-reserve):not(.card-trial):not(.card-release) { background: #1e1e20; border-color: #333335; }
html.dark .card-icon-wrap { background: #2a2a2c; }
html.dark .card-desc { font-weight: 600; color: #cfd3dc; }
html.dark .card-footer { border-top-color: #2a2a2c; }
html.dark .status-reserve { background: #1a2a3a; color: #79bbff; }
html.dark .status-download { background: #1a2e1a; color: #67c23a; }
html.dark .status-trial { background: #2a241a; color: #e6a23c; }
html.dark .status-default { background: #2a2a2c; color: #909399; }
html.dark .badge-test { background: #2a1a1a; color: #f89898; }
html.dark .badge-recruit { background: #1a2e1a; color: #7ddb5a; }
html.dark .badge-launch { background: #2a241a; color: #eeb956; }
html.dark .badge-default { background: #1a2a3a; color: #79bbff; }
</style>
