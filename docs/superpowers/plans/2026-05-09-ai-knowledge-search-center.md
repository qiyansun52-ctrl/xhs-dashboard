# AI Knowledge Search Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build version one of `AI 搜索中心`: a bounded research assistant that retrieves material-library and team-history knowledge, answers with validated citations, supports optional image analysis, and saves research notes.

**Architecture:** Add a rebuildable `knowledge_items` retrieval index in Supabase, extend the existing FastAPI AI service with research/retrieval/note endpoints, and add a new React page plus top-level navigation entry. Version one reuses the existing `voyage-3-lite` embedding path, uses RRF for hybrid retrieval, performs server-side citation existence validation, and keeps follow-up context client-carried rather than persistent chat threads.

**Tech Stack:** React 18 + Vite, inline styles, Supabase Postgres/Storage/pgvector, FastAPI, Pydantic, `voyageai`, optional OpenAI Responses API for generation/VLM, Python `unittest` for pure helper tests, `npm run build` for frontend verification.

---

## File Structure

| File | Status | Responsibility |
| --- | --- | --- |
| `crawler/ai_research_schema.sql` | create | Supabase SQL for `knowledge_items`, `index_jobs`, `ai_research_notes`, feedback, and vector RPC |
| `crawler/research_models.py` | create | Shared Pydantic request/response/source models for the AI research flow |
| `crawler/retrieval.py` | create | Pure retrieval helpers: RRF merge, sparse detection, citation validation, keyword query assembly |
| `crawler/test_retrieval.py` | create | Unit tests for retrieval helpers and citation validation |
| `crawler/knowledge_indexer.py` | create | Builds `knowledge_items` rows from Supabase source tables and processes `index_jobs` |
| `crawler/test_knowledge_indexer.py` | create | Unit tests for source-to-index text/metadata builders |
| `crawler/research_service.py` | create | Orchestrates task classification, optional VLM analysis, retrieval, generation, citation validation |
| `crawler/ai_api.py` | modify | Register `/ai/research`, `/ai/research-notes`, `/ai/research/health`, and index status endpoints |
| `crawler/config.example.py` | modify | Add AI research generation/VLM config knobs |
| `crawler/requirements.txt` | modify | Add `openai` dependency for generation/VLM adapter |
| `.env.example` | modify | Add frontend AI API settings |
| `src/aiApi.js` | create | Browser client for AI API calls and image upload path helpers |
| `src/components/AISearchPage.jsx` | create | New top-level AI Search Center page |
| `src/App.jsx` | modify | Add `AI 搜索中心` navigation and route branch |
| `docs/superpowers/evals/ai-knowledge-golden-set.example.json` | create | Golden-set template for offline evaluation |
| `crawler/eval_research.py` | create | Manual eval runner for golden-set Recall@10 and MRR |

## Verification Strategy

This repo has no JS test framework. Use focused Python unit tests for pure backend logic, SQL review for Supabase schema, `npm run build` for frontend compilation, and manual curl/browser checks for end-to-end behavior.

Use these commands repeatedly:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py test_knowledge_indexer.py
```

Expected: all tests pass.

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: Vite production build succeeds without import or syntax errors.

---

## Task 1: Add AI Research Schema

**Files:**
- Create: `crawler/ai_research_schema.sql`

- [ ] **Step 1: Create the schema file**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/ai_research_schema.sql` with this content:

```sql
-- ===============================================================
-- AI 搜索中心 schema
-- 在 Supabase Dashboard -> SQL Editor 中粘贴并执行
-- ===============================================================

create extension if not exists vector;

create table if not exists knowledge_items (
  id uuid primary key default gen_random_uuid(),
  source_type text not null check (source_type in (
    'viral_post',
    'benchmark_account',
    'benchmark_post',
    'topic',
    'title',
    'team_post',
    'account',
    'banned_word'
  )),
  source_id text not null,
  source_key text not null,
  parent_source_type text,
  parent_source_id text,
  source_url text,
  title text not null default '',
  content text not null default '',
  summary text,
  tags text[] default '{}',
  country text,
  account_id integer,
  language text not null default 'zh' check (language in ('zh', 'en', 'mixed')),
  content_type text,
  likes_count bigint,
  saves_count bigint,
  comments_count bigint,
  views_count bigint,
  metrics_extra jsonb not null default '{}'::jsonb,
  image_urls text[] default '{}',
  embedding vector(512),
  embedding_model_version text,
  embed_status text not null default 'pending' check (embed_status in ('pending', 'processing', 'completed', 'failed')),
  embed_error text,
  retry_count integer not null default 0,
  is_active boolean not null default true,
  published_at timestamptz,
  source_updated_at timestamptz,
  content_hash text,
  last_indexed_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(source_type, source_key)
);

create index if not exists knowledge_items_embedding_hnsw
  on knowledge_items using hnsw (embedding vector_cosine_ops)
  where embedding is not null and is_active = true;

create index if not exists idx_knowledge_items_source_active
  on knowledge_items(source_type, is_active);

create index if not exists idx_knowledge_items_country_active
  on knowledge_items(country, is_active);

create index if not exists idx_knowledge_items_account
  on knowledge_items(account_id);

create index if not exists idx_knowledge_items_tags
  on knowledge_items using gin(tags);

alter table knowledge_items enable row level security;
create policy "team_access" on knowledge_items for all using (true) with check (true);

create table if not exists index_jobs (
  id uuid primary key default gen_random_uuid(),
  source_type text not null,
  source_id text not null,
  operation text not null default 'upsert' check (operation in ('upsert', 'deactivate')),
  status text not null default 'pending' check (status in ('pending', 'processing', 'completed', 'failed')),
  retry_count integer not null default 0,
  error_message text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_index_jobs_status_created
  on index_jobs(status, created_at);

alter table index_jobs enable row level security;
create policy "team_access" on index_jobs for all using (true) with check (true);

create table if not exists ai_research_notes (
  id uuid primary key default gen_random_uuid(),
  user_question text not null,
  image_url text,
  conclusion text,
  recommendations jsonb not null default '[]'::jsonb,
  material_references jsonb not null default '[]'::jsonb,
  team_history_references jsonb not null default '[]'::jsonb,
  image_analysis jsonb,
  full_payload jsonb not null default '{}'::jsonb,
  user_note text,
  creator_id uuid,
  visibility text not null default 'team' check (visibility in ('team')),
  created_at timestamptz default now()
);

alter table ai_research_notes enable row level security;
create policy "team_access" on ai_research_notes for all using (true) with check (true);

create table if not exists ai_research_feedback (
  id uuid primary key default gen_random_uuid(),
  note_id uuid references ai_research_notes(id) on delete set null,
  question text not null,
  rating text not null check (rating in ('up', 'down')),
  reason text check (reason in ('结论错', '引用不支持', '不相关', '不够具体')),
  created_at timestamptz default now()
);

alter table ai_research_feedback enable row level security;
create policy "team_access" on ai_research_feedback for all using (true) with check (true);

create or replace function match_knowledge_items(
  query_embedding vector(512),
  match_count integer default 30,
  source_types text[] default null,
  country_filter text default null
)
returns table (
  id uuid,
  source_type text,
  source_id text,
  source_key text,
  parent_source_type text,
  parent_source_id text,
  source_url text,
  title text,
  content text,
  summary text,
  tags text[],
  country text,
  account_id integer,
  language text,
  content_type text,
  likes_count bigint,
  saves_count bigint,
  comments_count bigint,
  views_count bigint,
  metrics_extra jsonb,
  image_urls text[],
  published_at timestamptz,
  similarity float
)
language sql stable as $$
  select
    k.id,
    k.source_type,
    k.source_id,
    k.source_key,
    k.parent_source_type,
    k.parent_source_id,
    k.source_url,
    k.title,
    k.content,
    k.summary,
    k.tags,
    k.country,
    k.account_id,
    k.language,
    k.content_type,
    k.likes_count,
    k.saves_count,
    k.comments_count,
    k.views_count,
    k.metrics_extra,
    k.image_urls,
    k.published_at,
    (1 - (k.embedding <=> query_embedding))::float as similarity
  from knowledge_items k
  where k.is_active = true
    and k.embedding is not null
    and (source_types is null or k.source_type = any(source_types))
    and (country_filter is null or k.country = country_filter)
  order by k.embedding <=> query_embedding
  limit match_count
$$;
```

- [ ] **Step 2: Apply schema in Supabase**

Run the SQL in Supabase SQL Editor.

Expected: tables and function are created without SQL errors.

- [ ] **Step 3: Commit schema**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/ai_research_schema.sql
git commit -m "feat(ai): add research knowledge schema"
```

## Task 2: Add Retrieval Helper Tests And Models

**Files:**
- Create: `crawler/research_models.py`
- Create: `crawler/retrieval.py`
- Create: `crawler/test_retrieval.py`

- [ ] **Step 1: Write retrieval tests**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/test_retrieval.py`:

```python
import unittest

from retrieval import detect_task_type, is_sparse_result, rrf_merge, validate_citations


class RetrievalTests(unittest.TestCase):
    def test_rrf_merge_promotes_items_seen_in_both_lists(self):
        semantic = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        keyword = [{"id": "b"}, {"id": "d"}, {"id": "a"}]

        merged = rrf_merge([semantic, keyword], k=60)

        self.assertEqual(merged[0]["id"], "b")
        self.assertEqual({row["id"] for row in merged[:4]}, {"a", "b", "c", "d"})
        self.assertGreater(merged[0]["rrf_score"], merged[-1]["rrf_score"])

    def test_detect_task_type_prefers_experience_for_history_words(self):
        self.assertEqual(detect_task_type("我们过去写过哪些文书相关内容"), "experience")
        self.assertEqual(detect_task_type("帮我找英国申请焦虑爆款素材"), "material")
        self.assertEqual(detect_task_type("结合这张图找参考", has_image=True), "image_reference")

    def test_sparse_result_thresholds(self):
        self.assertTrue(is_sparse_result([], top_score_threshold=0.2))
        self.assertTrue(is_sparse_result([{"score": 0.1}], top_score_threshold=0.2))
        self.assertFalse(is_sparse_result([{"score": 0.9}, {"score": 0.7}, {"score": 0.6}], top_score_threshold=0.2))

    def test_validate_citations_removes_fabricated_ids(self):
        answer = {
            "recommendations": [
                {"text": "用焦虑共鸣开头", "source_ids": ["ki_1", "fake"]},
                {"text": "加入清单式步骤", "source_ids": ["fake_only"]},
            ],
            "general_advice": [],
        }
        validated = validate_citations(answer, retrieved_ids={"ki_1"})

        self.assertEqual(validated["recommendations"][0]["source_ids"], ["ki_1"])
        self.assertEqual(len(validated["recommendations"]), 1)
        self.assertEqual(validated["general_advice"][0]["text"], "加入清单式步骤")
        self.assertEqual(validated["general_advice"][0]["reason"], "citation validation removed unsupported source ids")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval'`.

- [ ] **Step 3: Add shared models**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/research_models.py`:

```python
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TaskType = Literal["material", "experience", "image_reference", "mixed"]


class ImageAnalysis(BaseModel):
    subject: str = ""
    scene: str = ""
    mood: str = ""
    visual_style: str = ""
    content_direction: str = ""
    keywords: List[str] = Field(default_factory=list)
    description: str = ""


class KnowledgeSource(BaseModel):
    id: str
    source_type: str
    source_id: str
    source_key: str
    title: str = ""
    content: str = ""
    summary: Optional[str] = None
    source_url: Optional[str] = None
    country: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    image_urls: List[str] = Field(default_factory=list)
    likes_count: Optional[int] = None
    saves_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    similarity: Optional[float] = None
    rrf_score: Optional[float] = None


class Recommendation(BaseModel):
    text: str
    source_ids: List[str] = Field(default_factory=list)


class GeneralAdvice(BaseModel):
    text: str
    reason: str


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    image_url: Optional[str] = None
    previous_answer_summary: Optional[str] = None
    previous_citation_ids: List[str] = Field(default_factory=list)


class ResearchAnswer(BaseModel):
    question: str
    task_type: TaskType
    conclusion: str
    recommendations: List[Recommendation] = Field(default_factory=list)
    material_references: List[str] = Field(default_factory=list)
    team_history_references: List[str] = Field(default_factory=list)
    related_sources: List[KnowledgeSource] = Field(default_factory=list)
    cited_sources: List[KnowledgeSource] = Field(default_factory=list)
    image_analysis: Optional[ImageAnalysis] = None
    general_advice: List[GeneralAdvice] = Field(default_factory=list)
    sparse: bool = False
    message: Optional[str] = None
```

- [ ] **Step 4: Add retrieval helpers**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/retrieval.py`:

```python
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set


EXPERIENCE_WORDS = ("过去", "历史", "我们写过", "团队", "之前", "过往")
MATERIAL_WORDS = ("素材", "爆款", "参考", "对标", "收藏")


def detect_task_type(question: str, has_image: bool = False) -> str:
    text = question or ""
    if has_image:
        return "image_reference"
    if any(word in text for word in EXPERIENCE_WORDS):
        return "experience"
    if any(word in text for word in MATERIAL_WORDS):
        return "material"
    return "mixed"


def rrf_merge(result_lists: Sequence[Sequence[dict]], k: int = 60) -> List[dict]:
    scores: Dict[str, float] = {}
    rows: Dict[str, dict] = {}
    for result_list in result_lists:
        for rank, row in enumerate(result_list, start=1):
            item_id = str(row["id"])
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in rows:
                rows[item_id] = dict(row)
    merged = []
    for item_id, row in rows.items():
        row["rrf_score"] = scores[item_id]
        row["score"] = row.get("similarity") or row["rrf_score"]
        merged.append(row)
    return sorted(merged, key=lambda row: row["rrf_score"], reverse=True)


def is_sparse_result(rows: Sequence[dict], top_score_threshold: float = 0.2, min_count: int = 3) -> bool:
    if not rows:
        return True
    top_score = rows[0].get("score") or rows[0].get("rrf_score") or rows[0].get("similarity") or 0
    return len(rows) < min_count or float(top_score) < top_score_threshold


def validate_citations(answer: dict, retrieved_ids: Iterable[str]) -> dict:
    allowed: Set[str] = set(str(item_id) for item_id in retrieved_ids)
    cleaned = dict(answer)
    valid_recommendations = []
    general_advice = list(cleaned.get("general_advice") or [])

    for rec in cleaned.get("recommendations") or []:
        source_ids = [sid for sid in rec.get("source_ids", []) if sid in allowed]
        if source_ids:
            updated = dict(rec)
            updated["source_ids"] = source_ids
            valid_recommendations.append(updated)
        else:
            general_advice.append({
                "text": rec.get("text", ""),
                "reason": "citation validation removed unsupported source ids",
            })

    cleaned["recommendations"] = valid_recommendations
    cleaned["general_advice"] = general_advice
    cleaned["material_references"] = [
        sid for sid in cleaned.get("material_references", []) if sid in allowed
    ]
    cleaned["team_history_references"] = [
        sid for sid in cleaned.get("team_history_references", []) if sid in allowed
    ]
    return cleaned
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py
```

Expected: `OK`.

- [ ] **Step 6: Commit retrieval helpers**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/research_models.py crawler/retrieval.py crawler/test_retrieval.py
git commit -m "feat(ai): add research retrieval helpers"
```

## Task 3: Add Knowledge Indexer

**Files:**
- Create: `crawler/knowledge_indexer.py`
- Create: `crawler/test_knowledge_indexer.py`

- [ ] **Step 1: Write indexer tests**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/test_knowledge_indexer.py`:

```python
import unittest

from knowledge_indexer import (
    build_benchmark_post_item,
    build_content_hash,
    build_team_post_item,
    detect_language,
)


class KnowledgeIndexerTests(unittest.TestCase):
    def test_detect_language(self):
        self.assertEqual(detect_language("英国留学申请"), "zh")
        self.assertEqual(detect_language("personal statement checklist"), "en")
        self.assertEqual(detect_language("英国 UCAS checklist"), "mixed")

    def test_build_content_hash_changes_when_content_changes(self):
        first = build_content_hash("title", "caption")
        second = build_content_hash("title", "different caption")
        self.assertNotEqual(first, second)

    def test_build_team_post_item_uses_post_stats(self):
        item = build_team_post_item(
            {
                "id": "post-1",
                "title": "英国文书怎么准备",
                "caption": "三步拆解申请文书",
                "tags": ["英国", "文书"],
                "images": ["https://example.com/a.jpg"],
                "account_id": 7,
                "status": "published",
                "created_at": "2026-05-01T00:00:00+00:00",
            },
            {"likes": 12, "saves": 34, "comments": 5, "views": 1000},
        )
        self.assertEqual(item["source_type"], "team_post")
        self.assertEqual(item["source_key"], "post-1")
        self.assertEqual(item["saves_count"], 34)
        self.assertIn("英国文书怎么准备", item["content"])

    def test_build_benchmark_post_item_has_parent_and_stable_key(self):
        item = build_benchmark_post_item(
            benchmark_id="bench-1",
            account_name="英国申请学姐",
            post={
                "note_id": "note-9",
                "title": "申请季别崩",
                "caption": "焦虑也能拆成步骤",
                "tags": ["申请焦虑"],
                "likes": 99,
                "cover_image": "https://example.com/cover.jpg",
            },
        )
        self.assertEqual(item["source_type"], "benchmark_post")
        self.assertEqual(item["source_key"], "bench-1:note-9")
        self.assertEqual(item["parent_source_id"], "bench-1")
        self.assertEqual(item["likes_count"], 99)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_knowledge_indexer.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_indexer'`.

- [ ] **Step 3: Add pure index builder implementation**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/knowledge_indexer.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


EMBED_MODEL_VERSION = "voyage-3-lite:512"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_language(text: str) -> str:
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text or ""))
    has_ascii_word = bool(re.search(r"[A-Za-z]{3,}", text or ""))
    if has_cjk and has_ascii_word:
        return "mixed"
    if has_ascii_word and not has_cjk:
        return "en"
    return "zh"


def build_content_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_tags(tags: Any) -> List[str]:
    if not tags:
        return []
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    return [str(tags).strip()] if str(tags).strip() else []


def build_text(title: str, caption: str = "", tags: Optional[List[str]] = None) -> str:
    parts = [title.strip()]
    if caption and caption.strip():
        parts.append(caption.strip())
    if tags:
        parts.append("标签：" + " ".join(tags))
    return "\n\n".join(part for part in parts if part)


def build_team_post_item(post: Dict[str, Any], stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tags = normalize_tags(post.get("tags"))
    title = post.get("title") or ""
    caption = post.get("caption") or ""
    content = build_text(title, caption, tags)
    stats = stats or {}
    return {
        "source_type": "team_post",
        "source_id": str(post["id"]),
        "source_key": str(post["id"]),
        "source_url": None,
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": None,
        "account_id": post.get("account_id"),
        "language": detect_language(content),
        "content_type": "image-heavy" if post.get("images") else "text-heavy",
        "likes_count": stats.get("likes"),
        "saves_count": stats.get("saves"),
        "comments_count": stats.get("comments"),
        "views_count": stats.get("views"),
        "metrics_extra": {"status": post.get("status"), "shares": stats.get("shares")},
        "image_urls": post.get("images") or [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": post.get("scheduled_at") or post.get("created_at"),
        "source_updated_at": post.get("updated_at") or post.get("created_at"),
        "content_hash": build_content_hash(title, caption, tags, stats),
        "last_indexed_at": now_iso(),
    }


def build_benchmark_post_item(benchmark_id: str, account_name: str, post: Dict[str, Any]) -> Dict[str, Any]:
    tags = normalize_tags(post.get("tags"))
    title = post.get("title") or ""
    caption = post.get("caption") or ""
    note_id = post.get("note_id") or post.get("id") or str(post.get("index", "0"))
    content = build_text(title, caption, tags)
    return {
        "source_type": "benchmark_post",
        "source_id": str(note_id),
        "source_key": f"{benchmark_id}:{note_id}",
        "parent_source_type": "benchmark_account",
        "parent_source_id": str(benchmark_id),
        "source_url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None,
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": post.get("country"),
        "account_id": None,
        "language": detect_language(content),
        "content_type": "image-heavy" if post.get("images") or post.get("cover_image") else "text-heavy",
        "likes_count": post.get("likes"),
        "saves_count": post.get("saves"),
        "comments_count": post.get("comments"),
        "views_count": post.get("views"),
        "metrics_extra": {"author_name": account_name},
        "image_urls": post.get("images") or ([post["cover_image"]] if post.get("cover_image") else []),
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": post.get("published_at"),
        "source_updated_at": post.get("updated_at"),
        "content_hash": build_content_hash(title, caption, tags, post.get("likes"), post.get("saves")),
        "last_indexed_at": now_iso(),
    }
```

- [ ] **Step 4: Run indexer tests**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_knowledge_indexer.py
```

Expected: `OK`.

- [ ] **Step 5: Extend indexer with Supabase rebuild command**

Append this implementation to `crawler/knowledge_indexer.py`:

```python

def upsert_knowledge_item(sb, item: Dict[str, Any]) -> None:
    existing = (
        sb.table("knowledge_items")
        .select("id, content_hash")
        .eq("source_type", item["source_type"])
        .eq("source_key", item["source_key"])
        .maybe_single()
        .execute()
    )
    current = existing.data
    if current and current.get("content_hash") == item.get("content_hash"):
        item["embed_status"] = "completed"
    sb.table("knowledge_items").upsert(item, on_conflict="source_type,source_key").execute()


def rebuild_team_posts(sb) -> int:
    posts = sb.table("posts").select("*").execute().data or []
    count = 0
    for post in posts:
        stats = {}
        try:
            res = sb.table("post_stats").select("*").eq("post_id", post["id"]).maybe_single().execute()
            stats = res.data or {}
        except Exception:
            stats = {}
        upsert_knowledge_item(sb, build_team_post_item(post, stats))
        count += 1
    return count


def rebuild_benchmark_posts(sb) -> int:
    rows = sb.table("benchmark_accounts").select("*").execute().data or []
    count = 0
    for row in rows:
        recent_posts = row.get("recent_posts") or []
        for index, post in enumerate(recent_posts):
            post = dict(post)
            post.setdefault("index", index)
            upsert_knowledge_item(sb, build_benchmark_post_item(str(row["id"]), row.get("name") or "", post))
            count += 1
    return count


def build_viral_post_item(row: Dict[str, Any]) -> Dict[str, Any]:
    tags = normalize_tags(row.get("tags"))
    title = row.get("title") or ""
    caption = row.get("caption") or row.get("note") or ""
    content = build_text(title, caption, tags)
    return {
        "source_type": "viral_post",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("url"),
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": row.get("country"),
        "account_id": None,
        "language": detect_language(content),
        "content_type": "image-heavy" if row.get("images") or row.get("cover_image") else "text-heavy",
        "likes_count": row.get("likes"),
        "saves_count": row.get("saves"),
        "comments_count": row.get("comments"),
        "views_count": row.get("views"),
        "metrics_extra": {"author_name": row.get("author_name")},
        "image_urls": row.get("images") or ([row["cover_image"]] if row.get("cover_image") else []),
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": row.get("fetch_status") == "done",
        "published_at": row.get("published_at") or row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, caption, tags, row.get("likes"), row.get("saves")),
        "last_indexed_at": now_iso(),
    }


def build_topic_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("tag") or "选题"
    content = row.get("description") or ""
    return {
        "source_type": "topic",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("reference_url"),
        "title": title,
        "content": content,
        "summary": content[:240] if content else None,
        "tags": normalize_tags([row.get("tag")]),
        "country": None,
        "account_id": None,
        "language": detect_language(content),
        "content_type": "topic",
        "likes_count": row.get("ref_likes"),
        "saves_count": row.get("ref_saves"),
        "comments_count": None,
        "views_count": row.get("ref_views"),
        "metrics_extra": {"fetch_status": row.get("fetch_status")},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, content, row.get("tag")),
        "last_indexed_at": now_iso(),
    }


def build_title_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("title") or ""
    return {
        "source_type": "title",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": None,
        "title": title,
        "content": title,
        "summary": title,
        "tags": [],
        "country": None,
        "account_id": None,
        "language": detect_language(title),
        "content_type": "title",
        "likes_count": None,
        "saves_count": None,
        "comments_count": None,
        "views_count": None,
        "metrics_extra": {},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("created_at"),
        "content_hash": build_content_hash(title),
        "last_indexed_at": now_iso(),
    }


def build_account_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("name") or ""
    content = build_text(title, row.get("bio") or "", [row.get("flag") or ""])
    return {
        "source_type": "account",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("xhs_link"),
        "title": title,
        "content": content,
        "summary": row.get("bio"),
        "tags": normalize_tags([row.get("flag")]),
        "country": row.get("flag"),
        "account_id": row.get("id"),
        "language": detect_language(content),
        "content_type": "account",
        "likes_count": row.get("likes"),
        "saves_count": row.get("saves"),
        "comments_count": None,
        "views_count": row.get("views"),
        "metrics_extra": {"followers": row.get("followers")},
        "image_urls": [row["avatar"]] if str(row.get("avatar") or "").startswith("http") else [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, row.get("bio"), row.get("followers")),
        "last_indexed_at": now_iso(),
    }


def build_banned_word_item(row: Dict[str, Any]) -> Dict[str, Any]:
    word = row.get("word") or ""
    return {
        "source_type": "banned_word",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": None,
        "title": word,
        "content": word,
        "summary": word,
        "tags": [],
        "country": None,
        "account_id": None,
        "language": detect_language(word),
        "content_type": "risk",
        "likes_count": None,
        "saves_count": None,
        "comments_count": None,
        "views_count": None,
        "metrics_extra": {},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("created_at"),
        "content_hash": build_content_hash(word),
        "last_indexed_at": now_iso(),
    }


def rebuild_table(sb, table: str, builder) -> int:
    rows = sb.table(table).select("*").execute().data or []
    for row in rows:
        upsert_knowledge_item(sb, builder(row))
    return len(rows)


def rebuild_all(sb) -> Dict[str, int]:
    return {
        "viral_posts": rebuild_table(sb, "viral_posts", build_viral_post_item),
        "team_posts": rebuild_team_posts(sb),
        "benchmark_posts": rebuild_benchmark_posts(sb),
        "topics": rebuild_table(sb, "topics", build_topic_item),
        "titles": rebuild_table(sb, "titles", build_title_item),
        "accounts": rebuild_table(sb, "accounts", build_account_item),
        "banned_words": rebuild_table(sb, "banned_words", build_banned_word_item),
    }


if __name__ == "__main__":
    from supabase import create_client
    from config import SUPABASE_KEY, SUPABASE_URL

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    result = rebuild_all(client)
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: Run all backend helper tests**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py test_knowledge_indexer.py
```

Expected: `OK`.

- [ ] **Step 7: Commit indexer**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/knowledge_indexer.py crawler/test_knowledge_indexer.py
git commit -m "feat(ai): add knowledge indexer"
```

## Task 4: Add Research Service And Citation Validation Flow

**Files:**
- Create: `crawler/research_service.py`
- Modify: `crawler/config.example.py`
- Modify: `crawler/requirements.txt`

- [ ] **Step 1: Update requirements**

Add this line to `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/requirements.txt`:

```txt
openai>=1.99.0
```

- [ ] **Step 2: Install backend dependencies**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
pip install -r requirements.txt
```

Expected: `openai`, `fastapi`, `supabase`, and `voyageai` are installed in the active Python environment.

- [ ] **Step 3: Update config example**

Append this block to `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/config.example.py`:

```python

# ── AI 搜索中心：生成与图片理解 ─────────────────────────────────
# 不配置 OPENAI_API_KEY 时，/ai/research 会返回基于检索结果的保守 fallback 答案
OPENAI_API_KEY = ""
OPENAI_TEXT_MODEL = "gpt-4.1-mini"
OPENAI_VISION_MODEL = "gpt-4.1-mini"

# 检索阈值，可根据 golden set 调整
AI_RESEARCH_MIN_RESULTS = 3
AI_RESEARCH_TOP_SCORE_THRESHOLD = 0.2
```

- [ ] **Step 4: Create research service**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/research_service.py`:

```python
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from research_models import ImageAnalysis, KnowledgeSource, ResearchAnswer, ResearchRequest
from retrieval import detect_task_type, is_sparse_result, rrf_merge, validate_citations

try:
    from config import OPENAI_API_KEY, OPENAI_TEXT_MODEL, OPENAI_VISION_MODEL
except Exception:
    OPENAI_API_KEY = ""
    OPENAI_TEXT_MODEL = "gpt-4.1-mini"
    OPENAI_VISION_MODEL = "gpt-4.1-mini"


class ResearchService:
    def __init__(self, supabase_client, embed_texts):
        self.sb = supabase_client
        self.embed_texts = embed_texts
        self.openai_key = OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.openai = OpenAI(api_key=self.openai_key) if self.openai_key else None

    async def research(self, req: ResearchRequest) -> ResearchAnswer:
        task_type = detect_task_type(req.question, has_image=bool(req.image_url))
        image_analysis = None
        image_query = ""
        if req.image_url:
            image_analysis = await self.analyze_image(req.image_url)
            image_query = " ".join([
                image_analysis.subject,
                image_analysis.scene,
                image_analysis.mood,
                image_analysis.visual_style,
                image_analysis.content_direction,
                " ".join(image_analysis.keywords),
            ]).strip()

        query = "\n".join(part for part in [
            req.question,
            req.previous_answer_summary or "",
            image_query,
        ] if part)
        retrieved_rows = await self.retrieve(query=query, task_type=task_type)
        sparse = is_sparse_result(retrieved_rows)

        answer_payload = self.generate_answer(
            question=req.question,
            task_type=task_type,
            rows=retrieved_rows,
            sparse=sparse,
            image_analysis=image_analysis,
        )
        validated = validate_citations(answer_payload, retrieved_ids={str(row["id"]) for row in retrieved_rows})
        sources = [KnowledgeSource(**self._source_shape(row)) for row in retrieved_rows]
        cited_ids = set()
        for rec in validated.get("recommendations", []):
            cited_ids.update(rec.get("source_ids") or [])
        cited_sources = [source for source in sources if source.id in cited_ids]

        return ResearchAnswer(
            question=req.question,
            task_type=task_type,
            conclusion=validated["conclusion"],
            recommendations=validated.get("recommendations", []),
            material_references=validated.get("material_references", []),
            team_history_references=validated.get("team_history_references", []),
            related_sources=sources,
            cited_sources=cited_sources,
            image_analysis=image_analysis,
            general_advice=validated.get("general_advice", []),
            sparse=sparse,
            message="内部资料匹配较少，以下建议包含少量通用创作建议。" if sparse else None,
        )

    async def retrieve(self, query: str, task_type: str) -> List[Dict[str, Any]]:
        embeds = await self.embed_texts([query], input_type="query")
        source_types = self._source_types_for_task(task_type)
        vector_res = self.sb.rpc("match_knowledge_items", {
            "query_embedding": embeds[0],
            "match_count": 30,
            "source_types": source_types,
            "country_filter": None,
        }).execute()
        vector_rows = vector_res.data or []

        keyword_rows = self.keyword_candidates(query, source_types=source_types)
        merged = rrf_merge([vector_rows, keyword_rows])
        return merged[:20]

    def keyword_candidates(self, query: str, source_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        words = [word for word in query.replace("，", " ").replace(",", " ").split() if len(word) >= 2]
        if not words:
            return []
        q = self.sb.table("knowledge_items").select("*").eq("is_active", True).limit(30)
        if source_types:
            q = q.in_("source_type", source_types)
        first = words[0]
        res = q.or_(f"title.ilike.%{first}%,content.ilike.%{first}%").execute()
        return res.data or []

    async def analyze_image(self, image_url: str) -> ImageAnalysis:
        if self.openai:
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string"},
                    "scene": {"type": "string"},
                    "mood": {"type": "string"},
                    "visual_style": {"type": "string"},
                    "content_direction": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                },
                "required": ["subject", "scene", "mood", "visual_style", "content_direction", "keywords", "description"],
            }
            resp = self.openai.responses.create(
                model=OPENAI_VISION_MODEL,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "请分析这张小红书配图，输出可用于留学内容选题检索的结构化 JSON。"},
                        {"type": "input_image", "image_url": image_url, "detail": "auto"},
                    ],
                }],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "image_analysis",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
            return ImageAnalysis(**json.loads(resp.output_text))
        return ImageAnalysis(
            subject="",
            scene="",
            mood="",
            visual_style="",
            content_direction="",
            keywords=[],
            description=f"图片已上传：{image_url}",
        )

    def generate_answer(
        self,
        question: str,
        task_type: str,
        rows: List[Dict[str, Any]],
        sparse: bool,
        image_analysis: Optional[ImageAnalysis],
    ) -> Dict[str, Any]:
        if not self.openai:
            return self.generate_fallback_answer(question, task_type, rows, sparse, image_analysis)
        if not rows:
            return self.generate_fallback_answer(question, task_type, rows, sparse, image_analysis)

        source_context = [
            {
                "id": str(row["id"]),
                "source_type": row.get("source_type"),
                "title": row.get("title"),
                "content": (row.get("content") or "")[:800],
                "likes_count": row.get("likes_count"),
                "saves_count": row.get("saves_count"),
            }
            for row in rows[:12]
        ]
        schema = {
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
                            "source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["text", "source_ids"],
                    },
                },
                "material_references": {"type": "array", "items": {"type": "string"}},
                "team_history_references": {"type": "array", "items": {"type": "string"}},
                "image_analysis": {"type": ["object", "null"]},
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
            "required": ["conclusion", "recommendations", "material_references", "team_history_references", "image_analysis", "general_advice"],
        }
        prompt = {
            "question": question,
            "task_type": task_type,
            "sparse": sparse,
            "image_analysis": image_analysis.model_dump() if image_analysis else None,
            "allowed_sources": source_context,
            "rules": [
                "只能引用 allowed_sources 中存在的 id。",
                "每条由内部资料支持的 recommendation 必须带 source_ids。",
                "没有内部证据的建议必须放进 general_advice。",
                "回答要面向小红书留学内容运营，中文输出。",
            ],
        }
        resp = self.openai.responses.create(
            model=OPENAI_TEXT_MODEL,
            instructions="你是小红书留学内容团队的 AI 素材研究员。你必须输出符合 schema 的 JSON。",
            input=json.dumps(prompt, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_answer",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return json.loads(resp.output_text)

    def generate_fallback_answer(
        self,
        question: str,
        task_type: str,
        rows: List[Dict[str, Any]],
        sparse: bool,
        image_analysis: Optional[ImageAnalysis],
    ) -> Dict[str, Any]:
        if not rows:
            return {
                "conclusion": "知识库中没有匹配内容。",
                "recommendations": [],
                "material_references": [],
                "team_history_references": [],
                "image_analysis": image_analysis.model_dump() if image_analysis else None,
                "general_advice": [],
            }

        top = rows[:3]
        recommendations = [
            {"text": f"优先参考《{row.get('title') or '无标题'}》的内容角度。", "source_ids": [str(row["id"])]}
            for row in top
        ]
        return {
            "conclusion": "根据当前知识库，下面这些素材和历史内容与问题最相关。" if not sparse else "内部资料匹配较少，可以先参考少量匹配内容，再结合通用创作判断。",
            "recommendations": recommendations,
            "material_references": [str(row["id"]) for row in rows if row.get("source_type") in ("viral_post", "benchmark_post", "topic", "title")],
            "team_history_references": [str(row["id"]) for row in rows if row.get("source_type") == "team_post"],
            "image_analysis": image_analysis.model_dump() if image_analysis else None,
            "general_advice": [{"text": "可用情绪共鸣开头，再给出具体步骤。", "reason": "internal evidence was sparse"}] if sparse else [],
        }

    def _source_types_for_task(self, task_type: str) -> Optional[List[str]]:
        if task_type == "experience":
            return ["team_post", "account"]
        if task_type == "material":
            return ["viral_post", "benchmark_post", "topic", "title"]
        return None

    def _source_shape(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "source_type": row.get("source_type") or "",
            "source_id": row.get("source_id") or "",
            "source_key": row.get("source_key") or "",
            "title": row.get("title") or "",
            "content": row.get("content") or "",
            "summary": row.get("summary"),
            "source_url": row.get("source_url"),
            "country": row.get("country"),
            "tags": row.get("tags") or [],
            "image_urls": row.get("image_urls") or [],
            "likes_count": row.get("likes_count"),
            "saves_count": row.get("saves_count"),
            "comments_count": row.get("comments_count"),
            "views_count": row.get("views_count"),
            "similarity": row.get("similarity"),
            "rrf_score": row.get("rrf_score"),
        }
```

- [ ] **Step 5: Run backend tests**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py test_knowledge_indexer.py
```

Expected: `OK`.

- [ ] **Step 6: Commit service skeleton**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/research_service.py crawler/config.example.py crawler/requirements.txt
git commit -m "feat(ai): add research service skeleton"
```

## Task 5: Register FastAPI Research Endpoints

**Files:**
- Modify: `crawler/ai_api.py`

- [ ] **Step 1: Add imports**

In `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/ai_api.py`, add imports near existing local imports:

```python
from research_models import ResearchRequest
from research_service import ResearchService
```

- [ ] **Step 2: Add endpoints before the `if __name__ == "__main__"` block**

Add:

```python
research_service = ResearchService(sb, embed_texts)


@app.get("/ai/research/health", dependencies=[Depends(require_api_key)])
async def research_health():
    res = (
        sb.table("knowledge_items")
        .select("id", count="exact")
        .eq("is_active", True)
        .execute()
    )
    return {
        "ok": True,
        "active_knowledge_items": res.count or 0,
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
    }


@app.post("/ai/research", dependencies=[Depends(require_api_key)])
async def research(req: ResearchRequest):
    try:
        result = await research_service.research(req)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"research 失败: {e}")
        raise HTTPException(500, "AI 服务暂时不可用，请稍后再试。")
    return result.model_dump()


@app.post("/ai/research-notes", dependencies=[Depends(require_api_key)])
async def save_research_note(payload: Dict[str, Any]):
    try:
        res = sb.table("ai_research_notes").insert([payload]).execute()
    except Exception as e:
        log.error(f"保存 research note 失败: {e}")
        raise HTTPException(500, "保存失败，请稍后重试。")
    rows = res.data or []
    return {"ok": True, "note": rows[0] if rows else None}
```

- [ ] **Step 3: Run import smoke test**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m py_compile ai_api.py research_models.py research_service.py retrieval.py knowledge_indexer.py
```

Expected: command exits with no output.

- [ ] **Step 4: Start AI API and check health**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python ai_api.py
```

In another terminal:

```bash
curl -sS http://127.0.0.1:8001/healthz
```

Expected:

```json
{"ok":true,"embed_model":"voyage-3-lite","embed_dim":512}
```

- [ ] **Step 5: Commit endpoints**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add crawler/ai_api.py
git commit -m "feat(ai): expose research endpoints"
```

## Task 6: Add Frontend AI API Client

**Files:**
- Modify: `.env.example`
- Create: `src/aiApi.js`

- [ ] **Step 1: Update `.env.example`**

Append:

```dotenv

# AI 搜索中心
VITE_AI_API_URL=http://127.0.0.1:8001
VITE_AI_API_KEY=team-internal-secret
```

- [ ] **Step 2: Create client**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/src/aiApi.js`:

```javascript
const BASE_URL = import.meta.env.VITE_AI_API_URL;
const API_KEY = import.meta.env.VITE_AI_API_KEY;

async function postJson(path, body) {
  if (!BASE_URL || !API_KEY) {
    throw new Error("AI API 未配置，请检查 .env 中的 VITE_AI_API_URL 和 VITE_AI_API_KEY");
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || "AI 服务暂时不可用，请稍后再试。");
  }

  return resp.json();
}

export async function research(question, options = {}) {
  return postJson("/ai/research", {
    question,
    image_url: options.imageUrl || null,
    previous_answer_summary: options.previousAnswerSummary || null,
    previous_citation_ids: options.previousCitationIds || [],
  });
}

export async function saveResearchNote(payload) {
  return postJson("/ai/research-notes", payload);
}
```

- [ ] **Step 3: Run frontend build**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit client**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add .env.example src/aiApi.js
git commit -m "feat(ai): add frontend research API client"
```

## Task 7: Add AI Search Center Page

**Files:**
- Create: `src/components/AISearchPage.jsx`

- [ ] **Step 1: Create page component**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/src/components/AISearchPage.jsx`:

```javascript
import { useState } from "react";
import { Bot, Bookmark, Image as ImageIcon, Loader2, Send, Sparkles } from "lucide-react";
import { supabase } from "../supabase.js";
import { research, saveResearchNote } from "../aiApi.js";
import { inputStyle, useIsMobile } from "./shared.jsx";

function SourceCard({ source }) {
  return (
    <div style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 12 }}>
      <div style={{ fontSize: 11, color: "#FF2442", marginBottom: 6 }}>{source.source_type}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#e0e0e0", marginBottom: 6 }}>{source.title || "无标题"}</div>
      <div style={{ fontSize: 12, color: "#666", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {source.summary || source.content || "暂无摘要"}
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 10, fontSize: 11, color: "#444" }}>
        {source.likes_count != null && <span>赞 {source.likes_count}</span>}
        {source.saves_count != null && <span>藏 {source.saves_count}</span>}
        {source.country && <span>{source.country}</span>}
      </div>
    </div>
  );
}

function AnswerView({ answer, onSave, savingNote }) {
  if (!answer) return null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(280px, 0.8fr)", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {answer.message && (
          <div style={{ background: "rgba(255,159,67,0.08)", border: "1px solid rgba(255,159,67,0.18)", borderRadius: 8, padding: 12, color: "#FF9F43", fontSize: 12 }}>
            {answer.message}
          </div>
        )}
        <section style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16 }}>
          <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>简明结论</div>
          <div style={{ fontSize: 16, color: "#fff", lineHeight: 1.7 }}>{answer.conclusion}</div>
        </section>
        <section style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16 }}>
          <div style={{ fontSize: 11, color: "#555", marginBottom: 10 }}>推荐方向</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(answer.recommendations || []).map((rec, idx) => (
              <div key={idx} style={{ background: "#0d0d0d", border: "1px solid #222", borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 13, color: "#ddd", lineHeight: 1.6 }}>{rec.text}</div>
                {rec.source_ids?.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    {rec.source_ids.map(id => <span key={id} style={{ fontSize: 10, color: "#54A0FF" }}>引用 {id.slice(0, 8)}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
        {answer.general_advice?.length > 0 && (
          <section style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 11, color: "#555", marginBottom: 10 }}>通用建议</div>
            {answer.general_advice.map((item, idx) => (
              <div key={idx} style={{ fontSize: 13, color: "#aaa", lineHeight: 1.6, marginBottom: 8 }}>{item.text}</div>
            ))}
          </section>
        )}
        <button onClick={onSave} disabled={savingNote} style={{
          alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8,
          padding: "9px 14px", borderRadius: 8, border: "none",
          background: savingNote ? "#333" : "#FF2442", color: "#fff", cursor: savingNote ? "not-allowed" : "pointer",
          fontSize: 13, fontWeight: 600,
        }}>
          <Bookmark size={15} /> {savingNote ? "保存中…" : "保存结论"}
        </button>
      </div>
      <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {answer.image_analysis && (
          <section style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 14 }}>
            <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>图片分析</div>
            <div style={{ fontSize: 12, color: "#aaa", lineHeight: 1.7 }}>
              {[answer.image_analysis.subject, answer.image_analysis.scene, answer.image_analysis.mood, answer.image_analysis.visual_style, answer.image_analysis.content_direction].filter(Boolean).join(" · ") || "暂无图片分析"}
            </div>
          </section>
        )}
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 11, color: "#555" }}>本次回答引用的素材</div>
          {(answer.cited_sources || []).length === 0
            ? <div style={{ fontSize: 12, color: "#333" }}>暂无引用来源</div>
            : answer.cited_sources.map(source => <SourceCard key={source.id} source={source} />)
          }
        </section>
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 11, color: "#555" }}>其他相关素材</div>
          {(answer.related_sources || []).slice(0, 6).map(source => <SourceCard key={source.id} source={source} />)}
        </section>
      </aside>
    </div>
  );
}

export default function AISearchPage() {
  const isMobile = useIsMobile();
  const [question, setQuestion] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [error, setError] = useState("");

  const uploadImage = async () => {
    if (!imageFile) return null;
    const researchId = crypto.randomUUID();
    const ext = imageFile.name.split(".").pop() || "jpg";
    const path = `ai-research/${researchId}/${Date.now()}.${ext}`;
    const { error: uploadError } = await supabase.storage.from("post-images").upload(path, imageFile);
    if (uploadError) throw new Error("图片上传失败：" + uploadError.message);
    const { data: { publicUrl } } = supabase.storage.from("post-images").getPublicUrl(path);
    return publicUrl;
  };

  const handleSubmit = async () => {
    if (!question.trim()) {
      alert("请先输入问题");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const imageUrl = await uploadImage();
      const result = await research(question.trim(), {
        imageUrl,
        previousAnswerSummary: answer?.conclusion || null,
        previousCitationIds: answer?.cited_sources?.map(s => s.id) || [],
      });
      setAnswer(result);
    } catch (err) {
      setError(err.message || "AI 服务暂时不可用，请稍后再试。");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!answer) return;
    setSavingNote(true);
    try {
      await saveResearchNote({
        user_question: answer.question,
        image_url: answer.image_url || null,
        conclusion: answer.conclusion,
        recommendations: answer.recommendations || [],
        material_references: answer.cited_sources?.filter(s => s.source_type !== "team_post") || [],
        team_history_references: answer.cited_sources?.filter(s => s.source_type === "team_post") || [],
        image_analysis: answer.image_analysis || null,
        full_payload: answer,
        visibility: "team",
      });
      alert("已保存为研究笔记");
    } catch (err) {
      alert(err.message || "保存失败，请稍后重试。");
    } finally {
      setSavingNote(false);
    }
  };

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1200 }}>
      <div style={{ marginBottom: 22 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 5px" }}>AI 搜索中心</h1>
        <p style={{ fontSize: 13, color: "#555", margin: 0 }}>找素材 · 找经验 · 看图找参考</p>
      </div>

      <div style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16, marginBottom: 20 }}>
        <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 8 }}>输入你的素材或经验检索问题</label>
        <textarea
          rows={3}
          value={question}
          onChange={e => setQuestion(e.target.value)}
          style={{ ...inputStyle, resize: "vertical", lineHeight: 1.6 }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#666", fontSize: 13, cursor: "pointer" }}>
            <ImageIcon size={15} />
            <span>{imageFile ? imageFile.name : "上传图片（可选）"}</span>
            <input type="file" accept="image/*" style={{ display: "none" }} onChange={e => setImageFile(e.target.files?.[0] || null)} />
          </label>
          <button onClick={handleSubmit} disabled={loading} style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "10px 18px", borderRadius: 8, border: "none",
            background: loading ? "#333" : "#FF2442", color: "#fff",
            cursor: loading ? "not-allowed" : "pointer", fontSize: 13, fontWeight: 700,
          }}>
            {loading ? <Loader2 size={15} /> : <Send size={15} />}
            {loading ? "研究中…" : "提问"}
          </button>
        </div>
      </div>

      {error && <div style={{ background: "rgba(255,36,66,0.08)", border: "1px solid rgba(255,36,66,0.2)", color: "#FF2442", borderRadius: 8, padding: 12, marginBottom: 16, fontSize: 13 }}>{error}</div>}

      {!answer && !loading && (
        <div style={{ border: "1px dashed #222", borderRadius: 8, padding: "42px 20px", textAlign: "center", color: "#444" }}>
          <Bot size={26} />
          <div style={{ fontSize: 13, marginTop: 10 }}>输入问题后，AI 会从素材库和团队历史内容里找依据。</div>
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#555", fontSize: 13 }}>
          <Sparkles size={16} /> 正在检索知识库并整理回答…
        </div>
      )}

      <AnswerView answer={answer} onSave={handleSave} savingNote={savingNote} />
    </div>
  );
}
```

- [ ] **Step 2: Run build**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: build succeeds if `src/aiApi.js` exists from Task 6.

- [ ] **Step 3: Commit page**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add src/components/AISearchPage.jsx
git commit -m "feat(ai): add AI search center page"
```

## Task 8: Wire Top-Level Navigation

**Files:**
- Modify: `src/App.jsx`

- [ ] **Step 1: Add icon and import**

In `/Users/gabriel/Projects/archive/xhs-dashboard/src/App.jsx`, change the lucide import to include `Sparkles`:

```javascript
import { FileText, Users2, CalendarDays, BookOpen, BarChart2, Plus, X, UserCircle, Sparkles } from "lucide-react";
```

Add page import:

```javascript
import AISearchPage from "./components/AISearchPage.jsx";
```

- [ ] **Step 2: Add nav item**

Add this item after `material` and before `analytics`:

```javascript
{ key: "ai", icon: <Sparkles size={20} />, label: "AI 搜索" },
```

- [ ] **Step 3: Add route branch**

Add this branch in main content:

```javascript
{view === "ai" && <AISearchPage />}
```

- [ ] **Step 4: Run build**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit navigation**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add src/App.jsx
git commit -m "feat(ai): add AI search navigation"
```

## Task 9: Add Eval Template And Runner

**Files:**
- Create: `docs/superpowers/evals/ai-knowledge-golden-set.example.json`
- Create: `crawler/eval_research.py`

- [ ] **Step 1: Create golden-set example**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/docs/superpowers/evals/ai-knowledge-golden-set.example.json`:

```json
[
  {
    "id": "q001",
    "question": "帮我找适合英国留学申请焦虑方向的素材",
    "expected_source_ids": [],
    "good_answer": "应该召回英国、申请焦虑、文书或时间线相关素材，并说明标题/内容方向。",
    "difficulty": "semantic"
  },
  {
    "id": "q002",
    "question": "我们过去写过哪些文书相关内容比较容易出收藏？",
    "expected_source_ids": [],
    "good_answer": "应该优先返回 team_post，并参考 saves_count 排序。",
    "difficulty": "cross-source"
  }
]
```

- [ ] **Step 2: Create eval runner**

Create `/Users/gabriel/Projects/archive/xhs-dashboard/crawler/eval_research.py`:

```python
#!/usr/bin/env python3
import argparse
import json
from typing import List

from supabase import create_client

from config import SUPABASE_KEY, SUPABASE_URL


def recall_at_k(returned: List[str], expected: List[str], k: int = 10) -> float:
    if not expected:
        return 0.0
    hits = set(returned[:k]) & set(expected)
    return len(hits) / len(set(expected))


def reciprocal_rank(returned: List[str], expected: List[str]) -> float:
    expected_set = set(expected)
    for index, item_id in enumerate(returned, start=1):
        if item_id in expected_set:
            return 1.0 / index
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("golden_set")
    args = parser.parse_args()

    with open(args.golden_set, "r", encoding="utf-8") as fh:
        questions = json.load(fh)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    recalls = []
    rr = []

    for item in questions:
        words = item["question"].split()
        q = sb.table("knowledge_items").select("id,title,content").eq("is_active", True).limit(10)
        if words:
            first = words[0]
            q = q.or_(f"title.ilike.%{first}%,content.ilike.%{first}%")
        rows = q.execute().data or []
        returned = [row["id"] for row in rows]
        expected = item.get("expected_source_ids") or []
        recalls.append(recall_at_k(returned, expected))
        rr.append(reciprocal_rank(returned, expected))

    report = {
        "questions": len(questions),
        "recall_at_10": sum(recalls) / len(recalls) if recalls else 0.0,
        "mrr": sum(rr) / len(rr) if rr else 0.0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run eval runner against example**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python eval_research.py ../docs/superpowers/evals/ai-knowledge-golden-set.example.json
```

Expected with empty `expected_source_ids`: report prints `questions`, `recall_at_10`, and `mrr` without crashing.

- [ ] **Step 4: Commit eval tooling**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add docs/superpowers/evals/ai-knowledge-golden-set.example.json crawler/eval_research.py
git commit -m "feat(ai): add research eval template"
```

## Task 10: End-To-End Verification

**Files:**
- Read: all changed files

- [ ] **Step 1: Run backend unit tests**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m unittest test_retrieval.py test_knowledge_indexer.py
```

Expected: `OK`.

- [ ] **Step 2: Run Python compile check**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python -m py_compile ai_api.py research_models.py research_service.py retrieval.py knowledge_indexer.py eval_research.py
```

Expected: no output.

- [ ] **Step 3: Run frontend build**

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Start local services**

Terminal 1:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard/crawler
python ai_api.py
```

Terminal 2:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
npm run dev
```

Expected: Vite prints a localhost URL, usually `http://localhost:5173`.

- [ ] **Step 5: Verify AI API health**

```bash
curl -sS http://127.0.0.1:8001/healthz
```

Expected: JSON includes `"ok": true`.

- [ ] **Step 6: Verify research endpoint**

Replace `team-internal-secret` with the value from `crawler/config.py`:

```bash
curl -sS -X POST http://127.0.0.1:8001/ai/research \
  -H "Content-Type: application/json" \
  -H "X-API-Key: team-internal-secret" \
  -d '{"question":"帮我找适合英国留学申请焦虑方向的素材"}'
```

Expected: JSON includes `conclusion`, `recommendations`, `related_sources`, and no fabricated citation ids.

- [ ] **Step 7: Verify browser flow**

Open Vite URL, click `AI 搜索`, ask `帮我找适合英国留学申请焦虑方向的素材`.

Expected:

- Page shows loading state.
- Answer renders or shows a Chinese sparse/empty knowledge message.
- Citation cards render when sources exist.
- Save action stores an `ai_research_notes` row or shows a Chinese error without losing the answer.

- [ ] **Step 8: Commit final verification notes if docs changed**

If verification discovers setup details that future developers need, update this plan or `README.md`, then commit:

```bash
cd /Users/gabriel/Projects/archive/xhs-dashboard
git add docs/superpowers/plans/2026-05-09-ai-knowledge-search-center.md README.md
git commit -m "docs(ai): document research verification steps"
```
