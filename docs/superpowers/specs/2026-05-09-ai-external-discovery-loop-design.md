# AI External Discovery Loop Design

## Summary

Extend `AI 搜索中心` with an external discovery loop for sparse internal recall.
When the internal knowledge base cannot support a strong answer, the assistant can trigger a Xiaohongshu discovery task, use newly crawled external hot posts for a clearly labeled temporary answer, and present those posts for human review before they are allowed into the official material library and `knowledge_items`.

The goal is not to let AI auto-grow the knowledge base. The goal is to let AI notice knowledge gaps, collect candidate evidence, help operators make a first-pass decision, and keep the final knowledge boundary under human control.

## 1. Product Positioning

### 1.1 Current State

The current `AI 搜索中心` is a bounded research assistant. It can retrieve from `knowledge_items`, generate a cited answer, and save a research note. It is agent-like because it performs a multi-step workflow, but it is not yet a full agentic loop: it does not choose follow-up tools based on weak results, create long-running tasks, recover from task failure, or expand its own source pool.

### 1.2 New Role

The external discovery loop adds one bounded autonomous behavior:

1. Detect that internal retrieval is weak.
2. Ask for or receive user permission to search Xiaohongshu externally.
3. Create a discovery job.
4. Let the crawler fetch candidate hot posts through keyword search and benchmark-account expansion.
5. Use those candidates for a temporary answer with clear provenance labels.
6. Require human review before any candidate becomes official knowledge.

This makes the assistant closer to a real domain agent, while keeping important decisions auditable.

### 1.3 Non-Goals

- Do not automatically insert external posts into `knowledge_items`.
- Do not schedule content or create official team posts.
- Do not crawl indefinitely or run broad open-ended Xiaohongshu exploration.
- Do not answer as if unreviewed external candidates are team knowledge.
- Do not bypass rate limits, manual review, or crawl safety controls.

## 2. User Experience

### 2.1 Trigger Behavior

When `/ai/research` detects sparse internal results, it should always return an immediate conservative answer first. External discovery is additive; it should not block the first response.

The product supports two trigger modes:

| Mode | Behavior | Recommended Use |
| --- | --- | --- |
| `ask_first` | show a `去小红书找参考` action; create the job only after user clicks | safest default while validating crawler quality |
| `auto_after_sparse` | create the discovery job immediately after returning the internal answer | useful once rate limits and result quality are trusted |

In both modes, candidates are only temporary external references until a human approves them.

For `ask_first`, the answer should show:

```text
内部资料匹配较少，我先给出保守建议。
可以去小红书搜索相关热门内容，找到后会作为待审核外部素材展示。
```

The user can then click `去小红书找参考`.

For `auto_after_sparse`, the answer should show:

```text
内部资料匹配较少，我先给出保守建议。
已创建小红书外部发现任务，找到的内容会作为待审核外部素材展示。
```

The implementation should start with `ask_first` as the default and keep `auto_after_sparse` behind a config flag. This gives the team the behavior they want without letting an early crawler bug create too many jobs.

### 2.2 Discovery Progress

After the user confirms, the AI page shows a job card:

- `准备搜索关键词`
- `正在搜索小红书热门内容`
- `正在扩展对标账号`
- `正在整理候选素材`
- `发现完成`
- `发现失败`

The user can continue reading the internal fallback answer while discovery runs.

### 2.3 Temporary External Answer

When discovery completes, the page shows a new section:

```text
外部补充参考（待审核）
以下内容来自本次小红书外部发现，尚未进入团队知识库。
```

The assistant can generate a supplemental answer from the candidate posts, but every claim sourced from these posts must be labeled as external and pending review.

The answer should not merge external candidates into the normal `本次回答引用的素材` group. It should use a separate group called `待审核外部素材`.

### 2.4 Human Review Actions

Each candidate card supports:

- `通过并入库`: create or update a `viral_posts` record and enqueue it for indexing.
- `忽略`: hide this candidate from the current workflow.
- `不相关`: mark as rejected and store the reason for future ranking improvements.

Only `通过并入库` makes the item eligible for `knowledge_items` and future internal citations.

## 3. Discovery Strategy

### 3.1 Combined Search Path

Use two discovery paths together:

1. Keyword search from the user question.
2. Expansion from existing benchmark accounts.

Keyword search provides breadth. Benchmark-account expansion provides quality anchors from accounts the team already considers relevant.

### 3.2 Keyword Extraction

The backend extracts 3-6 Xiaohongshu search queries from:

- user question
- task type
- optional image analysis keywords
- previous answer summary when present
- internal sparse-result titles, if any weak matches exist

Example:

```json
{
  "question": "英国申请焦虑方向有什么爆款素材？",
  "queries": [
    "英国留学 申请焦虑",
    "英国申请 文书焦虑",
    "留学申请 崩溃",
    "英国留学 offer 焦虑"
  ]
}
```

Queries should be short, Chinese-first, and suitable for Xiaohongshu search. Do not generate dozens of variants.

### 3.3 Benchmark Account Expansion

The crawler also selects relevant `benchmark_accounts` by:

- destination/country match
- content type match
- note direction match
- recent fetch status
- follower count or historical usefulness

For each selected account, the crawler refreshes recent posts and ranks them by interaction metrics.

### 3.4 Ranking Candidate Hot Posts

Candidate ranking should combine:

- semantic match to the original question
- keyword hit count
- likes, saves, comments, and views
- source path, with benchmark-account expansion getting a small trust boost
- freshness when available
- duplicate suppression by `xhs_note_id` or URL

Saves should matter more than likes because the team uses high-save content as stronger material signal.

Recommended score shape:

```text
candidate_score =
  relevance_score * 0.45
+ normalized_saves * 0.25
+ normalized_comments * 0.12
+ normalized_likes * 0.10
+ benchmark_trust_boost * 0.05
+ freshness_boost * 0.03
```

Exact weights can change after real data review, but the first implementation should keep them centralized in one scoring helper.

## 4. Data Model

### 4.1 `external_discovery_jobs`

This table represents one external discovery attempt triggered from AI Search.

Recommended fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `user_question` | text | original user question |
| `task_type` | text | material, experience, image_reference, mixed |
| `trigger_reason` | text | sparse_recall, zero_recall, user_requested |
| `internal_answer_payload` | jsonb | fallback/internal answer snapshot |
| `search_queries` | text[] | generated Xiaohongshu queries |
| `benchmark_account_ids` | uuid[] | selected benchmark accounts |
| `status` | text | pending, running, completed, failed, cancelled |
| `error_message` | text | failure reason |
| `created_by_member_id` | uuid nullable | future auth/member link |
| `created_at` | timestamptz | creation time |
| `started_at` | timestamptz | crawler started time |
| `finished_at` | timestamptz | crawler finished time |

RLS follows the current internal-tool pattern for version one: team-wide read/write. If auth is later introduced, review/approval writes should become member-scoped.

### 4.2 `external_discovery_candidates`

This table stores unreviewed external posts discovered by a job.

Recommended fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `job_id` | uuid | references `external_discovery_jobs(id)` |
| `source_path` | text | keyword_search or benchmark_expansion |
| `search_query` | text nullable | query that found the post |
| `benchmark_account_id` | uuid nullable | source account when applicable |
| `xhs_note_id` | text nullable | stable dedupe key when available |
| `url` | text | source URL |
| `title` | text | crawled title |
| `caption` | text | crawled caption |
| `cover_image` | text | rehosted image URL |
| `images` | text[] | rehosted image URLs |
| `tags` | text[] | crawled tags |
| `author_name` | text | Xiaohongshu author |
| `likes` | int | latest count |
| `saves` | int | latest count |
| `comments` | int | latest count |
| `views` | int | latest count |
| `candidate_score` | float | ranking score |
| `ai_reason` | text | why this candidate may help |
| `review_status` | text | pending, approved, ignored, rejected |
| `review_reason` | text | optional reviewer reason |
| `approved_viral_post_id` | uuid nullable | linked `viral_posts.id` after approval |
| `created_at` | timestamptz | creation time |
| `reviewed_at` | timestamptz | review time |

Add a unique constraint on `(job_id, url)` and a broader dedupe index on `xhs_note_id` where not null.

### 4.3 Formal Ingestion After Approval

When a candidate is approved:

1. Insert or upsert into `viral_posts`.
2. Set `fetch_status = 'done'`.
3. Preserve `source_url`, images, metrics, tags, author, and country when available.
4. Store a backlink from `external_discovery_candidates.approved_viral_post_id`.
5. Enqueue or trigger knowledge indexing so the item becomes a `knowledge_items` row.

The candidate remains as review history even after approval.

## 5. Backend Behavior

### 5.1 AI API Additions

Add endpoints:

| Endpoint | Purpose |
| --- | --- |
| `POST /ai/discovery-jobs` | create a job from a sparse AI answer |
| `GET /ai/discovery-jobs/{id}` | get job status and candidates |
| `POST /ai/discovery-jobs/{id}/supplement` | generate external supplemental answer |
| `POST /ai/discovery-candidates/{id}/approve` | approve and ingest candidate |
| `POST /ai/discovery-candidates/{id}/ignore` | ignore candidate |
| `POST /ai/discovery-candidates/{id}/reject` | reject candidate with reason |

Version one can keep these under the existing AI API key guard.

### 5.2 Relationship To `/ai/research`

`POST /ai/research` should not block while the crawler runs. It should return the internal answer plus enough metadata for the frontend to either offer discovery or display the auto-created job.

Example response additions:

```json
{
  "sparse": true,
  "can_external_discover": true,
  "discovery_trigger_reason": "sparse_recall",
  "suggested_search_queries": ["英国留学 申请焦虑", "英国申请 文书焦虑"],
  "discovery_trigger_mode": "ask_first",
  "discovery_job_id": null
}
```

When `discovery_trigger_mode = "ask_first"`, the frontend creates the job after user confirmation. When it is `auto_after_sparse`, the backend may return a non-null `discovery_job_id` for a job that has already been created.

### 5.3 Crawler Additions

Extend `crawler/server.py` with a discovery poller:

1. Select `external_discovery_jobs.status = 'pending'`.
2. Mark job `running`.
3. Run keyword search queries through MediaCrawler or Xiaohongshu client capabilities.
4. Refresh/select relevant benchmark accounts.
5. Fetch full details for candidate posts.
6. Rehost images to Supabase Storage.
7. Upsert candidates.
8. Mark job `completed` or `failed`.

If the installed MediaCrawler checkout lacks a direct keyword-search helper, create a thin adapter that calls the same Xiaohongshu search endpoint MediaCrawler uses internally. Keep this adapter isolated so future MediaCrawler updates only touch one file.

### 5.4 Failure Handling

| Failure | Behavior |
| --- | --- |
| Search endpoint unavailable | mark job failed with Chinese error |
| Login expired | mark job failed and surface re-login instruction |
| Partial candidate fetch failures | keep successful candidates, record skipped count |
| Duplicate candidates | merge by note id or URL |
| No candidates found | mark completed with zero candidates and explain no external match |
| Approval insert fails | keep candidate pending and show retryable error |

Do not discard a job just because some candidates fail.

## 6. Frontend Behavior

### 6.1 AI Search Page States

Add these states to `AISearchPage`:

- internal answer only
- discovery offered
- discovery running
- discovery completed with candidates
- discovery completed with zero candidates
- discovery failed
- candidate approved/ignored/rejected

### 6.2 Candidate Cards

Candidate cards should show:

- cover image
- title
- short caption excerpt
- metrics: likes, saves, comments, views
- source path: keyword search or benchmark account
- AI reason
- source URL
- review controls

Cards should visually differ from normal internal citations. Use labels like `待审核外部素材`.

### 6.3 Supplemental Answer

The external supplemental answer should be rendered below the internal answer. It must include:

- a clear warning that sources are unreviewed
- cited candidate cards
- suggested angles
- a reminder to approve useful candidates before relying on them as team knowledge

Do not save supplemental external references into `ai_research_notes` as official material references unless their review status is approved. If saved before approval, store them in a separate `external_candidate_references` field or inside `full_payload` as pending candidates.

## 7. Review And Knowledge Hygiene

### 7.1 Approval Rules

Approval means:

- this candidate is relevant to the team
- the metrics and content look credible enough
- images and title are acceptable for internal reference
- it is worth making searchable in future AI answers

Approval does not mean the team endorses copying the content.

### 7.2 Rejection Reasons

Use a small fixed list first:

- `不相关`
- `低质量`
- `疑似广告`
- `重复素材`
- `不适合团队调性`
- `数据异常`

These reasons can later train ranking and filtering.

### 7.3 Knowledge Boundary

The UI and API should maintain three source classes:

| Class | Meaning | Can support official AI citation? |
| --- | --- | --- |
| internal knowledge | approved `knowledge_items` | yes |
| external pending candidate | crawled but unreviewed | only in external supplemental answer |
| rejected candidate | reviewed as not useful | no |

This boundary is the main safety mechanism for the feature.

## 8. Safety, Rate Limits, And Abuse Controls

### 8.1 Crawl Limits

Initial limits:

- max 4 keyword queries per job
- max 20 keyword results fetched per job
- max 3 benchmark accounts expanded per job
- max 10 posts per benchmark account
- max 30 final candidates stored per job
- minimum 2 seconds between Xiaohongshu detail requests

These should live in `crawler/config.py` with safe defaults in `config.example.py`.

### 8.2 Duplicate And Loop Prevention

Before creating a new job, check recent jobs with the same normalized question or query set. If a similar job completed recently, offer to reuse its candidates instead of crawling again.

Recommended first threshold: reuse jobs from the last 24 hours when at least two generated search queries match.

### 8.3 Manual Kill Switch

Add a config flag:

```python
EXTERNAL_DISCOVERY_ENABLED = False
EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"
```

Production operators explicitly turn it on after schema setup and crawler validation.

## 9. Evaluation Plan

### 9.1 Discovery Quality

Review at least 20 real sparse-recall questions. Track:

- candidates found per job
- approval rate
- rejection reason distribution
- time from job creation to candidates ready
- supplemental answer usefulness

### 9.2 Launch Criteria

Version one can be used by the team when:

- at least 60% of discovery jobs return one or more relevant candidates
- at least 30% of candidates in sampled jobs are approved
- no unapproved candidates appear in normal internal citations
- approval correctly creates searchable `knowledge_items`
- crawler rate limits avoid login/session instability during testing

## 10. Phased Implementation

### Phase 1: Schema And Manual Job Flow

- Add `external_discovery_jobs`.
- Add `external_discovery_candidates`.
- Add AI API endpoints to create/list jobs.
- Add frontend UI to offer discovery and show empty/running/completed states.
- Do not crawl yet; use manually inserted candidate fixtures for UI validation.

### Phase 2: Crawler Discovery Worker

- Add keyword discovery adapter.
- Add benchmark-account expansion path.
- Add candidate scoring and dedupe.
- Write candidates to Supabase.
- Surface job progress in the AI page.

### Phase 3: Supplemental Answer

- Generate external supplemental answer from candidate set.
- Validate candidate citations against the current job candidates.
- Keep external citations separate from internal citations.

### Phase 4: Human Approval And Indexing

- Add approve/ignore/reject actions.
- Approval inserts into `viral_posts`.
- Approval triggers or queues `knowledge_items` rebuild for that item.
- Add tests to guarantee pending candidates cannot become internal citations.

## 11. Open Implementation Questions

These do not block the design, but should be answered during implementation planning:

1. Which MediaCrawler API or endpoint is safest for keyword search in the installed checkout?
2. Should approved candidates go directly to `viral_posts`, or first appear in Material Library with a visible `来源：AI 外部发现` label?
3. Should discovery jobs be team-visible immediately, or only visible to the triggering operator until candidates are approved?
4. Should rejected candidates suppress future rediscovery globally or only for similar questions?

## 12. Success Criteria

The feature is successful when operators can ask a sparse question, trigger Xiaohongshu discovery, receive useful temporary external references, approve good candidates, and later see those approved candidates appear as normal internal AI citations.

The strongest product signal is not how many posts are crawled. It is how many discovered candidates operators approve and later reuse.
