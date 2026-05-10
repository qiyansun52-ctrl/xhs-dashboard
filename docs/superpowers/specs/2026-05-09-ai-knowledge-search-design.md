# AI Knowledge Search Center Design

## Summary

Add a standalone `AI 搜索中心` module to the XHS operations dashboard. Version one is an `AI 素材研究员`: a bounded question-answering research assistant that helps operators find usable materials and historical team experience from the existing material library and team posts.

The assistant supports optional image input, grounds important claims in source records, and lets users save the result as a lightweight research note. The first AI workflow should optimize for trust, traceability, and reuse rather than broad automation.

## 1. Product Positioning

### 1.1 Current Dashboard Role

The existing dashboard records and coordinates accounts, posts, schedules, analytics, and material-library data. The data already represents team memory, but users still have to manually browse and remember where useful material lives.

### 1.2 AI Search Center Role

The AI Search Center turns stored operational data into a natural-language team memory.

Version one focuses on two jobs:

- `找素材`: retrieve relevant viral posts, benchmark posts, topics, title ideas, and other material-library references.
- `找经验`: retrieve relevant team historical posts, titles, captions, tags, account positioning, and past content patterns.

`找结论` and trend-analysis agents are out of scope for version one. They depend on a stable material and experience retrieval layer and should become a separate analytics/agent product later.

### 1.3 Relationship To Material Library

The AI Search Center is not a Material Library tab. The Material Library is where source data is collected and maintained. The AI Search Center is where that data is used through questions, citations, and saved research notes.

## 2. Users And Use Cases

### 2.1 Primary Users

Primary users are non-technical content operators managing Xiaohongshu accounts for overseas-student audiences.

### 2.2 Core Questions

Version one should answer questions like:

- "帮我找适合英国留学申请焦虑方向的素材。"
- "我们过去写过哪些文书相关内容比较容易出收藏？"
- "结合这张图，帮我找相似参考，并给标题、内容、tag 建议。"
- "只参考团队历史内容，给我几个可以复用的标题结构。"

### 2.3 Experience Goal

The assistant should feel like a research partner: concise enough for fast daily use, but grounded enough that every important conclusion can be inspected against the original evidence.

It should not write final publishable copy in version one. It helps users make better content decisions.

## 3. Product Shape

### 3.1 Entry Point

Add `AI 搜索中心` as a top-level navigation item, beside account management, content management, calendar, material library, and analytics.

### 3.2 Main Interaction

- A single prompt box accepts text and optional image upload.
- The answer renders in a fixed structure.
- Users can ask follow-up questions in the same working context.
- Each answer can be saved as a research note.

Follow-up context should stay lightweight in version one. The frontend sends the latest answer summary, latest citations, and the new user question to `POST /ai/research`. Each follow-up should still perform a fresh retrieval pass, using the prior answer only as query context. Do not add a persistent chat-thread table yet.

### 3.3 Non-Product Behavior

Version one should not:

- replace manual browsing in the Material Library
- create official posts
- schedule posts
- assign tasks
- behave like a broad open-ended chatbot

Out-of-domain questions should be politely rejected with a clear boundary message.

## 4. Agent Behavior

### 4.1 Principle

Version one is a bounded question-answering agent. Its actions are enumerable and auditable.

### 4.2 Processing Flow

1. Receive the user's question and optional image URL.
2. Classify the task as material search, experience search, image-reference search, or mixed request.
3. If an image is present, run image understanding first and extract structured signals.
4. Build retrieval queries from the user question, task type, and image signals.
5. Retrieve from `knowledge_items`.
6. Rank results with task-aware rules.
7. Generate a structured answer with `source_ids` attached to claims.
8. Validate citations before returning the answer.
9. Let the user save the answer as a lightweight research note.

### 4.3 Knowledge-First Rule

- Prefer internal knowledge.
- If internal evidence is weak, explicitly say `内部资料匹配较少`.
- Only then add a small amount of general creative advice.
- Never present generic advice as if it were supported by internal sources.

### 4.4 Out-Of-Scope Questions

If the question is unrelated to operations, content, materials, accounts, or Xiaohongshu workflow, return a short boundary response instead of answering.

Example: "这个助手主要用于查找素材、历史内容和图片参考。这个问题不在当前能力范围内。"

## 5. Answer Structure

Every answer uses a predictable structure. Conditional sections should be omitted only when not applicable; when applicable but empty, explicitly explain that no matching source was found.

| Section | Content | Required |
| --- | --- | --- |
| `简明结论` | 2-4 sentences answering the user's question | required |
| `推荐方向` | title directions, content angles, tag suggestions | required |
| `参考素材` | cited material-library results | required when retrieved; otherwise say none found |
| `历史经验` | cited team-history results | required when retrieved; otherwise say none found |
| `图片分析` | subject, scene, mood, style, content direction | only when an image is uploaded |
| `保存结论` | action to save answer and citations as a note | required |

### 5.1 Citations As Product Contract

Any specific claim in `推荐方向`, `参考素材`, or `历史经验` that is supported by internal knowledge must carry citations. Uncited text must be clearly separated as `通用建议`.

### 5.2 Referenced vs Related Sources

Render sources in two groups:

- `本次回答引用的素材`: sources actually cited by the generated answer.
- `其他相关素材`: retrieved but uncited sources, shown as secondary exploration material.

This keeps the main answer readable while still exposing useful adjacent results.

## 6. Knowledge And Retrieval

### 6.1 Indexed Sources

| `source_type` | Source | Notes |
| --- | --- | --- |
| `viral_post` | `viral_posts` | title, caption, cover, images, likes/saves/comments/views, country, tags, source URL |
| `benchmark_account` | `benchmark_accounts` | account name, bio, destination, content type, followers, fetch status |
| `benchmark_post` | `benchmark_accounts.recent_posts` | one indexed item per recent post, linked back to parent account |
| `topic` | `topics` | description, tag, reference URL, reference metrics |
| `title` | `titles` | title text and metadata |
| `team_post` | `posts` | team historical posts, caption, tags, status, images, account, uploader |
| `team_post_stats` | `post_stats` / `post_stats_history` | likes, saves, comments, views, shares, collected time for ranking `team_post` |
| `account` | `accounts` | account name, avatar, flag/country, bio, color, positioning context |
| `banned_word` | `banned_words` | risk reminders only, not primary retrieval results |

Documents such as SOPs, retrospectives, and operating notes are out of scope for version one.

### 6.2 Unified Index: `knowledge_items`

Frontend code should not search many business tables directly. All AI retrieval goes through `knowledge_items`. Source tables remain the source of truth; `knowledge_items` is a rebuildable AI index.

Recommended fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `source_type` | text/enum | values from section 6.1 |
| `source_id` | text | original source record id |
| `source_key` | text | stable unique key within `source_type` |
| `parent_source_type` | text nullable | used by nested records such as `benchmark_post` |
| `parent_source_id` | text nullable | parent source id |
| `source_url` | text nullable | URL or app deep-link target for citation UI |
| `title` | text | display title |
| `content` | text | retrieval text |
| `summary` | text nullable | short generated summary for answer context |
| `tags` | text[] | business tags |
| `country` | text nullable | country/destination/audience label |
| `account_id` | integer nullable | current `accounts.id` is serial integer |
| `language` | text | `zh`, `en`, or `mixed` |
| `content_type` | text nullable | image-heavy, text-heavy, video, account, topic, title |
| `likes_count` | bigint nullable | NULL means unknown; 0 means truly zero |
| `saves_count` | bigint nullable | same semantics |
| `comments_count` | bigint nullable | same semantics |
| `views_count` | bigint nullable | same semantics |
| `metrics_extra` | jsonb | non-standard metrics |
| `image_urls` | text[] | associated images |
| `embedding` | vector | pgvector embedding |
| `embedding_model_version` | text | supports gradual migration between models |
| `embed_status` | text/enum | `pending`, `processing`, `completed`, `failed` |
| `embed_error` | text nullable | failure reason |
| `retry_count` | int | embedding retry counter |
| `is_active` | bool | soft delete / search visibility |
| `published_at` | timestamptz nullable | source publication time |
| `source_updated_at` | timestamptz nullable | source table update time |
| `content_hash` | text | changes when indexed content changes |
| `last_indexed_at` | timestamptz nullable | last sync time |
| `created_at` | timestamptz | index row creation time |
| `updated_at` | timestamptz | index row update time |

Recommended indexes:

- HNSW or IVFFlat on `embedding`.
- Unique index on `(source_type, source_key)`.
- B-tree indexes on `(source_type, is_active)`, `(country, is_active)`, `(account_id)`.
- GIN index on `tags`.

### 6.3 Chunking Strategy

Use natural business boundaries first:

- `viral_post`, `benchmark_post`, `team_post`: one post becomes one `knowledge_item`. `content = title + "\n\n" + caption`; tags and image description can be appended as supporting text. If caption is very long, split into child chunks that share the same source metadata.
- `benchmark_account`: account itself and recent posts are separate items. Recent posts use `source_type = benchmark_post`, `parent_source_id = benchmark_account.id`, and `source_key = account_id + ":" + note_id` when `note_id` exists.
- `topic`: index `description` as content. Do not crawl arbitrary third-party `reference_url` content in version one.
- `title`: index as a lightweight item, but apply lower ranking weight because a title alone lacks context.
- `account`: index bio and positioning context, mainly for questions about persona and account fit.

### 6.4 Retrieval Strategy

#### 6.4.1 Hybrid Retrieval With RRF

Version one should use Reciprocal Rank Fusion (RRF) to merge:

- semantic vector retrieval
- keyword candidates from title/content/tag/country/source_type matching
- structured filters inferred from the query

Do not depend on default PostgreSQL full-text search for Chinese unless a suitable tokenizer is configured. Simple title/caption substring, tag matching, and structured filters are enough for the first keyword path.

RRF is recommended because it avoids score-scale conflicts between vector and keyword retrieval during cold start. Cross-encoder reranking is a future upgrade after enough feedback data exists.

#### 6.4.2 Embedding Model

The current AI prototype uses `voyage-3-lite` with 512 dimensions. Version one can continue from that implementation for continuity, but every index row must record `embedding_model_version`.

Before switching model families, run the golden eval set. Future candidates include `bge-m3` for self-hosted multilingual retrieval or OpenAI `text-embedding-3-large` for faster managed integration. Do not switch models based on preference alone; switch only if eval quality or operational constraints justify it.

#### 6.4.3 Task-Aware Ranking

Different task types should use different ranking rules:

| Task Type | Ranking Rule |
| --- | --- |
| material search | relevance -> performance metrics -> source completeness -> freshness; boost `viral_post` and `benchmark_post` |
| experience search | relevance -> `team_post` first -> freshness -> performance metrics |
| image reference | image-signal match -> relevance -> performance metrics |
| mixed request | return grouped results: `参考素材` and `历史经验` rank independently |

This is important: `team_post` must not be a weak late-stage signal. If the user asks for experience, team history should be treated as a first-order source constraint or strong boost.

#### 6.4.4 Sparse Recall Thresholds

Version one should define clear sparse-result behavior:

| Condition | Behavior |
| --- | --- |
| 0 retrieved items | say `知识库中没有匹配内容`; do not invent internal evidence |
| fewer than 3 retrieved items | show `内部资料匹配较少` and separate any general advice |
| top score below configured threshold | same sparse-result behavior |
| total active `knowledge_items` < 100 | show a cold-start banner on the page |

Exact thresholds should be tuned with the golden eval set. The implementation should make them config values, not hard-coded magic numbers inside UI code.

### 6.5 Image Workflow

Version one does not use image vector search. It uses VLM-to-text.

Flow:

1. Frontend uploads images to Supabase Storage under `post-images/ai-research/{research_id}/{filename}`. A separate `ai-query-images` bucket can replace this later. Do not mix AI query uploads into formal post image paths.
2. Backend sends the image URL to a VLM.
3. VLM returns structured signals:
   - `subject`
   - `scene`
   - `mood`
   - `visual_style`
   - `content_direction`
   - `keywords` (3-8 terms)
4. Retrieval query assembly:
   - `keywords` feed the keyword candidate path.
   - `subject + scene + mood + content_direction` becomes a natural-language semantic query.
   - Both result sets are merged with RRF.
5. If keywords are too generic and recall is sparse, fall back to the full image description as the semantic query.

If image analysis fails, continue with text-only retrieval and show `图片分析失败，已先基于文字问题回答。`

## 7. Citation Mechanism

### 7.1 Three-Layer Defense

| Layer | Behavior | Goal |
| --- | --- | --- |
| generation | model outputs structured JSON with text separated from `source_ids` | reduce hallucination surface |
| validation | server checks every `source_id` against this request's retrieved set | block fabricated citations |
| UI | uncited claims are labeled as general advice; citations expand to raw source data | let users inspect evidence strength |

### 7.2 Generation Contract

The model must return structured JSON. Example shape:

```json
{
  "conclusion": "string",
  "recommendations": [
    {
      "text": "string",
      "source_ids": ["knowledge_item_uuid"]
    }
  ],
  "material_references": ["knowledge_item_uuid"],
  "team_history_references": ["knowledge_item_uuid"],
  "image_analysis": null,
  "general_advice": [
    {
      "text": "string",
      "reason": "internal evidence was sparse"
    }
  ]
}
```

`source_ids` may only reference ids from the current retrieved set. The system instruction and response schema must both state this.

### 7.3 Validation Contract

Before returning to the frontend, the AI API must run citation validation:

1. Existence validation: every `source_id` must exist in the retrieved set for the current request.
2. Invalid citations: remove invalid ids and mark the affected sentence as uncited general advice.
3. Empty cited claims: if a recommendation loses all citations and is not allowed as general advice, either drop it or ask the model to regenerate once.
4. Support validation: reserve an interface for claim-support checks. Version one only requires existence validation; v1.1 can add rule-based or model-based support checks.

If the model produces citation ids that do not exist, never display them.

### 7.4 UI Citation Behavior

- Cited claims show clickable citation chips.
- Expanded citations show title, source type, cover/image, key metrics, source URL or app target, and a short excerpt.
- Uncited general advice is visually separated and labeled.
- `其他相关素材` is shown below the answer as secondary exploration material.

## 8. Research Notes

### 8.1 Table: `ai_research_notes`

Recommended fields:

| Field | Notes |
| --- | --- |
| `id` | uuid |
| `user_question` | original question |
| `image_url` | uploaded image URL, if any |
| `conclusion` | short answer |
| `recommendations` | title/content/tag suggestions |
| `material_references` | cited material sources with snapshots |
| `team_history_references` | cited team-history sources with snapshots |
| `image_analysis` | structured VLM result |
| `full_payload` | complete answer JSON |
| `user_note` | optional user note |
| `creator_id` | member id when available |
| `visibility` | `team` for version one |
| `created_at` | created time |

### 8.2 Citation Snapshot Rule

When saving a note, store a snapshot of each citation: title, image, key metrics, source type, and source URL. This preserves the research context even if a source is deleted or metrics later change.

### 8.3 Boundary With Formal Content

Research notes do not create official posts, update schedules, or appear in content management. They are research artifacts.

## 9. Evaluation Plan

### 9.1 Offline Golden Set

Before launch, create a golden set of 50-100 real questions.

Source:

- 1-2 operators provide real questions they have manually researched before.
- Include questions the AI should answer once the knowledge base is indexed.

Each question should include:

- expected relevant `knowledge_item.id` values
- a one-sentence definition of a good answer
- difficulty label: keyword/easy, semantic/medium, cross-source/hard

### 9.2 Offline Metrics

- Retrieval: Recall@10 and MRR. Version-one launch target: Recall@10 >= 0.7.
- Generation: human review on correctness, citation support, and hallucination.
- Release gate: manual sampled review is required; LLM-as-judge can assist but cannot be the sole release decision.

### 9.3 Online Metrics

| Metric | Meaning |
| --- | --- |
| save-to-note conversion rate | strongest usefulness proxy |
| citation click rate | whether users inspect evidence |
| follow-up count per session | high values can indicate first-answer gaps |
| sparse-result rate | knowledge coverage signal |
| zero-recall rate | priority signal for indexing/source improvements |
| negative feedback rate | quality regression signal |

### 9.4 Feedback Loop

Every answer should support a lightweight feedback action: thumbs up/down plus optional reason such as `结论错`, `引用不支持`, `不相关`, or `不够具体`.

This data should feed future reranker and prompt improvements.

## 10. Technical Architecture

### 10.1 Existing Stack

- Frontend: React + Vite, inline styles.
- Database: Supabase Postgres + pgvector.
- Storage: Supabase Storage.
- Realtime: Supabase Realtime.
- AI service: Python AI API initially co-deployed with the crawler.

### 10.2 Components

| Component | Responsibility |
| --- | --- |
| AI Search Center page | prompt, image upload, answer rendering, citation expansion, note saving |
| `POST /ai/research` | task understanding, image analysis, retrieval, generation, validation, structured response |
| `POST /ai/research-notes` | save research note |
| `knowledge_items` | unified retrieval surface |
| `ai_research_notes` | saved answer storage |
| index worker | sync source tables to `knowledge_items` and embeddings |
| eval runner | manually run golden set and generate quality report |

### 10.3 Request Flow

1. User submits question and optional image.
2. Frontend uploads image to Storage when present.
3. Frontend calls `POST /ai/research`.
4. Backend runs task classification, image analysis, retrieval, ranking, generation, citation validation.
5. Frontend renders structured answer, citations, and related sources.
6. User saves result through `POST /ai/research-notes`.

## 11. Index Sync Mechanism

### 11.1 Trigger Strategy

Primary path: application-level event plus async queue.

- On source-table insert/update, application code writes an `index_jobs` row.
- The index worker consumes jobs, builds content, calls embedding API, and upserts `knowledge_items`.

Fallback path: a low-frequency full reconciliation job detects missed changes.

Do not use database triggers that directly call external AI services. They couple database transactions to external network calls and make failures harder to debug.

### 11.2 Latency Targets

| Event | Target |
| --- | --- |
| source insert/update | P95 searchable within 60 seconds |
| source deactivate/delete | P95 hidden from search within 5 seconds |

Deletion should be implemented as soft deletion first: set `knowledge_items.is_active = false`; do not recompute embeddings.

### 11.3 Failure Handling

- Embedding failure: exponential backoff, max 3 retries, then `embed_status = failed`.
- Source deleted: soft delete index row; cleanup can happen later.
- State machine: `pending -> processing -> completed` or `failed`.
- Stuck `processing` jobs should be recoverable by age-based timeout.

### 11.4 Full Rebuild

Version one must include an executable full rebuild script or admin command. It does not need UI.

Required use cases:

- embedding model migration
- schema backfill
- recovery after indexing bugs

## 12. Error Handling

All user-facing errors must be in Chinese.

| State | Message |
| --- | --- |
| AI service unavailable | `AI 服务暂时不可用，请稍后再试。` |
| knowledge index not ready | `知识库正在准备中，稍后再搜索。` |
| image analysis failed | `图片分析失败，已先基于文字问题回答。` |
| sparse recall | `内部资料匹配较少，以下建议包含少量通用创作建议。` |
| zero recall | `知识库中没有匹配内容。` |
| save failed | `保存失败，请稍后重试。` |
| network error | `网络异常，请稍后重试。` |
| out-of-scope question | `这个助手主要用于查找素材、历史内容和图片参考。这个问题不在当前能力范围内。` |

Generated answers should not disappear after save or network errors.

## 13. Known Constraints And Technical Debt

1. AI API and crawler are initially co-deployed. This is acceptable for version one but couples crawling reliability with inference latency and scaling. Split into a dedicated AI service in a later version.
2. Image support uses VLM-to-text, not image vectors. Generic image keywords can weaken retrieval.
3. No cross-encoder reranker in version one. RRF is the first ranking layer.
4. Citation support validation only performs existence validation in version one. Stronger claim-support validation is reserved for v1.1.
5. SOPs, retrospectives, and operating documents are out of scope for version one.
6. Research-note visibility is team-wide in version one because the product has no complex permission system yet.

## 14. Non-Goals For Version One

- automatic official post creation
- automatic scheduling
- task assignment
- trend/conclusion agent
- document/SOP knowledge base
- image vector search
- open-ended chatbot behavior
- complex permissions
- multi-agent automation

## 15. Success Criteria

Measurable launch criteria:

- Retrieval: golden set Recall@10 >= 0.7.
- Generation: 30-sample human review shows answer correctness >= 80%.
- Citation trust: 30-sample human review shows citation relevance >= 85%.
- Hallucination: 30-sample human review shows no-hallucination rate >= 90%.
- Adoption: within 4 weeks, saved-note conversion rate >= 15%.
- Coverage: zero-recall rate <= 10% after initial indexing is complete.

Qualitative criteria:

- Weak internal evidence is explicitly disclosed.
- Users can inspect source records behind important claims.
- Research notes save useful context without creating official content records.
- Existing Material Library and Content Management workflows are not disrupted.

## 16. Future Roadmap

1. Saved research notes become reusable team knowledge.
2. Add document sources such as SOPs, retrospectives, and operating notes.
3. Convert research notes into topics or title ideas.
4. Add content drafting after the research workflow proves reliable.
5. Build trend/conclusion agents as a separate analytics product.
6. Add account-persona matching.
7. Add cross-encoder reranking.
8. Upgrade citation support validation from existence checks to claim-support checks.
