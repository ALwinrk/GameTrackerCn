<template>
  <div
    class="game-card"
    :class="cardStatusClass(item.game_status || '')"
    @click="item.detail_url && openDetail(item.detail_url)"
    @contextmenu.prevent="onContextMenu($event, item, source)"
  >
    <!-- 图标: 绝对定位 -->
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
      <span v-if="item.status_badge" class="card-status-badge" :class="badgeClass(item.status_badge || '')">{{ item.status_badge }}</span>
    </div>
    <div v-else class="card-badges card-badges--empty"></div>
    <!-- Row 3: 标签徽章 -->
    <div v-if="item.download_count && hasTags(item.download_count)" class="card-tags">
      <span v-for="tag in splitTags(item.download_count)" :key="tag"
        class="tag-badge" :style="{ background: tagBg(tag), color: tagFg(tag) }">{{ tag }}</span>
    </div>
    <div v-else class="card-tags card-tags--empty"></div>
    <!-- Row 4: 活动描述 (flex:1, 完整展示) -->
    <div v-if="item.activity_desc" class="card-desc">{{ item.activity_desc }}</div>
    <div v-else class="card-desc card-desc--empty"></div>
    <!-- Row 5: 游戏类型 -->
    <div v-if="item.game_status" class="card-footer">
      <span class="card-game-status" :class="statusClass(item.game_status)">{{ item.game_status }}</span>
    </div>
    <div v-else class="card-footer card-footer--empty"></div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import type { GameItem } from '../stores/app'

const props = defineProps<{
  item: GameItem
  source: string
}>()

const emit = defineEmits<{
  contextmenu: [e: MouseEvent, item: GameItem, source: string]
  openDetail: [url: string]
}>()

const imgFailed = reactive<Record<string, boolean>>({})

function onImgError(pkg: string) { imgFailed[pkg] = true }
function openDetail(url: string) { emit('openDetail', url) }
function onContextMenu(e: MouseEvent, item: GameItem, source: string) {
  emit('contextmenu', e, item, source)
}

// ── 工具函数 ──
function hasTags(tagStr: string): boolean { return /[,，]/.test(tagStr) }
function splitTags(tagStr: string): string[] {
  return tagStr.split(/[,，]/).map(t => t.trim()).filter(Boolean)
}

const TAG_COLORS = [
  { bg: '#ecf5ff', fg: '#409eff' },
  { bg: '#fef0f0', fg: '#f56c6c' },
  { bg: '#f0f9eb', fg: '#67c23a' },
  { bg: '#fdf6ec', fg: '#e6a23c' },
  { bg: '#f4f0fe', fg: '#9b6ef3' },
  { bg: '#e6faf7', fg: '#1aadbc' },
  { bg: '#fef5e7', fg: '#e07b28' },
  { bg: '#fce4ec', fg: '#e91e63' },
]
function tagColor(tag: string) {
  let hash = 0
  for (let i = 0; i < tag.length; i++) hash = ((hash << 5) - hash) + tag.charCodeAt(i) | 0
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length]
}
function tagBg(tag: string): string { return tagColor(tag).bg }
function tagFg(tag: string): string { return tagColor(tag).fg }

function badgeClass(badge: string): string {
  const map: Record<string, string> = {
    '测试': 'badge-test', '招募中': 'badge-recruit',
    '内测': 'badge-test', '公测': 'badge-launch',
  }
  return map[badge] || 'badge-default'
}

function cardStatusClass(status: string): string {
  const map: Record<string, string> = {
    '预约': 'card-reserve', '试玩': 'card-trial', '下载': 'card-release',
  }
  return map[status] || 'card-release'
}

function statusClass(status: string): string {
  const map: Record<string, string> = {
    '预约': 'status-reserve', '下载': 'status-download', '试玩': 'status-trial',
  }
  return map[status] || 'status-default'
}
</script>

<style scoped>
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
  font-size: 12px; font-weight: 700; color: #fff;
  background: var(--color-primary, #409eff);
  padding: 1px 6px; border-radius: 3px;
  flex-shrink: 0; line-height: 1.5;
}
.card-status-badge {
  font-size: 12px; padding: 2px 6px;
  border-radius: 3px; font-weight: 500; flex-shrink: 0;
}
.badge-test { background: #fef0f0; color: #f56c6c; }
.badge-recruit { background: #f0f9eb; color: #67c23a; }
.badge-launch { background: #fdf6ec; color: #e6a23c; }
.badge-default { background: #ecf5ff; color: #409eff; }

/* ── Row 3: 标签徽章 (2 行 max) ── */
.card-tags {
  display: flex; flex-wrap: wrap; gap: 4px;
  height: 52px; overflow: hidden;
}
.tag-badge {
  font-size: 13px; padding: 3px 10px;
  border-radius: 5px; font-weight: 500;
  white-space: nowrap; line-height: 1.5;
}

/* ── Row 4: 活动描述 (flex:1, 完整展示, 不折叠!) ── */
.card-desc {
  flex: 1;
  font-size: 14px; font-weight: 600;
  color: var(--text-primary, #303133);
  line-height: 1.5;
  word-break: break-all;
}

/* ── Row 5: 游戏类型页脚 ── */
.card-footer {
  display: flex; align-items: center;
  height: 26px; padding-top: 4px;
  border-top: 1px solid var(--border-lighter, #f2f6fc);
}
.card-game-status {
  font-size: 13px; padding: 2px 10px;
  border-radius: 10px; font-weight: 600;
}
.status-reserve { background: #ecf5ff; color: #409eff; }
.status-download { background: #f0f9eb; color: #67c23a; }
.status-trial { background: #fdf6ec; color: #e6a23c; }
.status-default { background: #f5f7fa; color: #909399; }
</style>

<style>
/* 暗色主题 (必须非 scoped: html.dark 是外层元素) */
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
