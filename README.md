# XHS Dashboard

**Internal operations platform for a Xiaohongshu (Little Red Book) content team.**
**小红书团队运营管理平台。**

Replaces spreadsheet-based workflows with a real-time dashboard covering content scheduling, multi-account monitoring, competitor research, and viral content analysis. Built for a content team running multiple overseas-student-targeted XHS accounts.

替代原本零散的表格协作，将内容排期、多账号数据监控、竞品研究、爆款内容分析集中在一个实时看板。服务于运营多个海外留学生 IP 账号的内容团队。

[English](#english) · [中文](#中文)

---

## English

### Why this project

Managing 5+ XHS accounts across multiple destinations (UK / US / Australia / Canada) quickly outgrows shared spreadsheets: content calendars drift, competitor data gets stale, and "which viral post did we reference last month?" becomes unanswerable. This platform gives the team a single surface for everything they do day-to-day, with all external data (follower counts, post metrics, competitor posts) refreshed automatically by a background crawler.

### Core features

| Module | What it does |
|--------|--------------|
| **Accounts** | Stats per account, team-member assignments, historical follower trend |
| **Content** | Post drafts with multi-image upload, 3-status kanban (draft → scheduled → published), full-screen detail drawer |
| **Calendar** | Monthly grid view of all scheduled posts across accounts |
| **Material Library** | Four tabs: viral posts collection, benchmark accounts (auto-fetched), topic bank, title/banned-word lists |
| **Analytics** | Follower growth line charts, benchmark comparison, viral-post rankings by likes/saves/comments, country distribution |

### System architecture

```
           ┌─────────────────────────────────────────┐
           │         Vercel (React + Vite)           │
           │  — inline styles, Recharts for graphs   │
           └──────────┬──────────────────────────────┘
                      │ read / write / subscribe (Realtime)
                      ▼
           ┌─────────────────────────────────────────┐
           │           Supabase                      │
           │   Postgres + Storage + Realtime         │
           │                                         │
           │   Tables: posts, accounts, members,     │
           │           benchmark_accounts,           │
           │           viral_posts, topics,          │
           │           account_stats_history,        │
           │           benchmark_stats_history,      │
           │           post_stats_history,           │
           │           crawl_logs                    │
           │   Bucket: post-images (public)          │
           └──────────┬──────────────────────────────┘
                      │ polls every 5 seconds
                      ▼
           ┌─────────────────────────────────────────┐
           │   Local macOS machine (LaunchAgent)     │
           │                                         │
           │   server.py — MediaCrawler + Playwright │
           │   • 5s poll: pending jobs → crawl       │
           │   • 12h APScheduler: full sync          │
           │   • Downloads & re-hosts XHS images     │
           │     to Supabase Storage                 │
           └─────────────────────────────────────────┘
```

The frontend never talks to XHS directly. Instead, users enter a link → the frontend writes `fetch_status = 'pending'` to Supabase → the local crawler picks it up within 5 seconds → results stream back via Supabase Realtime so every team member's browser updates automatically without a refresh.

### Tech stack

**Frontend** · React 18 · Vite 5 · Recharts · Lucide icons · `@supabase/supabase-js`
No router (`useState` drives view switching), no CSS framework (inline styles only), no TypeScript — deliberate choices to keep the ~4,000 lines of JSX approachable for future non-frontend contributors.

**Backend** · Supabase (Postgres, Storage, Realtime) with a single permissive RLS policy. Treated as the application's source of truth plus its job queue.

**Crawler** · Python · [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) · Playwright (persistent browser context for cookie reuse) · APScheduler · httpx

**Infra** · Vercel for zero-config CI from GitHub · macOS LaunchAgent for auto-start, auto-restart on crash, and throttled restart loops

### Engineering challenges solved

**1. Bypassing XHS's geographic API restrictions.**
XHS blocks direct API calls from non-China IPs and from HTTPS pages hitting their HTTP-only CDN. Solution: a Supabase-backed job queue. The browser queues work, the local crawler (on a Mac in China with valid session cookies) processes it. All XHS traffic originates from an authenticated local machine — no CORS, no IP blocks, no auth tokens to ship to the client.

**2. XHS CDN hotlink protection breaking every image.**
XHS image URLs have a `Referer`-based hotlink policy and serve over HTTP only — both break when loaded from a Vercel-hosted HTTPS page. Solution: the crawler downloads every image with a fake `Referer` header, re-uploads to Supabase Storage, and writes the resulting public HTTPS URL back to the database. Every image rendered in the app is served from our own bucket.

**3. Incomplete summary data from creator-feed endpoint.**
When crawling a competitor's profile, XHS's feed endpoint only returns summary data — no captions, no tags, no comment counts. Solution: after fetching the feed, the crawler calls `get_note_by_id` per post to fill in the missing fields and build the full image carousel. Costs 10 extra requests per account but makes the detail drawer actually useful.

**4. Building trend charts from scratch.**
Supabase only stores current values by default, not history. Solution: two history tables (`account_stats_history`, `benchmark_stats_history`) with a `unique(id, date)` constraint, written via upsert from the 12-hour full-sync job. One row per entity per day, naturally idempotent across retries.

**5. `xsec_token` and Chinese number parsing.**
Creator IDs alone don't work against XHS's API — every request needs a time-limited `xsec_token` from the share URL. And XHS returns follower counts as `"1.2万"` / `"10万+"`, not integers. The crawler handles both in `parse_count()` and by requiring full share URLs in config.

**6. Mobile-first responsive without a framework.**
All responsive behavior routes through a single `useIsMobile()` hook at 768px. Modals stick to the bottom on mobile (`alignItems: flex-end`) and center on desktop. Drawers slide from right (desktop) or bottom (mobile, 92dvh height with safe-area padding). Zero media queries.

### Project structure

```
src/
├── App.jsx                       # Layout, nav, account/member state
└── components/
    ├── AccountsPage.jsx          # Account list, per-account detail, stats
    ├── ContentManager.jsx        # Post grid, create/edit modal, image upload
    ├── CalendarPage.jsx          # Monthly calendar
    ├── MaterialPage.jsx          # 4-tab library: viral / benchmark / topics / titles
    ├── AnalyticsPage.jsx         # Trend charts, rankings, country breakdown
    ├── ViralPostDrawer.jsx       # Viral / benchmark post detail (image carousel)
    ├── PostDetailDrawer.jsx      # Internal post detail
    └── shared.jsx                # useIsMobile, Avatar, Badge, STATUS, fmt()

crawler/
├── server.py                     # Long-running service: polling + APScheduler
├── config.py                     # Supabase creds + ACCOUNT_MAP
├── parser.py                     # parse_count() for Chinese number strings
├── com.xhs.dashboard.crawler.plist  # LaunchAgent definition
└── setup_autostart.sh            # One-shot installer for auto-start

schema.sql                        # Core tables
analytics_schema.sql              # History snapshot tables
crawler/schema.sql                # Crawler-specific tables (stats history, crawl_logs)
```

### Local setup

**Prerequisites** Node 18+ · Python 3.11+ · a working [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout with a logged-in XHS session

```bash
# 1. Frontend
npm install
cp .env.example .env        # fill VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm run dev                 # http://localhost:5173

# 2. Database — paste each file into Supabase SQL Editor once
#    schema.sql, analytics_schema.sql, crawler/schema.sql

# 3. Crawler service
cd crawler
cp config.example.py config.py   # fill SUPABASE_URL, SUPABASE_KEY, ACCOUNT_MAP
chmod +x setup_autostart.sh
./setup_autostart.sh             # installs LaunchAgent for this checkout
# MEDIACRAWLER_DIR=/path/to/MediaCrawler ./setup_autostart.sh
tail -f logs/server.log          # verify "✅ XHS 客户端初始化成功"
```

**Optional AI external discovery loop**

After the core schema is installed, run `crawler/ai_schema.sql` in Supabase SQL Editor. Once crawler login is validated, set `EXTERNAL_DISCOVERY_ENABLED = True` in `crawler/config.py`, keep `EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"` until crawl quality is reviewed, then start both `crawler/server.py` and `crawler/ai_api.py`. In AI Search, ask a sparse question, click `去小红书找参考`, review candidates, and approve useful items.

### Design choices worth calling out

- **No auth layer.** Known 4–8 user team, shared internal tool. Adding login is pure friction.
- **Supabase Realtime instead of polling.** One subscription per relevant table; every connected browser reacts to crawler completions within milliseconds.
- **UUID-first upload pattern.** `crypto.randomUUID()` generates post IDs client-side before insert, so images upload to `post-images/{post_id}/` paths before the row exists — avoids the classic "which comes first, the row or the storage path" ordering problem.
- **Flexible JSONB columns for nested data.** `recent_posts` on `benchmark_accounts` is a JSONB array: adding fields (caption, tags, images) never required a migration.

---

## 中文

### 项目背景

运营 5+ 个面向不同留学目的地（英美澳加）的小红书账号，共享表格很快就不够用了：排期会漂移，竞品数据会过时，"上个月我们参考的爆款帖是哪一篇"成了无法追溯的问题。这个平台把团队每天的工作集中到一个界面上，外部数据（粉丝数、帖子互动、竞品动态）全部由后台爬虫自动刷新。

### 核心功能

| 模块 | 作用 |
|------|------|
| **账号管理** | 每个账号的数据概览、团队成员分工、粉丝历史趋势 |
| **内容管理** | 帖子草稿，多图上传，三态看板（草稿 → 已排期 → 已发布），全屏详情抽屉 |
| **内容日历** | 跨账号月视图，一眼看完所有排期 |
| **素材库** | 四个 Tab：爆款收藏、对标账号（自动抓取）、选题库、标题库/违禁词 |
| **数据监控** | 粉丝增长折线图、对标对比、爆款按点赞/收藏/评论排行、地区分布 |

### 系统架构

```
           ┌─────────────────────────────────────────┐
           │         Vercel（React + Vite）          │
           │   纯 inline styles · Recharts 作图      │
           └──────────┬──────────────────────────────┘
                      │ 读写 / 订阅（Realtime）
                      ▼
           ┌─────────────────────────────────────────┐
           │           Supabase                      │
           │   Postgres + Storage + Realtime         │
           │                                         │
           │   表: posts, accounts, members,         │
           │       benchmark_accounts, viral_posts,  │
           │       topics, account_stats_history,    │
           │       benchmark_stats_history,          │
           │       post_stats_history, crawl_logs    │
           │   Bucket: post-images（公开）           │
           └──────────┬──────────────────────────────┘
                      │ 每 5 秒轮询
                      ▼
           ┌─────────────────────────────────────────┐
           │      本地 macOS（LaunchAgent）          │
           │                                         │
           │  server.py · MediaCrawler + Playwright │
           │  • 5 秒轮询：pending 任务 → 爬取       │
           │  • 12 小时定时全量同步                  │
           │  • 图片下载并转存至 Supabase Storage   │
           └─────────────────────────────────────────┘
```

前端不直接请求小红书。用户粘贴链接 → 前端将 `fetch_status = 'pending'` 写入 Supabase → 本地爬虫 5 秒内接手 → 结果通过 Supabase Realtime 实时推送回所有成员的浏览器，无需手动刷新。

### 技术选型

**前端** · React 18 · Vite 5 · Recharts · Lucide icons · `@supabase/supabase-js`
不使用路由库（`useState` 切换视图），不使用 CSS 框架（全 inline styles），不使用 TypeScript — 有意简化约 4,000 行 JSX，降低后续非前端背景成员的上手门槛。

**后端** · Supabase（Postgres + Storage + Realtime），单一通用 RLS policy，同时作为数据存储和任务队列。

**爬虫** · Python · [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) · Playwright（持久化浏览器上下文，复用登录态）· APScheduler · httpx

**基础设施** · Vercel 从 GitHub 自动 CI · macOS LaunchAgent 管理爬虫进程，支持开机自启、崩溃重启、限频防抖。

### 关键工程问题与解法

**1. 绕过小红书的地域 API 限制。**
小红书屏蔽境外 IP 的直接请求，也禁止 HTTPS 页面访问其 HTTP-only 图片 CDN。解法：Supabase 作为任务队列，浏览器下发任务，本地爬虫（运行于境内、持有有效 Cookie 的 Mac）消费任务。所有小红书流量都来自已登录的本地机器——无 CORS、无 IP 封禁、无需把敏感 token 下发到前端。

**2. 图片防盗链几乎让所有图加载失败。**
小红书图片 URL 有 `Referer` 防盗链且只走 HTTP，在 Vercel 的 HTTPS 页面上都会挂。解法：爬虫带伪造 `Referer` 下载每张图，重新上传至 Supabase Storage，再把返回的 HTTPS 公开链接写回数据库。页面上所有图都托管在自己的 bucket 里。

**3. 对标账号列表接口返回的数据不完整。**
爬取竞品主页时，小红书的 feed 接口只返回摘要——没有正文、标签、评论数。解法：爬完 feed 后，对每条帖子再调一次 `get_note_by_id` 补全详情并收集完整图片组。每个账号多发 10 次请求，但详情抽屉里能看到真正有用的内容。

**4. 趋势图需要历史数据，但 Supabase 只存当前值。**
解法：新增两张历史表（`account_stats_history`、`benchmark_stats_history`），加 `unique(id, date)` 约束，由每 12 小时的全量同步 upsert 写入。每实体每天一行，天然幂等。

**5. `xsec_token` 和中文数字解析。**
光靠用户 ID 调不通接口——每个请求都需要分享链接里带的临时 `xsec_token`。而粉丝数又是 `"1.2万"` / `"10万+"` 这样的中文字符串，不是数字。`parse_count()` 统一处理中文/英文/带符号数字，config 要求填完整的分享 URL。

**6. 响应式无框架实现。**
所有断点判断走一个 `useIsMobile()` hook（768px）。Modal 在手机上贴底、桌面居中；抽屉在桌面从右滑入、手机从下滑入（92dvh + 安全区内边距）。零 media query。

### 目录结构

```
src/
├── App.jsx                       # 布局、导航、账号/成员状态
└── components/
    ├── AccountsPage.jsx          # 账号列表、详情、统计
    ├── ContentManager.jsx        # 帖子网格、新建/编辑、图片上传
    ├── CalendarPage.jsx          # 月视图日历
    ├── MaterialPage.jsx          # 素材库：爆款/对标/选题/标题
    ├── AnalyticsPage.jsx         # 趋势图、排行、地区分布
    ├── ViralPostDrawer.jsx       # 爆款/对标帖子详情抽屉
    ├── PostDetailDrawer.jsx      # 内部帖子详情
    └── shared.jsx                # useIsMobile、Avatar、Badge、STATUS、fmt

crawler/
├── server.py                     # 常驻服务：轮询 + APScheduler
├── config.py                     # Supabase 凭证 + ACCOUNT_MAP
├── parser.py                     # 中文数字解析
├── com.xhs.dashboard.crawler.plist  # LaunchAgent 定义
└── setup_autostart.sh            # 一键安装开机自启

schema.sql                        # 核心表
analytics_schema.sql              # 历史快照表
crawler/schema.sql                # 爬虫专用表（历史快照、爬取日志）
```

### 本地启动

**前置** Node 18+ · Python 3.11+ · 已配置好登录态的 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)

```bash
# 1. 前端
npm install
cp .env.example .env        # 填入 VITE_SUPABASE_URL 和 VITE_SUPABASE_ANON_KEY
npm run dev                 # http://localhost:5173

# 2. 数据库 — 在 Supabase SQL Editor 中依次执行
#    schema.sql · analytics_schema.sql · crawler/schema.sql

# 3. 爬虫服务
cd crawler
cp config.example.py config.py   # 填入 SUPABASE_URL、SUPABASE_KEY、ACCOUNT_MAP
chmod +x setup_autostart.sh
./setup_autostart.sh             # 为当前仓库路径安装 LaunchAgent
# MEDIACRAWLER_DIR=/path/to/MediaCrawler ./setup_autostart.sh
tail -f logs/server.log          # 看到 "✅ XHS 客户端初始化成功" 即可
```

**可选：AI 外部发现闭环**

核心 schema 执行完成后，在 Supabase SQL Editor 中继续执行 `crawler/ai_schema.sql`。确认爬虫登录态可用后，在 `crawler/config.py` 中设置 `EXTERNAL_DISCOVERY_ENABLED = True`，并先保持 `EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"`，等人工确认抓取质量后再调整。然后同时启动 `crawler/server.py` 和 `crawler/ai_api.py`，在 AI Search 里提一个信息较少的问题，点击 `去小红书找参考`，检查候选结果并批准有用素材。

### 值得一提的设计取舍

- **不做登录。** 4–8 人内部小团队，成员已知，登录只会增加摩擦。
- **Supabase Realtime 替代轮询。** 每个相关表订阅一次，爬虫写完结果所有在线成员的页面毫秒级同步。
- **UUID-first 上传模式。** `crypto.randomUUID()` 在前端先生成 post ID，图片上传到 `post-images/{post_id}/` 后再 insert 记录——绕开"先有图还是先有行"的顺序问题。
- **JSONB 字段承载嵌套数据。** `benchmark_accounts.recent_posts` 是 JSONB 数组，新增字段（caption、tags、images）无需数据库迁移。
