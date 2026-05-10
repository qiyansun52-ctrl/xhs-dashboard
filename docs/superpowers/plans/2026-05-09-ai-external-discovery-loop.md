# AI External Discovery Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an external Xiaohongshu discovery loop that lets AI Search answer sparse questions with clearly labeled pending external candidates, then lets humans approve useful candidates into `viral_posts` and `knowledge_items`.

**Architecture:** Keep internal knowledge and external pending candidates separate. `/ai/research` returns the immediate internal answer plus discovery metadata; a separate discovery job queue drives crawler work; review endpoints move approved candidates into the formal material library and index. The crawler uses a keyword search adapter plus benchmark-account expansion, with centralized scoring and dedupe.

**Tech Stack:** React 18 + Vite, inline styles, Supabase Postgres/Storage/RLS/Realtime, FastAPI + Pydantic, Python `unittest`, MediaCrawler/XHS client, Voyage embeddings through the existing `ai_api.py` worker path.

---

## References Checked

- Supabase RLS docs: `https://supabase.com/docs/guides/database/postgres/row-level-security`
- Supabase Storage access control docs: `https://supabase.com/docs/guides/storage/security/access-control`
- Supabase Vector indexes docs: `https://supabase.com/docs/guides/ai/vector-indexes`
- Supabase changelog: `https://supabase.com/changelog.md`

Notes for implementation:

- Enable RLS on new public tables and add the existing internal `team_access` policy.
- Keep approval writes idempotent because PostgREST read retries do not make write operations automatically safe.
- HNSW remains appropriate for existing `knowledge_items` embeddings; this feature does not add vector columns to external candidates.

## File Structure

| File | Responsibility |
| --- | --- |
| `crawler/ai_schema.sql` | Append external discovery tables, indexes, RLS policies, and helper uniqueness indexes |
| `crawler/config.example.py` | Add feature flag, trigger mode, crawler limits, and scoring defaults |
| `crawler/discovery.py` | Pure helpers for query generation, dedupe keys, candidate scoring, and citation validation |
| `crawler/test_discovery.py` | Unit tests for discovery helpers |
| `crawler/research_models.py` | Extend research response model with discovery metadata and external supplement models |
| `crawler/research_service.py` | Add sparse-response discovery metadata and external supplement generation |
| `crawler/discovery_service.py` | Job creation/listing, candidate review, approval ingestion, and knowledge indexing orchestration |
| `crawler/xhs_discovery.py` | XHS keyword search adapter and benchmark expansion helpers |
| `crawler/server.py` | Poll `external_discovery_jobs`, run discovery, and write candidates |
| `crawler/ai_api.py` | Register discovery job, supplement, approval, ignore, and reject endpoints |
| `src/aiApi.js` | Browser client functions for discovery endpoints |
| `src/components/AISearchPage.jsx` | Discovery offer, job progress, candidate cards, supplemental answer, and review actions |
| `README.md` | Document feature flags, SQL setup, and manual validation flow |

## Task 1: Add Discovery Schema And Config

**Files:**
- Modify: `crawler/ai_schema.sql`
- Modify: `crawler/config.example.py`

- [ ] **Step 1: Append external discovery schema to `crawler/ai_schema.sql`**

Append this SQL after the existing `match_knowledge_items` function:

```sql

-- ===============================================================
-- AI 外部发现闭环 schema（追加）
-- 在 Supabase Dashboard -> SQL Editor 中粘贴并执行
-- ===============================================================

create table if not exists external_discovery_jobs (
  id uuid primary key default gen_random_uuid(),
  user_question text not null,
  task_type text not null check (task_type in ('material', 'experience', 'image_reference', 'mixed')),
  trigger_reason text not null check (trigger_reason in ('sparse_recall', 'zero_recall', 'user_requested')),
  internal_answer_payload jsonb not null default '{}'::jsonb,
  search_queries text[] not null default '{}',
  benchmark_account_ids uuid[] not null default '{}',
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed', 'cancelled')),
  error_message text,
  created_by_member_id uuid references members(id) on delete set null,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_external_discovery_jobs_status
  on external_discovery_jobs(status, created_at);

create index if not exists idx_external_discovery_jobs_created_at
  on external_discovery_jobs(created_at desc);

alter table external_discovery_jobs enable row level security;
create policy "team_access" on external_discovery_jobs for all using (true) with check (true);

create table if not exists external_discovery_candidates (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references external_discovery_jobs(id) on delete cascade,
  source_path text not null check (source_path in ('keyword_search', 'benchmark_expansion')),
  search_query text,
  benchmark_account_id uuid references benchmark_accounts(id) on delete set null,
  xhs_note_id text,
  url text not null,
  title text not null default '',
  caption text not null default '',
  cover_image text,
  images text[] not null default '{}',
  tags text[] not null default '{}',
  author_name text,
  likes integer default 0,
  saves integer default 0,
  comments integer default 0,
  views integer default 0,
  candidate_score double precision not null default 0,
  ai_reason text,
  review_status text not null default 'pending' check (review_status in ('pending', 'approved', 'ignored', 'rejected')),
  review_reason text check (
    review_reason is null or review_reason in ('不相关', '低质量', '疑似广告', '重复素材', '不适合团队调性', '数据异常')
  ),
  approved_viral_post_id uuid,
  created_at timestamptz default now(),
  reviewed_at timestamptz,
  unique(job_id, url)
);

create index if not exists idx_external_discovery_candidates_job_score
  on external_discovery_candidates(job_id, candidate_score desc);

create index if not exists idx_external_discovery_candidates_review
  on external_discovery_candidates(review_status, created_at desc);

create index if not exists idx_external_discovery_candidates_note_id
  on external_discovery_candidates(xhs_note_id)
  where xhs_note_id is not null;

alter table external_discovery_candidates enable row level security;
create policy "team_access" on external_discovery_candidates for all using (true) with check (true);

alter table ai_research_notes
  add column if not exists external_candidate_references jsonb not null default '[]'::jsonb;

alter table viral_posts
  add column if not exists discovery_candidate_id uuid references external_discovery_candidates(id) on delete set null;

alter table viral_posts
  add column if not exists source_origin text not null default 'manual'
  check (source_origin in ('manual', 'crawler', 'ai_external_discovery'));

create index if not exists idx_viral_posts_discovery_candidate
  on viral_posts(discovery_candidate_id)
  where discovery_candidate_id is not null;
```

- [ ] **Step 2: Add config defaults to `crawler/config.example.py`**

Append this section to the end of the file:

```python

# ── AI 外部发现闭环 ─────────────────────────────────────────────
# 默认关闭。确认 schema、AI API、爬虫搜索能力都可用后再打开。
EXTERNAL_DISCOVERY_ENABLED = False

# ask_first: AI 先给内部回答，用户点击后才创建发现任务。
# auto_after_sparse: 内部匹配不足时自动创建发现任务，但候选仍需人工审核才能入库。
EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"

# 每个发现任务的爬取上限。先保守，避免影响小红书登录态和风控。
EXTERNAL_DISCOVERY_MAX_QUERIES = 4
EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS = 20
EXTERNAL_DISCOVERY_MAX_BENCHMARK_ACCOUNTS = 3
EXTERNAL_DISCOVERY_MAX_POSTS_PER_BENCHMARK = 10
EXTERNAL_DISCOVERY_MAX_CANDIDATES = 30
EXTERNAL_DISCOVERY_REQUEST_DELAY_SECONDS = 2

# 24 小时内相似搜索复用已有 job，减少重复爬取。
EXTERNAL_DISCOVERY_REUSE_WINDOW_HOURS = 24
```

- [ ] **Step 3: Run SQL review and syntax checks**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git diff --check -- crawler/ai_schema.sql crawler/config.example.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Apply schema in Supabase**

Open Supabase SQL Editor and run the full `crawler/ai_schema.sql`.

Expected checks in SQL Editor:

```sql
select to_regclass('public.external_discovery_jobs') as jobs_table;
select to_regclass('public.external_discovery_candidates') as candidates_table;
select column_name from information_schema.columns
where table_name = 'viral_posts'
  and column_name in ('discovery_candidate_id', 'source_origin');
```

Expected: both table names are non-null, and both `viral_posts` columns are listed.

- [ ] **Step 5: Commit schema and config**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/ai_schema.sql crawler/config.example.py
git commit -m "feat(ai): add external discovery schema"
```

## Task 2: Add Discovery Helper Tests And Pure Helpers

**Files:**
- Create: `crawler/test_discovery.py`
- Create: `crawler/discovery.py`

- [ ] **Step 1: Create failing helper tests**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/test_discovery.py`:

```python
import unittest

from discovery import (
    build_candidate_url,
    candidate_dedupe_key,
    derive_search_queries,
    normalize_question,
    score_candidate,
    validate_external_candidate_ids,
)


class DiscoveryHelperTests(unittest.TestCase):
    def test_normalize_question_removes_extra_spaces_and_punctuation(self):
        self.assertEqual(
            normalize_question("  英国留学， 申请焦虑！！ "),
            "英国留学 申请焦虑",
        )

    def test_derive_search_queries_keeps_short_chinese_queries(self):
        queries = derive_search_queries(
            question="英国申请焦虑方向有什么爆款素材？",
            image_keywords=[],
            weak_titles=["英国文书怎么准备"],
            max_queries=4,
        )
        self.assertLessEqual(len(queries), 4)
        self.assertIn("英国留学 申请焦虑", queries)
        self.assertTrue(all(len(query) <= 24 for query in queries))

    def test_score_candidate_weights_saves_more_than_likes(self):
        low_save = {"likes": 10000, "saves": 50, "comments": 10, "views": 50000}
        high_save = {"likes": 2000, "saves": 1200, "comments": 10, "views": 8000}
        self.assertGreater(
            score_candidate(high_save, relevance_score=0.6, source_path="keyword_search"),
            score_candidate(low_save, relevance_score=0.6, source_path="keyword_search"),
        )

    def test_benchmark_expansion_gets_small_boost(self):
        row = {"likes": 1000, "saves": 300, "comments": 50, "views": 10000}
        self.assertGreater(
            score_candidate(row, relevance_score=0.5, source_path="benchmark_expansion"),
            score_candidate(row, relevance_score=0.5, source_path="keyword_search"),
        )

    def test_candidate_dedupe_prefers_note_id(self):
        row = {"xhs_note_id": "note-1", "url": "https://example.com/a"}
        self.assertEqual(candidate_dedupe_key(row), "note:note-1")

    def test_candidate_dedupe_falls_back_to_url(self):
        row = {"xhs_note_id": "", "url": "https://example.com/a?x=1"}
        self.assertEqual(candidate_dedupe_key(row), "url:https://example.com/a?x=1")

    def test_build_candidate_url_uses_note_id(self):
        self.assertEqual(
            build_candidate_url("abc123", fallback_url=""),
            "https://www.xiaohongshu.com/explore/abc123",
        )

    def test_validate_external_candidate_ids_removes_fabricated_ids(self):
        payload = {
            "recommendations": [
                {"text": "参考焦虑共鸣开头", "candidate_ids": ["c1", "fake"]},
                {"text": "没有候选支持", "candidate_ids": ["fake"]},
            ],
            "general_advice": [],
        }
        cleaned = validate_external_candidate_ids(payload, allowed_candidate_ids={"c1"})
        self.assertEqual(cleaned["recommendations"][0]["candidate_ids"], ["c1"])
        self.assertEqual(len(cleaned["recommendations"]), 1)
        self.assertEqual(cleaned["general_advice"][0]["text"], "没有候选支持")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m unittest test_discovery.py
```

Expected: `ModuleNotFoundError: No module named 'discovery'`.

- [ ] **Step 3: Create `crawler/discovery.py`**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/discovery.py`:

```python
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Sequence, Set


COUNTRY_HINTS = ("英国", "美国", "澳洲", "澳大利亚", "加拿大", "香港", "新加坡")
CONTENT_HINTS = ("申请", "文书", "选校", "签证", "雅思", "托福", "offer", "留学", "焦虑")
MOOD_HINTS = ("焦虑", "崩溃", "后悔", "避坑", "真实", "省钱", "经验", "攻略")


def normalize_question(question: str) -> str:
    text = (question or "").strip()
    text = re.sub(r"[，。！？、,.!?]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_any(text: str, values: Sequence[str]) -> List[str]:
    return [value for value in values if value in text]


def derive_search_queries(
    question: str,
    image_keywords: Sequence[str] | None = None,
    weak_titles: Sequence[str] | None = None,
    max_queries: int = 4,
) -> List[str]:
    text = normalize_question(" ".join([
        question or "",
        " ".join(image_keywords or []),
        " ".join(weak_titles or []),
    ]))
    countries = _contains_any(text, COUNTRY_HINTS)
    content = _contains_any(text, CONTENT_HINTS)
    moods = _contains_any(text, MOOD_HINTS)

    country = countries[0] if countries else "留学"
    if country == "澳大利亚":
        country = "澳洲"
    topic = content[0] if content else "申请"
    mood = moods[0] if moods else "经验"

    candidates = [
        f"{country}留学 {topic}{mood}" if country != "留学" else f"留学 {topic}{mood}",
        f"{country}申请 {topic}" if country != "留学" else f"留学申请 {topic}",
        f"{country}留学 {mood}" if country != "留学" else f"留学 {mood}",
        f"{topic} {mood} 小红书",
    ]

    cleaned: List[str] = []
    seen: Set[str] = set()
    for query in candidates:
        query = normalize_question(query)
        if not query or query in seen:
            continue
        seen.add(query)
        cleaned.append(query[:24])
        if len(cleaned) >= max_queries:
            break
    return cleaned


def _log_norm(value: Any) -> float:
    try:
        number = max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        number = 0.0
    return math.log1p(number) / math.log1p(100000)


def score_candidate(row: Dict[str, Any], relevance_score: float = 0.5, source_path: str = "keyword_search") -> float:
    trust_boost = 1.0 if source_path == "benchmark_expansion" else 0.0
    score = (
        max(min(float(relevance_score), 1.0), 0.0) * 0.45
        + _log_norm(row.get("saves")) * 0.25
        + _log_norm(row.get("comments")) * 0.12
        + _log_norm(row.get("likes")) * 0.10
        + trust_boost * 0.05
        + _log_norm(row.get("views")) * 0.03
    )
    return round(score, 6)


def candidate_dedupe_key(row: Dict[str, Any]) -> str:
    note_id = str(row.get("xhs_note_id") or row.get("note_id") or "").strip()
    if note_id:
        return f"note:{note_id}"
    return f"url:{str(row.get('url') or '').strip()}"


def build_candidate_url(note_id: str | None, fallback_url: str | None = None) -> str:
    if note_id:
        return f"https://www.xiaohongshu.com/explore/{note_id}"
    return fallback_url or ""


def validate_external_candidate_ids(answer: dict, allowed_candidate_ids: Iterable[str]) -> dict:
    allowed = {str(item_id) for item_id in allowed_candidate_ids}
    cleaned = dict(answer)
    valid_recommendations = []
    general_advice = list(cleaned.get("general_advice") or [])

    for recommendation in cleaned.get("recommendations") or []:
        candidate_ids = [
            str(candidate_id)
            for candidate_id in recommendation.get("candidate_ids", [])
            if str(candidate_id) in allowed
        ]
        if candidate_ids:
            updated = dict(recommendation)
            updated["candidate_ids"] = candidate_ids
            valid_recommendations.append(updated)
        else:
            general_advice.append({
                "text": recommendation.get("text", ""),
                "reason": "external candidate validation removed unsupported candidate ids",
            })

    cleaned["recommendations"] = valid_recommendations
    cleaned["general_advice"] = general_advice
    cleaned["candidate_references"] = [
        candidate_id
        for candidate_id in cleaned.get("candidate_references", [])
        if str(candidate_id) in allowed
    ]
    return cleaned
```

- [ ] **Step 4: Run discovery helper tests**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m unittest test_discovery.py
```

Expected: `OK`.

- [ ] **Step 5: Commit helper tests and implementation**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/discovery.py crawler/test_discovery.py
git commit -m "feat(ai): add discovery helper logic"
```

## Task 3: Extend Research Response With Discovery Metadata

**Files:**
- Modify: `crawler/research_models.py`
- Modify: `crawler/research_service.py`
- Modify: `crawler/config.example.py`
- Test: `crawler/test_discovery.py`

- [ ] **Step 1: Add model fields to `crawler/research_models.py`**

Update `ResearchAnswer` with the following fields:

```python
    can_external_discover: bool = False
    discovery_trigger_reason: Optional[str] = None
    suggested_search_queries: List[str] = Field(default_factory=list)
    discovery_trigger_mode: str = "ask_first"
    discovery_job_id: Optional[str] = None
```

- [ ] **Step 2: Add config fallback imports in `crawler/research_service.py`**

Extend the existing config import block:

```python
        EXTERNAL_DISCOVERY_ENABLED,
        EXTERNAL_DISCOVERY_TRIGGER_MODE,
        EXTERNAL_DISCOVERY_MAX_QUERIES,
```

Extend the fallback values in the `except Exception` block:

```python
    EXTERNAL_DISCOVERY_ENABLED = False
    EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"
    EXTERNAL_DISCOVERY_MAX_QUERIES = 4
```

Add this import near existing retrieval imports:

```python
from discovery import derive_search_queries
```

- [ ] **Step 3: Return discovery metadata from sparse research results**

In `ResearchService.research`, after `sparse` is computed and before returning `ResearchAnswer`, build weak titles and suggested queries:

```python
        weak_titles = [
            str(row.get("title") or "")
            for row in retrieved_rows[:5]
            if row.get("title")
        ]
        suggested_search_queries = derive_search_queries(
            req.question,
            image_keywords=image_analysis.keywords if image_analysis else [],
            weak_titles=weak_titles,
            max_queries=EXTERNAL_DISCOVERY_MAX_QUERIES,
        ) if sparse and EXTERNAL_DISCOVERY_ENABLED else []
        discovery_trigger_reason = "zero_recall" if sparse and not retrieved_rows else "sparse_recall"
```

Add these arguments to the `ResearchAnswer(...)` call:

```python
            can_external_discover=bool(sparse and EXTERNAL_DISCOVERY_ENABLED),
            discovery_trigger_reason=discovery_trigger_reason if sparse and EXTERNAL_DISCOVERY_ENABLED else None,
            suggested_search_queries=suggested_search_queries,
            discovery_trigger_mode=EXTERNAL_DISCOVERY_TRIGGER_MODE,
            discovery_job_id=None,
```

- [ ] **Step 4: Add a focused test for query derivation**

Append this test to `crawler/test_discovery.py`:

```python
    def test_query_derivation_uses_image_keywords(self):
        queries = derive_search_queries(
            question="帮我找相似参考",
            image_keywords=["英国", "申请", "焦虑"],
            weak_titles=[],
            max_queries=3,
        )
        self.assertTrue(any("英国" in query for query in queries))
        self.assertTrue(any("申请" in query for query in queries))
```

- [ ] **Step 5: Run model and helper checks**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m unittest test_discovery.py test_retrieval.py test_knowledge_indexer.py
python3 -m py_compile research_models.py research_service.py discovery.py
```

Expected: tests pass and compile has no output.

- [ ] **Step 6: Commit research metadata changes**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/research_models.py crawler/research_service.py crawler/config.example.py crawler/test_discovery.py
git commit -m "feat(ai): expose discovery metadata on sparse answers"
```

## Task 4: Add Discovery Job Service And API Endpoints

**Files:**
- Create: `crawler/discovery_service.py`
- Modify: `crawler/ai_api.py`
- Test: `crawler/test_discovery.py`

- [ ] **Step 1: Create discovery service**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/discovery_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from discovery import derive_search_queries


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryService:
    def __init__(self, supabase_client, max_queries: int = 4):
        self.sb = supabase_client
        self.max_queries = max_queries

    def create_job(
        self,
        user_question: str,
        task_type: str,
        trigger_reason: str,
        internal_answer_payload: Dict[str, Any],
        search_queries: Optional[List[str]] = None,
        benchmark_account_ids: Optional[List[str]] = None,
        created_by_member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        queries = search_queries or derive_search_queries(user_question, max_queries=self.max_queries)
        payload = {
            "user_question": user_question,
            "task_type": task_type,
            "trigger_reason": trigger_reason,
            "internal_answer_payload": internal_answer_payload or {},
            "search_queries": queries[:self.max_queries],
            "benchmark_account_ids": benchmark_account_ids or [],
            "status": "pending",
            "created_by_member_id": created_by_member_id,
        }
        res = self.sb.table("external_discovery_jobs").insert([payload]).execute()
        rows = res.data or []
        return rows[0] if rows else payload

    def get_job_with_candidates(self, job_id: str) -> Dict[str, Any]:
        job_res = (
            self.sb.table("external_discovery_jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
        candidate_res = (
            self.sb.table("external_discovery_candidates")
            .select("*")
            .eq("job_id", job_id)
            .order("candidate_score", desc=True)
            .execute()
        )
        return {
            "job": job_res.data,
            "candidates": candidate_res.data or [],
        }

    def mark_candidate_review(self, candidate_id: str, review_status: str, review_reason: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "review_status": review_status,
            "review_reason": review_reason,
            "reviewed_at": now_iso(),
        }
        res = (
            self.sb.table("external_discovery_candidates")
            .update(payload)
            .eq("id", candidate_id)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else payload
```

- [ ] **Step 2: Add Pydantic request models to `crawler/ai_api.py`**

Add this import:

```python
from discovery_service import DiscoveryService
```

Create the service after `research_service = ResearchService(...)`:

```python
discovery_service = DiscoveryService(sb, max_queries=getattr(app_config, "EXTERNAL_DISCOVERY_MAX_QUERIES", 4))
```

Add these models before endpoint definitions:

```python
class CreateDiscoveryJobReq(BaseModel):
    user_question: str = Field(..., min_length=1, max_length=1000)
    task_type: str = Field(default="mixed")
    trigger_reason: str = Field(default="user_requested")
    internal_answer_payload: Dict[str, Any] = Field(default_factory=dict)
    search_queries: List[str] = Field(default_factory=list)
    benchmark_account_ids: List[str] = Field(default_factory=list)
    created_by_member_id: Optional[str] = None


class ReviewCandidateReq(BaseModel):
    reason: Optional[str] = None
```

- [ ] **Step 3: Add job create/list and ignore/reject endpoints**

Add these endpoints before the `if __name__ == "__main__"` block:

```python
@app.post("/ai/discovery-jobs", dependencies=[Depends(require_api_key)])
async def create_discovery_job(req: CreateDiscoveryJobReq):
    enabled = getattr(app_config, "EXTERNAL_DISCOVERY_ENABLED", False)
    if not enabled:
        raise HTTPException(400, "外部发现功能尚未开启")
    try:
        job = discovery_service.create_job(
            user_question=req.user_question,
            task_type=req.task_type,
            trigger_reason=req.trigger_reason,
            internal_answer_payload=req.internal_answer_payload,
            search_queries=req.search_queries,
            benchmark_account_ids=req.benchmark_account_ids,
            created_by_member_id=req.created_by_member_id,
        )
        return {"ok": True, "job": job}
    except Exception as e:
        log.error(f"创建外部发现任务失败: {e}")
        raise HTTPException(500, "创建外部发现任务失败，请稍后重试。")


@app.get("/ai/discovery-jobs/{job_id}", dependencies=[Depends(require_api_key)])
async def get_discovery_job(job_id: str):
    try:
        return discovery_service.get_job_with_candidates(job_id)
    except Exception as e:
        log.error(f"读取外部发现任务失败: {e}")
        raise HTTPException(500, "读取外部发现任务失败，请稍后重试。")


@app.post("/ai/discovery-candidates/{candidate_id}/ignore", dependencies=[Depends(require_api_key)])
async def ignore_discovery_candidate(candidate_id: str):
    try:
        candidate = discovery_service.mark_candidate_review(candidate_id, "ignored")
        return {"ok": True, "candidate": candidate}
    except Exception as e:
        log.error(f"忽略候选素材失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")


@app.post("/ai/discovery-candidates/{candidate_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_discovery_candidate(candidate_id: str, req: ReviewCandidateReq):
    try:
        candidate = discovery_service.mark_candidate_review(candidate_id, "rejected", req.reason or "不相关")
        return {"ok": True, "candidate": candidate}
    except Exception as e:
        log.error(f"拒绝候选素材失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")
```

- [ ] **Step 4: Run compile check**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m py_compile ai_api.py discovery_service.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit job API**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/ai_api.py crawler/discovery_service.py
git commit -m "feat(ai): add external discovery job API"
```

## Task 5: Add Frontend Discovery Job Flow

**Files:**
- Modify: `src/aiApi.js`
- Modify: `src/components/AISearchPage.jsx`

- [ ] **Step 1: Add discovery client functions to `src/aiApi.js`**

Append:

```javascript
export async function createDiscoveryJob(payload) {
  return postJson("/ai/discovery-jobs", payload);
}

export async function getDiscoveryJob(jobId) {
  if (!BASE_URL || !API_KEY) {
    throw new Error("AI API 未配置，请检查 .env 中的 VITE_AI_API_URL 和 VITE_AI_API_KEY");
  }

  const resp = await fetch(`${BASE_URL}/ai/discovery-jobs/${jobId}`, {
    method: "GET",
    headers: { "X-API-Key": API_KEY },
  });

  if (!resp.ok) {
    let message = "";
    try {
      const data = await resp.json();
      message = data?.detail || data?.message || "";
    } catch {
      message = await resp.text().catch(() => "");
    }
    throw new Error(message || "读取外部发现任务失败，请稍后重试。");
  }

  return resp.json();
}

export async function ignoreDiscoveryCandidate(candidateId) {
  return postJson(`/ai/discovery-candidates/${candidateId}/ignore`, {});
}

export async function rejectDiscoveryCandidate(candidateId, reason = "不相关") {
  return postJson(`/ai/discovery-candidates/${candidateId}/reject`, { reason });
}
```

- [ ] **Step 2: Import client functions in `AISearchPage.jsx`**

Change the import from `../aiApi.js` to:

```javascript
import {
  createDiscoveryJob,
  getDiscoveryJob,
  ignoreDiscoveryCandidate,
  rejectDiscoveryCandidate,
  research,
  saveResearchNote,
} from "../aiApi.js";
```

- [ ] **Step 3: Add discovery state to `AISearchPage`**

Add state near existing `answer` and `loading` state:

```javascript
  const [discoveryJob, setDiscoveryJob] = useState(null);
  const [discoveryCandidates, setDiscoveryCandidates] = useState([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
```

- [ ] **Step 4: Add job creation and refresh handlers**

Add these functions inside `AISearchPage`:

```javascript
  const refreshDiscoveryJob = async (jobId) => {
    const payload = await getDiscoveryJob(jobId);
    setDiscoveryJob(payload.job);
    setDiscoveryCandidates(payload.candidates || []);
    return payload.job;
  };

  const handleCreateDiscovery = async () => {
    if (!answer) return;

    setDiscoveryLoading(true);
    setDiscoveryError("");
    try {
      const { job } = await createDiscoveryJob({
        user_question: answer.question,
        task_type: answer.task_type || "mixed",
        trigger_reason: answer.discovery_trigger_reason || "user_requested",
        internal_answer_payload: answer,
        search_queries: answer.suggested_search_queries || [],
        benchmark_account_ids: [],
      });
      setDiscoveryJob(job);
      setDiscoveryCandidates([]);
    } catch (err) {
      setDiscoveryError(err.message || "创建外部发现任务失败，请稍后重试。");
    } finally {
      setDiscoveryLoading(false);
    }
  };

  const handleCandidateReview = async (candidate, action) => {
    try {
      const resp = action === "ignore"
        ? await ignoreDiscoveryCandidate(candidate.id)
        : await rejectDiscoveryCandidate(candidate.id, "不相关");
      const updated = resp.candidate;
      setDiscoveryCandidates(prev => prev.map(item => item.id === candidate.id ? { ...item, ...updated } : item));
    } catch (err) {
      alert(err.message || "操作失败，请稍后重试。");
    }
  };
```

- [ ] **Step 5: Add polling effect for running jobs**

Change the React import to include `useEffect`:

```javascript
import { useEffect, useState } from "react";
```

Add this effect inside `AISearchPage`:

```javascript
  useEffect(() => {
    if (!discoveryJob?.id || !["pending", "running"].includes(discoveryJob.status)) return;

    const timer = window.setInterval(() => {
      refreshDiscoveryJob(discoveryJob.id).catch(err => {
        setDiscoveryError(err.message || "刷新外部发现任务失败");
      });
    }, 5000);

    return () => window.clearInterval(timer);
  }, [discoveryJob?.id, discoveryJob?.status]);
```

- [ ] **Step 6: Add simple discovery UI components**

Add these components above `AISearchPage`:

```javascript
function DiscoveryCandidateCard({ candidate, onReview }) {
  const disabled = candidate.review_status !== "pending";
  return (
    <div style={{ background: "#111", border: "1px solid #2a2a2a", borderRadius: 10, padding: 12 }}>
      <div style={{ display: "flex", gap: 12 }}>
        {candidate.cover_image && (
          <img src={candidate.cover_image} alt="" style={{ width: 72, height: 96, objectFit: "cover", borderRadius: 8, background: "#1a1a1a" }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "#FF9F43", marginBottom: 6 }}>待审核外部素材</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0", lineHeight: 1.4 }}>{candidate.title || "无标题"}</div>
          <div style={{ fontSize: 12, color: "#666", lineHeight: 1.6, marginTop: 6, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
            {candidate.caption || candidate.ai_reason || "暂无摘要"}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8, fontSize: 11, color: "#555" }}>
            <span>赞 {candidate.likes || 0}</span>
            <span>藏 {candidate.saves || 0}</span>
            <span>评 {candidate.comments || 0}</span>
            <span>{candidate.source_path === "benchmark_expansion" ? "对标账号扩展" : "关键词搜索"}</span>
          </div>
          {candidate.url && (
            <a href={candidate.url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 8, fontSize: 11, color: "#54A0FF", textDecoration: "none" }}>
              打开原始链接
            </a>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
        <button disabled={disabled} onClick={() => onReview(candidate, "ignore")} style={{ padding: "7px 10px", borderRadius: 7, border: "1px solid #2a2a2a", background: "transparent", color: disabled ? "#333" : "#666", cursor: disabled ? "not-allowed" : "pointer", fontSize: 12 }}>
          忽略
        </button>
        <button disabled={disabled} onClick={() => onReview(candidate, "reject")} style={{ padding: "7px 10px", borderRadius: 7, border: "1px solid #2a2a2a", background: "transparent", color: disabled ? "#333" : "#FF9F43", cursor: disabled ? "not-allowed" : "pointer", fontSize: 12 }}>
          不相关
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Render discovery offer and candidates**

After `<AnswerView ... />`, add:

```jsx
      {answer?.can_external_discover && !discoveryJob && (
        <div style={{ marginTop: 18, background: "#111", border: "1px solid rgba(255,159,67,0.22)", borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 13, color: "#FF9F43", marginBottom: 8 }}>内部资料匹配较少</div>
          <div style={{ fontSize: 12, color: "#777", lineHeight: 1.6, marginBottom: 12 }}>
            可以去小红书搜索相关热门内容。找到的内容会作为待审核外部素材展示，审核通过后才会进入团队知识库。
          </div>
          <button onClick={handleCreateDiscovery} disabled={discoveryLoading} style={{
            padding: "9px 14px",
            borderRadius: 8,
            border: "none",
            background: discoveryLoading ? "#333" : "#FF2442",
            color: "#fff",
            cursor: discoveryLoading ? "not-allowed" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}>
            {discoveryLoading ? "创建中…" : "去小红书找参考"}
          </button>
        </div>
      )}

      {discoveryError && (
        <div style={{ marginTop: 14, color: "#FF6B6B", fontSize: 12 }}>
          {discoveryError}
        </div>
      )}

      {discoveryJob && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 13, color: "#FF9F43", marginBottom: 10 }}>
            外部发现任务：{discoveryJob.status === "completed" ? "发现完成" : discoveryJob.status === "failed" ? "发现失败" : "正在发现"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {discoveryCandidates.length === 0
              ? <div style={{ fontSize: 12, color: "#555" }}>暂无候选素材，爬虫完成后会自动显示。</div>
              : discoveryCandidates.map(candidate => (
                <DiscoveryCandidateCard key={candidate.id} candidate={candidate} onReview={handleCandidateReview} />
              ))}
          </div>
        </div>
      )}
```

- [ ] **Step 8: Run frontend build**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: Vite build succeeds. The existing chunk-size warning is acceptable.

- [ ] **Step 9: Commit frontend manual job flow**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add src/aiApi.js src/components/AISearchPage.jsx
git commit -m "feat(ai): add discovery job UI"
```

## Task 6: Add XHS Discovery Adapter And Crawler Worker

**Files:**
- Create: `crawler/xhs_discovery.py`
- Modify: `crawler/server.py`
- Test: `crawler/test_discovery.py`

- [ ] **Step 1: Add adapter tests**

Append these tests to `crawler/test_discovery.py`:

```python
class FakeSearchClient:
    async def search_note(self, keyword, page=1, page_size=10, sort="general"):
        return {
            "items": [
                {"note_id": "n1", "display_title": keyword, "xsec_token": "token"}
            ]
        }


class XhsDiscoveryAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_adapter_uses_available_search_method(self):
        from xhs_discovery import search_keyword_notes

        rows = await search_keyword_notes(FakeSearchClient(), "英国留学", limit=5)
        self.assertEqual(rows[0]["note_id"], "n1")
        self.assertEqual(rows[0]["display_title"], "英国留学")
```

- [ ] **Step 2: Create `crawler/xhs_discovery.py`**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/xhs_discovery.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any, Dict, List


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


def _extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "notes", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("items", "notes"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return []


async def search_keyword_notes(client, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    method_names = ("search_note", "search_notes", "get_note_by_keyword")
    for method_name in method_names:
        method = getattr(client, method_name, None)
        if not method:
            continue
        try:
            payload = await _maybe_await(method(keyword=keyword, page=1, page_size=limit, sort="popularity_descending"))
        except TypeError:
            payload = await _maybe_await(method(keyword, 1, limit))
        return _extract_items(payload)[:limit]

    raise RuntimeError("当前 MediaCrawler 客户端不支持关键词搜索，请先补充 XHS 搜索适配器。")


def select_benchmark_accounts(rows: List[Dict[str, Any]], queries: List[str], max_accounts: int = 3) -> List[Dict[str, Any]]:
    query_text = " ".join(queries)

    def score(row: Dict[str, Any]) -> tuple:
        destination = row.get("destination") or ""
        content_type = row.get("content_type") or ""
        note_direction = row.get("note_direction") or ""
        match_score = sum(1 for value in (destination, content_type, note_direction) if value and value in query_text)
        return (match_score, int(row.get("followers") or 0), str(row.get("fetched_at") or ""))

    return sorted(rows, key=score, reverse=True)[:max_accounts]


async def delay_between_requests(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
```

- [ ] **Step 3: Add discovery worker helpers to `crawler/server.py`**

Add imports near existing local imports:

```python
from discovery import build_candidate_url, candidate_dedupe_key, score_candidate
from xhs_discovery import delay_between_requests, search_keyword_notes, select_benchmark_accounts
```

Add config values near other constants:

```python
EXTERNAL_DISCOVERY_ENABLED = getattr(app_config, "EXTERNAL_DISCOVERY_ENABLED", False)
EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS = getattr(app_config, "EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS", 20)
EXTERNAL_DISCOVERY_MAX_BENCHMARK_ACCOUNTS = getattr(app_config, "EXTERNAL_DISCOVERY_MAX_BENCHMARK_ACCOUNTS", 3)
EXTERNAL_DISCOVERY_MAX_POSTS_PER_BENCHMARK = getattr(app_config, "EXTERNAL_DISCOVERY_MAX_POSTS_PER_BENCHMARK", 10)
EXTERNAL_DISCOVERY_MAX_CANDIDATES = getattr(app_config, "EXTERNAL_DISCOVERY_MAX_CANDIDATES", 30)
EXTERNAL_DISCOVERY_REQUEST_DELAY_SECONDS = getattr(app_config, "EXTERNAL_DISCOVERY_REQUEST_DELAY_SECONDS", 2)
```

Add this helper after `process_topics`:

```python
async def upsert_discovery_candidate(job_id: str, source_path: str, source_meta: Dict[str, Any], post_data: Dict[str, Any]):
    url = post_data.get("url") or build_candidate_url(post_data.get("xhs_note_id"), source_meta.get("url"))
    row = {
        "job_id": job_id,
        "source_path": source_path,
        "search_query": source_meta.get("search_query"),
        "benchmark_account_id": source_meta.get("benchmark_account_id"),
        "xhs_note_id": post_data.get("xhs_note_id"),
        "url": url,
        "title": post_data.get("title") or "",
        "caption": post_data.get("caption") or "",
        "cover_image": post_data.get("cover_image"),
        "images": post_data.get("images") or [],
        "tags": post_data.get("tags") or [],
        "author_name": post_data.get("author_name"),
        "likes": post_data.get("likes") or 0,
        "saves": post_data.get("saves") or 0,
        "comments": post_data.get("comments") or 0,
        "views": post_data.get("views") or 0,
        "candidate_score": score_candidate(post_data, relevance_score=0.6, source_path=source_path),
        "ai_reason": source_meta.get("ai_reason") or "与本次问题相关的外部热门参考。",
    }
    sb.table("external_discovery_candidates").upsert(row, on_conflict="job_id,url").execute()
```

- [ ] **Step 4: Add `process_external_discovery_jobs` to `crawler/server.py`**

Add:

```python
async def process_external_discovery_jobs():
    if not EXTERNAL_DISCOVERY_ENABLED:
        return
    try:
        result = (
            sb.table("external_discovery_jobs")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .limit(1)
            .execute()
        )
        jobs = result.data or []
        if not jobs:
            return

        for job in jobs:
            job_id = job["id"]
            sb.table("external_discovery_jobs").update({
                "status": "running",
                "started_at": now_iso(),
                "error_message": None,
            }).eq("id", job_id).execute()

            candidates_seen = set()
            stored_count = 0
            try:
                for query in (job.get("search_queries") or [])[:EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS]:
                    notes = await search_keyword_notes(xhs_client, query, limit=EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS)
                    for note in notes:
                        note_id = note.get("note_id") or note.get("id")
                        xsec_token = note.get("xsec_token")
                        url = build_candidate_url(note_id, note.get("url"))
                        dedupe = candidate_dedupe_key({"xhs_note_id": note_id, "url": url})
                        if dedupe in candidates_seen:
                            continue
                        candidates_seen.add(dedupe)
                        if not url:
                            continue
                        post_data = await fetch_post_data(url if "xsec_token" in url else f"{url}?xsec_token={xsec_token}" if xsec_token else url)
                        post_data["url"] = url
                        await upsert_discovery_candidate(job_id, "keyword_search", {"search_query": query}, post_data)
                        stored_count += 1
                        await delay_between_requests(EXTERNAL_DISCOVERY_REQUEST_DELAY_SECONDS)
                        if stored_count >= EXTERNAL_DISCOVERY_MAX_CANDIDATES:
                            break
                    if stored_count >= EXTERNAL_DISCOVERY_MAX_CANDIDATES:
                        break

                benchmark_rows = (
                    sb.table("benchmark_accounts")
                    .select("*")
                    .eq("fetch_status", "done")
                    .execute()
                    .data or []
                )
                selected_accounts = select_benchmark_accounts(
                    benchmark_rows,
                    job.get("search_queries") or [],
                    max_accounts=EXTERNAL_DISCOVERY_MAX_BENCHMARK_ACCOUNTS,
                )
                for account in selected_accounts:
                    for post in (account.get("recent_posts") or [])[:EXTERNAL_DISCOVERY_MAX_POSTS_PER_BENCHMARK]:
                        note_id = post.get("note_id") or post.get("id")
                        url = build_candidate_url(note_id, post.get("url"))
                        dedupe = candidate_dedupe_key({"xhs_note_id": note_id, "url": url})
                        if dedupe in candidates_seen or not url:
                            continue
                        candidates_seen.add(dedupe)
                        post_data = dict(post)
                        post_data.update({
                            "xhs_note_id": note_id,
                            "url": url,
                            "author_name": account.get("name"),
                        })
                        await upsert_discovery_candidate(
                            job_id,
                            "benchmark_expansion",
                            {"benchmark_account_id": account["id"]},
                            post_data,
                        )
                        stored_count += 1
                        if stored_count >= EXTERNAL_DISCOVERY_MAX_CANDIDATES:
                            break
                    if stored_count >= EXTERNAL_DISCOVERY_MAX_CANDIDATES:
                        break

                sb.table("external_discovery_jobs").update({
                    "status": "completed",
                    "finished_at": now_iso(),
                }).eq("id", job_id).execute()
                log.info(f"  ✅ 外部发现任务完成: {job_id} candidates={stored_count}")
            except Exception as e:
                sb.table("external_discovery_jobs").update({
                    "status": "failed",
                    "error_message": str(e)[:500],
                    "finished_at": now_iso(),
                }).eq("id", job_id).execute()
                log.error(f"  ❌ 外部发现任务失败: {e}")
    except Exception as e:
        log.error(f"process_external_discovery_jobs 出错: {e}")
```

- [ ] **Step 5: Add worker call to `poll_loop`**

In `poll_loop`, after `await process_topics(pending_only=True)`, add:

```python
            await process_external_discovery_jobs()
```

- [ ] **Step 6: Run backend tests and compile**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m unittest test_discovery.py test_retrieval.py test_knowledge_indexer.py
python3 -m py_compile server.py xhs_discovery.py discovery.py
```

Expected: tests pass and compile has no output.

- [ ] **Step 7: Commit crawler discovery worker**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/server.py crawler/xhs_discovery.py crawler/discovery.py crawler/test_discovery.py
git commit -m "feat(crawler): process external discovery jobs"
```

## Task 7: Add External Supplemental Answer

**Files:**
- Modify: `crawler/research_models.py`
- Modify: `crawler/research_service.py`
- Modify: `crawler/ai_api.py`
- Modify: `src/aiApi.js`
- Modify: `src/components/AISearchPage.jsx`

- [ ] **Step 1: Add external supplement models**

Append to `crawler/research_models.py`:

```python
class ExternalRecommendation(BaseModel):
    text: str
    candidate_ids: List[str] = Field(default_factory=list)


class ExternalSupplementAnswer(BaseModel):
    job_id: str
    conclusion: str
    recommendations: List[ExternalRecommendation] = Field(default_factory=list)
    candidate_references: List[str] = Field(default_factory=list)
    general_advice: List[GeneralAdvice] = Field(default_factory=list)
    warning: str = "以下内容来自待审核外部素材，尚未进入团队知识库。"
```

- [ ] **Step 2: Add supplement generation method to `ResearchService`**

Add imports:

```python
from discovery import validate_external_candidate_ids
from research_models import ExternalSupplementAnswer
```

Add method inside `ResearchService`:

```python
    async def generate_external_supplement(
        self,
        job_id: str,
        question: str,
        candidates: List[Dict[str, Any]],
    ) -> ExternalSupplementAnswer:
        allowed_ids = {str(row["id"]) for row in candidates}
        if not candidates:
            return ExternalSupplementAnswer(
                job_id=job_id,
                conclusion="本次外部发现没有找到可用候选素材。",
                recommendations=[],
                candidate_references=[],
                general_advice=[],
            )

        if not self.openai:
            top = candidates[:3]
            payload = {
                "conclusion": "基于待审核外部素材，可以先参考这些热门内容的角度，但正式使用前需要人工审核。",
                "recommendations": [
                    {
                        "text": f"参考《{row.get('title') or '无标题'}》的切入角度。",
                        "candidate_ids": [str(row["id"])],
                    }
                    for row in top
                ],
                "candidate_references": [str(row["id"]) for row in top],
                "general_advice": [],
            }
            validated = validate_external_candidate_ids(payload, allowed_ids)
            return ExternalSupplementAnswer(job_id=job_id, **validated)

        source_context = [
            {
                "id": str(row["id"]),
                "title": row.get("title"),
                "caption": (row.get("caption") or "")[:600],
                "likes": row.get("likes"),
                "saves": row.get("saves"),
                "comments": row.get("comments"),
            }
            for row in candidates[:12]
        ]
        prompt = {
            "question": question,
            "external_pending_candidates": source_context,
            "rules": [
                "这些候选素材尚未审核，回答必须明确它们不是团队知识库内容。",
                "candidate_ids 只能引用 external_pending_candidates 中存在的 id。",
                "不要建议直接照搬内容，只给选题、标题结构、情绪角度和标签方向。",
                "中文输出。",
            ],
        }

        def _call():
            return self.openai.responses.create(
                model=OPENAI_TEXT_MODEL,
                instructions="你是小红书留学内容团队的外部素材研究员。你只能基于待审核候选素材输出 JSON。",
                input=json.dumps(prompt, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "external_supplement_answer",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "conclusion": {"type": "string"},
                                "recommendations": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "text": {"type": "string"},
                                            "candidate_ids": {"type": "array", "items": {"type": "string"}},
                                        },
                                        "required": ["text", "candidate_ids"],
                                    },
                                },
                                "candidate_references": {"type": "array", "items": {"type": "string"}},
                                "general_advice": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "text": {"type": "string"},
                                            "reason": {"type": "string"},
                                        },
                                        "required": ["text", "reason"],
                                    },
                                },
                            },
                            "required": ["conclusion", "recommendations", "candidate_references", "general_advice"],
                        },
                    }
                },
            )

        resp = await asyncio.to_thread(_call)
        validated = validate_external_candidate_ids(json.loads(resp.output_text), allowed_ids)
        return ExternalSupplementAnswer(job_id=job_id, **validated)
```

- [ ] **Step 3: Add supplement endpoint to `ai_api.py`**

Add:

```python
@app.post("/ai/discovery-jobs/{job_id}/supplement", dependencies=[Depends(require_api_key)])
async def create_discovery_supplement(job_id: str):
    try:
        payload = discovery_service.get_job_with_candidates(job_id)
        job = payload["job"]
        candidates = [
            row for row in payload["candidates"]
            if row.get("review_status") in ("pending", "approved")
        ]
        result = await research_service.generate_external_supplement(
            job_id=job_id,
            question=job.get("user_question") or "",
            candidates=candidates,
        )
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result.dict()
    except Exception as e:
        log.error(f"生成外部补充回答失败: {e}")
        raise HTTPException(500, "生成外部补充回答失败，请稍后重试。")
```

- [ ] **Step 4: Add frontend supplement client**

Append to `src/aiApi.js`:

```javascript
export async function createDiscoverySupplement(jobId) {
  return postJson(`/ai/discovery-jobs/${jobId}/supplement`, {});
}
```

- [ ] **Step 5: Render supplement in `AISearchPage.jsx`**

Import `createDiscoverySupplement`, add state:

```javascript
  const [externalSupplement, setExternalSupplement] = useState(null);
  const [supplementLoading, setSupplementLoading] = useState(false);
```

Add handler:

```javascript
  const handleCreateSupplement = async () => {
    if (!discoveryJob?.id) return;
    setSupplementLoading(true);
    try {
      const result = await createDiscoverySupplement(discoveryJob.id);
      setExternalSupplement(result);
    } catch (err) {
      alert(err.message || "生成外部补充回答失败，请稍后重试。");
    } finally {
      setSupplementLoading(false);
    }
  };
```

Render after candidate list:

```jsx
          {discoveryJob.status === "completed" && discoveryCandidates.length > 0 && (
            <button onClick={handleCreateSupplement} disabled={supplementLoading} style={{
              marginTop: 12,
              padding: "9px 14px",
              borderRadius: 8,
              border: "none",
              background: supplementLoading ? "#333" : "#FF9F43",
              color: "#111",
              cursor: supplementLoading ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 700,
            }}>
              {supplementLoading ? "生成中…" : "基于待审核素材生成补充回答"}
            </button>
          )}

          {externalSupplement && (
            <div style={{ marginTop: 14, background: "#111", border: "1px solid rgba(255,159,67,0.22)", borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 11, color: "#FF9F43", marginBottom: 8 }}>外部补充回答（待审核）</div>
              <div style={{ fontSize: 14, color: "#fff", lineHeight: 1.7 }}>{externalSupplement.conclusion}</div>
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                {(externalSupplement.recommendations || []).map((item, index) => (
                  <div key={index} style={{ fontSize: 13, color: "#aaa", lineHeight: 1.6 }}>
                    {item.text}
                  </div>
                ))}
              </div>
            </div>
          )}
```

- [ ] **Step 6: Verify backend and frontend**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m py_compile research_models.py research_service.py ai_api.py
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: compile passes and Vite build succeeds.

- [ ] **Step 7: Commit supplemental answer flow**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/research_models.py crawler/research_service.py crawler/ai_api.py src/aiApi.js src/components/AISearchPage.jsx
git commit -m "feat(ai): add external supplement answers"
```

## Task 8: Add Human Approval And Indexing

**Files:**
- Modify: `crawler/discovery_service.py`
- Modify: `crawler/ai_api.py`
- Modify: `src/aiApi.js`
- Modify: `src/components/AISearchPage.jsx`
- Test: `crawler/test_discovery.py`

- [ ] **Step 1: Add approval payload builder to `discovery_service.py`**

Add imports:

```python
from knowledge_indexer import build_viral_post_item, upsert_knowledge_item
```

Add methods to `DiscoveryService`:

```python
    def _find_existing_viral_post(self, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        note_id = candidate.get("xhs_note_id")
        if note_id:
            res = (
                self.sb.table("viral_posts")
                .select("*")
                .eq("xhs_note_id", note_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows:
                return rows[0]
        res = (
            self.sb.table("viral_posts")
            .select("*")
            .eq("url", candidate.get("url"))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def _viral_payload_from_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        note_text = "来源：AI 外部发现"
        if candidate.get("ai_reason"):
            note_text = f"{note_text}。{candidate['ai_reason']}"
        return {
            "url": candidate.get("url"),
            "note": note_text,
            "country": None,
            "fetch_status": "done",
            "fetched_at": now_iso(),
            "xhs_note_id": candidate.get("xhs_note_id"),
            "title": candidate.get("title") or "",
            "caption": candidate.get("caption") or "",
            "cover_image": candidate.get("cover_image"),
            "images": candidate.get("images") or [],
            "tags": candidate.get("tags") or [],
            "author_name": candidate.get("author_name"),
            "likes": candidate.get("likes") or 0,
            "saves": candidate.get("saves") or 0,
            "comments": candidate.get("comments") or 0,
            "views": candidate.get("views") or 0,
            "discovery_candidate_id": candidate.get("id"),
            "source_origin": "ai_external_discovery",
        }

    def approve_candidate(self, candidate_id: str) -> Dict[str, Any]:
        candidate_res = (
            self.sb.table("external_discovery_candidates")
            .select("*")
            .eq("id", candidate_id)
            .single()
            .execute()
        )
        candidate = candidate_res.data
        if not candidate:
            raise ValueError("候选素材不存在")
        if candidate.get("review_status") == "approved" and candidate.get("approved_viral_post_id"):
            return candidate

        payload = self._viral_payload_from_candidate(candidate)
        existing = self._find_existing_viral_post(candidate)
        if existing:
            viral_id = existing["id"]
            self.sb.table("viral_posts").update(payload).eq("id", viral_id).execute()
            viral_post = dict(existing)
            viral_post.update(payload)
            viral_post["id"] = viral_id
        else:
            insert_res = self.sb.table("viral_posts").insert([payload]).execute()
            rows = insert_res.data or []
            viral_post = rows[0]
            viral_id = viral_post["id"]

        updated_candidate = self.mark_candidate_review(candidate_id, "approved")
        self.sb.table("external_discovery_candidates").update({
            "approved_viral_post_id": viral_id,
        }).eq("id", candidate_id).execute()

        knowledge_item = build_viral_post_item(viral_post)
        upsert_knowledge_item(self.sb, knowledge_item)
        updated_candidate["approved_viral_post_id"] = viral_id
        return updated_candidate
```

- [ ] **Step 2: Add approve endpoint to `ai_api.py`**

Add:

```python
@app.post("/ai/discovery-candidates/{candidate_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_discovery_candidate(candidate_id: str):
    try:
        candidate = discovery_service.approve_candidate(candidate_id)
        return {"ok": True, "candidate": candidate}
    except Exception as e:
        log.error(f"候选素材入库失败: {e}")
        raise HTTPException(500, "候选素材入库失败，请稍后重试。")
```

- [ ] **Step 3: Add frontend approval client**

Append to `src/aiApi.js`:

```javascript
export async function approveDiscoveryCandidate(candidateId) {
  return postJson(`/ai/discovery-candidates/${candidateId}/approve`, {});
}
```

- [ ] **Step 4: Wire approval in `AISearchPage.jsx`**

Import `approveDiscoveryCandidate`.

Change `handleCandidateReview` to:

```javascript
  const handleCandidateReview = async (candidate, action) => {
    try {
      const resp = action === "approve"
        ? await approveDiscoveryCandidate(candidate.id)
        : action === "ignore"
          ? await ignoreDiscoveryCandidate(candidate.id)
          : await rejectDiscoveryCandidate(candidate.id, "不相关");
      const updated = resp.candidate;
      setDiscoveryCandidates(prev => prev.map(item => item.id === candidate.id ? { ...item, ...updated } : item));
    } catch (err) {
      alert(err.message || "操作失败，请稍后重试。");
    }
  };
```

Add approval button to `DiscoveryCandidateCard` before `忽略`:

```jsx
        <button disabled={disabled} onClick={() => onReview(candidate, "approve")} style={{ padding: "7px 10px", borderRadius: 7, border: "none", background: disabled ? "#333" : "#26DE81", color: "#111", cursor: disabled ? "not-allowed" : "pointer", fontSize: 12, fontWeight: 700 }}>
          通过并入库
        </button>
```

- [ ] **Step 5: Add status label for reviewed candidates**

Inside `DiscoveryCandidateCard`, after metrics, add:

```jsx
          {candidate.review_status !== "pending" && (
            <div style={{ marginTop: 8, fontSize: 11, color: candidate.review_status === "approved" ? "#26DE81" : "#555" }}>
              {candidate.review_status === "approved" ? "已入库" : candidate.review_status === "ignored" ? "已忽略" : "已标记不相关"}
            </div>
          )}
```

- [ ] **Step 6: Verify approval path compiles**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m py_compile discovery_service.py ai_api.py knowledge_indexer.py
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: compile passes and Vite build succeeds.

- [ ] **Step 7: Manual approval smoke test**

With `ai_api.py` running and one pending candidate row present, run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
export CANDIDATE_ID="$(
python3 - <<'PY'
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
rows = (
    supabase.table("external_discovery_candidates")
    .select("id")
    .eq("review_status", "pending")
    .order("created_at", desc=True)
    .limit(1)
    .execute()
    .data
    or []
)

if not rows:
    raise SystemExit("No pending external_discovery_candidates row found")

print(rows[0]["id"])
PY
)"

curl -s -X POST "$VITE_AI_API_URL/ai/discovery-candidates/$CANDIDATE_ID/approve" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $VITE_AI_API_KEY" \
  -d '{}' | python3 -m json.tool
```

Expected:

```json
{
  "ok": true,
  "candidate": {
    "review_status": "approved"
  }
}
```

Then confirm the database state:

```bash
python3 - <<'PY'
import os

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

candidate_id = os.environ["CANDIDATE_ID"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

candidate = (
    supabase.table("external_discovery_candidates")
    .select("review_status, approved_viral_post_id")
    .eq("id", candidate_id)
    .single()
    .execute()
    .data
)

items = (
    supabase.table("knowledge_items")
    .select("source_type, source_id, embed_status")
    .eq("source_type", "viral_post")
    .order("created_at", desc=True)
    .limit(5)
    .execute()
    .data
    or []
)

print(candidate)
print(items)
PY
```

Expected: candidate is approved with a viral post id; a `viral_post` knowledge item exists and is pending/completed for embedding.

- [ ] **Step 8: Commit approval and indexing flow**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/discovery_service.py crawler/ai_api.py src/aiApi.js src/components/AISearchPage.jsx
git commit -m "feat(ai): approve discovery candidates into knowledge"
```

## Task 9: Documentation And End-To-End Verification

**Files:**
- Modify: `README.md`
- Test: backend and frontend verification commands

- [ ] **Step 1: Add README setup notes**

In both English and Chinese local setup sections, add a short AI external discovery subsection:

```markdown
# Optional: AI external discovery loop
# 1. Run crawler/ai_schema.sql in Supabase SQL Editor after the core schema.
# 2. Set EXTERNAL_DISCOVERY_ENABLED = True in crawler/config.py after validating crawler login.
# 3. Keep EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first" until crawl quality is reviewed.
# 4. Start crawler/server.py and crawler/ai_api.py.
# 5. Ask a sparse question in AI 搜索中心, click 去小红书找参考, review candidates, then approve useful items.
```

- [ ] **Step 2: Run full local checks**

Run:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 -m unittest test_discovery.py test_retrieval.py test_knowledge_indexer.py
python3 -m py_compile ai_api.py discovery.py discovery_service.py xhs_discovery.py research_models.py research_service.py knowledge_indexer.py server.py
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
git diff --check
```

Expected:

- Python tests pass.
- Python compile exits with no output.
- Vite build succeeds; the existing chunk-size warning is acceptable.
- `git diff --check` exits with no output.

- [ ] **Step 3: Run API smoke checks**

Start AI API:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python3 ai_api.py
```

In another terminal:

```bash
curl -s "$VITE_AI_API_URL/healthz" | python3 -m json.tool
```

Expected:

```json
{
  "ok": true,
  "embed_model": "voyage-3-lite",
  "embed_dim": 512
}
```

Create a discovery job:

```bash
curl -s -X POST "$VITE_AI_API_URL/ai/discovery-jobs" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $VITE_AI_API_KEY" \
  -d '{
    "user_question": "英国申请焦虑方向有什么爆款素材？",
    "task_type": "material",
    "trigger_reason": "user_requested",
    "internal_answer_payload": {"conclusion": "内部资料匹配较少。"},
    "search_queries": ["英国留学 申请焦虑"]
  }' | python3 -m json.tool
```

Expected: response includes `"ok": true` and a job with `"status": "pending"`.

- [ ] **Step 4: Run browser flow**

Start frontend:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run dev
```

Manual expected flow:

1. Open `http://localhost:5173`.
2. Go to `AI 搜索`.
3. Ask a question that returns sparse internal knowledge.
4. See `去小红书找参考`.
5. Click it.
6. See an external discovery job card.
7. After crawler completes or fixture candidates exist, see `待审核外部素材`.
8. Click `通过并入库` on one candidate.
9. Candidate shows `已入库`.

- [ ] **Step 5: Commit documentation and final verification notes**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add README.md
git commit -m "docs(ai): document external discovery setup"
```

## Self-Review Checklist

- [ ] Spec requirement covered: sparse internal recall can offer or create discovery job.
- [ ] Spec requirement covered: keyword search and benchmark account expansion both exist.
- [ ] Spec requirement covered: external candidates stay separate from internal citations.
- [ ] Spec requirement covered: human approval is required before formal knowledge indexing.
- [ ] Spec requirement covered: crawler limits and feature kill switch are configurable.
- [ ] Spec requirement covered: rejected and ignored candidates do not enter `knowledge_items`.
- [ ] Type names match across tasks: `external_discovery_jobs`, `external_discovery_candidates`, `discovery_job_id`, `candidate_ids`, `review_status`.
- [ ] No broad refactor is required; changes stay within AI API, crawler, AI page, and schema.

## Execution Options

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, faster iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batching with checkpoints.

Recommended path: start with Tasks 1-5 to deliver the safe manual job flow first, then Tasks 6-8 to turn on real crawling and approval indexing.
