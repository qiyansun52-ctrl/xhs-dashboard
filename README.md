# XHS Dashboard

Real-time content operations dashboard for a multi-account Xiaohongshu (RedNote) workflow, backed by a Supabase-queued local Playwright crawler and an AI retrieval layer for viral-content search.
**小红书多账号运营看板：Supabase 任务队列 + 本地 Playwright 爬虫 + AI 语义检索。**

> Status: working prototype in active use by a 4–8 person content team. No public demo (data is private and the crawler requires a logged-in XHS session). 开发中，无公开 demo。

<!-- TODO: add screenshots of accounts page, content kanban, analytics, AI search drawer -->

---

## Why this exists / 项目背景

The team runs 5+ XHS personas targeting Chinese students applying to UK / US / AU / CA universities. Shared spreadsheets stopped working at ~3 accounts: content calendars drifted, follower history was lost, and "which viral post did we reference last month?" became unanswerable. This project replaces all of that with a single live dashboard whose external data is refreshed automatically by a background crawler.

运营 5+ 个面向英美澳加留学生的小红书账号，表格协作扩展不到这个规模。该平台把排期、数据监控、对标研究、爆款检索整合到一个实时看板，外部数据由后台爬虫自动同步。

## Highlights

- **Browser-queued crawler architecture.** XHS blocks non-China IPs and HTTPS→HTTP image hotlinking; the frontend can never call XHS directly. Solution: the frontend writes `fetch_status='pending'` rows to Supabase, a local macOS service (Playwright + [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler), running on a Mac in China with a logged-in session) polls every 5 seconds and writes results back. Supabase Realtime streams completions to every connected browser within milliseconds.
- **AI search over the team's viral-post collection.** FastAPI service (`crawler/ai_api.py`) indexes saved posts with Voyage embeddings, serves hybrid (vector + keyword) retrieval, and uses GPT-4.1-mini for the synthesis layer. An optional external-discovery loop turns a sparse internal match into a crawl job: "go find references on XHS," human-review, then ingest.
- **Image rehosting that survives hotlink protection.** Every XHS image is downloaded by the crawler with a spoofed `Referer`, re-uploaded to Supabase Storage, and the public HTTPS URL is written back to the row. No broken images, no HTTPS/HTTP mixed-content.
- **Daily history snapshots.** Two history tables (`account_stats_history`, `benchmark_stats_history`) with `unique(entity_id, date)` constraints, written via upsert by a 12-hour APScheduler job. Idempotent and naturally one-row-per-day.
- **Mobile-first responsive without a CSS framework.** All breakpoint logic routes through a single `useIsMobile()` hook (768px). Modals snap-bottom on mobile, center on desktop. Drawers slide from right (desktop) or bottom (mobile, 92dvh + safe-area). Zero media queries.

## Tech stack

| Layer | Choice |
|-------|--------|
| Frontend | React 18, Vite 5, Recharts, Lucide icons — no router, no CSS framework, no TypeScript (~4k lines of plain JSX, deliberately approachable) |
| Backend (data) | Supabase: Postgres + Storage + Realtime. Single permissive RLS policy — used as both source of truth and job queue. |
| Crawler | Python 3.11, MediaCrawler, Playwright (persistent context for cookie reuse), APScheduler, httpx |
| AI layer | FastAPI, Voyage AI (`voyage-3-lite`) embeddings, OpenAI GPT-4.1-mini for synthesis, pgvector via Supabase |
| Infra | Vercel (zero-config CI from GitHub) for the frontend; macOS LaunchAgent for the crawler (auto-start, crash recovery, throttled restart) |

## Architecture

```
       ┌───────────────────────────────────────────────────┐
       │           Vercel  ·  React + Vite                 │
       │   inline styles · Recharts · Supabase JS client   │
       └────────────┬──────────────────────────────┬───────┘
                    │ read / write / Realtime sub  │ /ai/* (search, research)
                    ▼                              ▼
       ┌───────────────────────────────┐   ┌────────────────────────┐
       │          Supabase             │   │   FastAPI (local)      │
       │  Postgres + Storage + pgvec   │◄──┤   ai_api.py            │
       │  Tables: posts, accounts,     │   │   Voyage embeddings    │
       │    members, viral_posts,      │   │   Hybrid retrieval     │
       │    benchmark_accounts,        │   │   GPT-4.1-mini synth   │
       │    *_stats_history, ...       │   └────────────────────────┘
       │  Bucket: post-images          │
       └──────────────┬────────────────┘
                      │ poll every 5s for pending jobs
                      ▼
       ┌───────────────────────────────┐
       │   macOS LaunchAgent           │
       │   crawler/server.py           │
       │   MediaCrawler + Playwright   │
       │   • 5s poll: pending → crawl  │
       │   • 12h full-sync (APSched)   │
       │   • rehost images to Storage  │
       └───────────────────────────────┘
```

The frontend never talks to XHS directly. Tasks flow: user enters a link → row written with `fetch_status='pending'` → crawler picks it up within 5s → Supabase Realtime pushes the result back to every connected client.

## Engineering challenges worth calling out

1. **Bypassing XHS's geo-restricted API.** Direct calls from non-China IPs and from HTTPS pages are blocked. The Supabase-backed job queue moves all XHS traffic onto an authenticated local machine — no CORS, no IP blocks, no session tokens shipped to the client.
2. **Hotlink protection breaking every image.** XHS CDN enforces a `Referer` check and serves HTTP only. Fix: crawler downloads with a spoofed `Referer`, re-uploads to Supabase Storage, writes the public HTTPS URL back. Every image rendered in the app is on our own bucket.
3. **Incomplete feed payloads.** XHS's creator-feed endpoint returns summary data only — no captions, tags, or comment counts. Mitigation: after fetching the feed, call `get_note_by_id` per post to fill in missing fields. 10 extra requests per benchmark account, but the detail drawer is actually useful.
4. **`xsec_token` + Chinese number parsing.** XHS requests need a short-lived `xsec_token` from the share URL (creator IDs alone fail), and follower counts come back as `"1.2万"` / `"10万+"`. `parser.py` normalizes both; config requires full share URLs, not bare IDs.
5. **Trend charts from a stateless DB.** Supabase only stores current values. Two history tables with `unique(entity_id, date)` and idempotent 12h upserts give per-day rows without dedupe logic on the client.
6. **AI retrieval that knows when it doesn't know.** Hybrid retrieval scores results against a similarity floor (`AI_RESEARCH_MIN_SIMILARITY = 0.55`) and a result-count floor. Below the floor, the UI offers `去小红书找参考` ("look on XHS") which kicks off a discovery crawl job — human-reviewed before ingestion.

## Project structure / 目录结构

```
src/
  App.jsx                  # layout, nav, global accounts/members state
  aiApi.js                 # client wrapper for FastAPI /ai/* endpoints
  supabase.js              # Supabase client singleton
  components/
    AccountsPage.jsx       # account grid + detail + trend line
    ContentManager.jsx     # 3:4 post cards, kanban, multi-image upload
    CalendarPage.jsx       # monthly grid of scheduled posts
    MaterialPage.jsx       # 4-tab library: viral / benchmark / topics / titles
    AnalyticsPage.jsx      # follower trends, rankings, country breakdown
    AISearchPage.jsx       # AI search center (retrieval + research)
    PostDetailDrawer.jsx   # internal post detail
    ViralPostDrawer.jsx    # viral / benchmark detail (image carousel)
    shared.jsx             # useIsMobile, Avatar, Badge, STATUS, fmt()

crawler/
  server.py                # long-running: 5s poll + 12h APScheduler
  ai_api.py                # FastAPI: /ai/search-viral, /ai/research, ...
  knowledge_indexer.py     # background embedding worker
  retrieval_pipeline.py    # hybrid retrieval (vector + lexical)
  research_service.py      # GPT synthesis over retrieved context
  discovery_service.py     # external-discovery job lifecycle
  xhs_discovery.py         # XHS-side search + benchmark selection
  parser.py                # parse_count() for "1.2万" style strings
  com.xhs.dashboard.crawler.plist  # LaunchAgent definition
  setup_autostart.sh       # one-shot installer
  config.example.py        # template — copy to config.py and fill in

schema.sql                 # core tables
analytics_schema.sql       # history snapshot tables
crawler/schema.sql         # crawler-side tables (jobs, crawl logs)
crawler/ai_schema.sql      # AI tables (embeddings, research traces, discovery)
```

## Quick start / 快速开始

**Prerequisites.** Node 18+, Python 3.11+, a working [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout with a logged-in XHS session, a Supabase project. Optional: Voyage AI + OpenAI keys for the AI layer.

```bash
# 1. Frontend / 前端
npm install
cp .env.example .env                   # fill VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
npm run dev                            # http://localhost:5173

# 2. Database / 数据库 — paste into Supabase SQL Editor in order
#    schema.sql · analytics_schema.sql · crawler/schema.sql
#    (optional) crawler/ai_schema.sql for the AI layer

# 3. Crawler / 爬虫服务
cd crawler
cp config.example.py config.py         # fill SUPABASE_URL, SUPABASE_KEY, ACCOUNT_MAP
pip install -r requirements.txt
./setup_autostart.sh                   # installs macOS LaunchAgent
tail -f logs/server.log                # look for "XHS 客户端初始化成功"

# 4. AI API (optional) / AI 服务（可选）
python ai_api.py                       # FastAPI on 127.0.0.1:8001
```

`MEDIACRAWLER_DIR=/custom/path ./setup_autostart.sh` if MediaCrawler isn't at `~/MediaCrawler`. The frontend reaches the AI service via `VITE_AI_API_URL` / `VITE_AI_API_KEY` (shared local token — not a real auth layer, fine for a 4-8 person internal tool).

## Design choices, honestly / 设计取舍

- **No auth layer.** Known small team, shared internal tool — login is friction with no upside. Would not ship this way for anything public.
- **No router, no CSS framework, no TypeScript.** Deliberate: keeps ~4k lines of JSX approachable for non-frontend-leaning contributors. Trade-off accepted.
- **UUID-first upload.** `crypto.randomUUID()` generates post IDs client-side so images can land in `post-images/{post_id}/` before the row exists. Avoids the row-vs-storage ordering problem.
- **JSONB for nested data.** `benchmark_accounts.recent_posts` is a JSONB array — adding fields (caption, tags, images) never required a migration.
- **`getWeekly()` is currently pseudo-random.** Placeholder visualization on cards where a real 7-day series isn't yet wired up; the history tables back the real charts on the analytics page. Will be replaced — flagged here for honesty.

## Status / Roadmap

- Working: full CRUD on posts/accounts/members; multi-image upload; calendar; viral & benchmark library; analytics charts; image rehosting; auto-restart crawler; AI search over saved viral posts.
- Active: external-discovery loop (gated behind `EXTERNAL_DISCOVERY_ENABLED`, defaults to `ask_first` for human review).
- Planned: replace `getWeekly()` placeholder with real per-card 7-day series; broader test coverage on the retrieval pipeline; lightweight role-based access if the team scales past ~10.

## License

No license file. Personal/portfolio project — please open an issue if you want to reuse code.

未配置 license，个人项目代码，复用请先开 issue 讨论。
