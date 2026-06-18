# 国内游戏每日新游排查系统 v1.1

好游快爆 (3839.com) + TapTap (taptap.cn) 新游预约/上线实时监控面板。

## v1.1 更新

### 功能
- **卡片全字段对齐**: 每条字段独立行，名称 2 行 clamp、标签 2 行占位、详情 flex 完整展开、游戏类型底部对齐
- **TapTap 类型标签**: 从 API `app_card_info.tags` 提取类型标签（角色扮演、策略、卡牌等），与事件元数据并列展示
- **历史日期可折叠**: N-1 天前默认折叠，今天及未来默认展开，点击日期头切换
- **GameCard 组件化**: 提取公共卡片组件，3839/TapTap 统一模板，新源接入更便捷

### 健壮性
- **熔断器修复**: `record_failure` SQL 参数补全，连续失败自动降频/熔断
- **线程安全**: config 单例加锁、WebSocket 广播快照、DB 全连接关闭
- **SQLite WAL 优化**: `busy_timeout=3000` 防止并发写入锁冲突
- **内存泄漏修复**: 刷新轮询 timer 组件销毁时清除、文件句柄/DB 连接全量释放
- **竞态修复**: `fetchUpdates` 加 AbortController 取消旧请求

### 安全性
- **XSS 防护**: 公告栏用 DOMPurify 白名单过滤，仅允许安全标签
- **SSRF 防护**: `validate_url` DNS 解析 + 私有 IP 拦截已激活
- **输入校验**: API limit 上限 500、配置字段长度限制、localStorage 解析异常兜底
- **TypeScript**: `AppConfig` 接口替代 `Record<string,any>`，`GameItem` 可选字段完善

### 启动
- 端口冲突检测 + 自动终止旧进程、浏览器端口轮询、退出信号处理
- `python -m backend.main` 工作目录修正、版本号统一 v1.1

## 快速开始

### 方式一：直接运行 EXE

双击 `ChinaGameTracker.exe`，浏览器自动打开 `http://127.0.0.1:8001`。

### 方式二：源码运行

```bash
# 1. 安装 Python 依赖
pip install fastapi uvicorn pydantic-settings loguru beautifulsoup4 aiohttp lxml

# 2. 启动后端
python launcher.py

# 3. 访问 http://127.0.0.1:8001
```

### 前端开发

```bash
cd frontend
npm install
npm run dev        # 访问 http://127.0.0.1:5173
npm run build      # 生产构建
```

## 数据源

| 数据源 | URL | 提取方式 | 代理 |
|--------|-----|----------|------|
| 好游快爆 | 3839.com/timeline.html | aiohttp 直连 → BeautifulSoup (`.foreList li`) | 不需要 |
| TapTap | taptap.cn/app-calendar | Web API 逐日扫描 + JSON-LD 降级 | 不需要 |

## 爬虫策略

### 好游快爆
- 静态 HTML 解析：`.foreCard` (日期块) → `.foreList li` (游戏条目)
- 提取：游戏名 (`.name em`)、标签 (`.tags .it`)、评分、图标、预约/下载状态
- 唯一标识：`3839_{slugify(游戏名)}`

### TapTap
- 调用 `webapiv2/calendar/v1/event-list?day=<ts>` API，逐日扫描（全量 90 天 / 增量 14 天）
- 提取：游戏名、图标、评分、预约数、事件类型、appId
- 唯一标识：`taptap_{appId}`
- JSON-LD 降级兜底，不依赖 Playwright

## 端口

- **8001**（不与海外系统 8000 冲突）

## 配置

编辑 EXE 同目录下的 `config.json` 或通过前端设置面板：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `proxy` | `""` | 国内站点直连，留空 |
| `update_check_interval` | 3600 | 定时抓取间隔 (秒) |
| `frontend_poll_interval` | 300 | 前端轮询间隔 (秒) |
| `enable_3839` | true | 好游快爆开关 |
| `enable_taptap` | true | TapTap 开关 |
| `display_limit_3839` | 400 | 好游快爆展示条数 |
| `display_limit_taptap` | 200 | TapTap 展示条数 |

## 技术栈

- **后端**: FastAPI + SQLite + aiohttp + BeautifulSoup + patchright
- **前端**: Vue 3 + TypeScript + Element Plus + Pinia + Vite + DOMPurify
- **打包**: PyInstaller (--console, 单文件 EXE, ~80MB)

## 目录结构

```
├── backend/
│   ├── main.py                 # FastAPI 入口 + lifespan
│   ├── config.py               # 配置管理 (热更新 + _MEIPASS 自动复制)
│   ├── api/routes.py           # REST API + WebSocket
│   ├── db/database.py          # SQLite (daily_updates + circuit_breaker)
│   ├── core/http_client.py     # aiohttp 优先 HTTP 客户端
│   ├── core/browser_manager.py # Playwright 管理器 (TapTap 已不再依赖)
│   └── cron/domestic_tracker.py # 好游快爆 + TapTap 爬虫 + 熔断器
├── frontend/
│   └── src/components/DailyPanel.vue  # 双标签页 + 右侧状态面板
├── config.json                 # 运行时配置
└── launcher.py                 # 桌面启动器
```

## 与海外系统的关系

| 维度 | 海外系统 | 国内系统 |
|------|----------|----------|
| 项目路径 | `E:\game-package-crawler` | `E:\china_game` |
| 端口 | 8000 | 8001 |
| 数据源 | Google Play + APKPure + APKCombo + APKMirror + APKVision | 好游快爆 + TapTap |
| 代理 | 需要 (梯子) | 直连 |
| HTTP 客户端 | Scrapling Fetcher (TLS 指纹) | aiohttp |
| 用途 | 包名版本排查 + 下载 | 每日新游预约监控 |
