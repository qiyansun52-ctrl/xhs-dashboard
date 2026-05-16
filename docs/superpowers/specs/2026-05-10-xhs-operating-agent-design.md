# XHS Operating Agent Design

> 首期功能优先级、Agent 工作台 UI/UX 与落地分期见 `docs/superpowers/specs/2026-05-16-ui-visual-polish-design.md` 第 11 节。本文档是能力架构与策略边界的权威来源。

## Summary

Build a semi-automatic, general-purpose Xiaohongshu operations agent for the dashboard.

The agent should help the team research content, plan topics, deconstruct viral posts, draft copy, review risk, analyze comments, monitor benchmarks, review data, and update team memory. It should feel like one `全能小红书 Agent` to users, but internally it should be a controlled orchestrator with specialist skills, explicit tools, evidence gates, human review, and persistent memory.

Version one should not be a black-box autonomous bot. It should be a traceable agent workflow:

```text
Plan -> Tool Call -> Observe -> Decide -> Answer -> Human Review -> Memory Update
```

The agent may search, crawl, analyze, draft, and create review tasks automatically. It must not publish, comment, like, delete, schedule, or permanently ingest external knowledge without human confirmation.

## 1. Product Positioning

### 1.1 Current Product

The current dashboard manages Xiaohongshu accounts, content, calendar, analytics, and material-library data. The AI Search Center is currently a bounded RAG assistant: it searches `knowledge_items`, generates a cited answer, can create external discovery tasks, and can save research notes.

This is useful, but it is still centered on search. A general operating agent should be centered on operator goals.

### 1.2 Target Product

The target product is `XHS Operating Agent`: a single natural-language workbench for Xiaohongshu operations.

It should support goals like:

- "帮我规划下周英国账号内容。"
- "拆一下这 10 篇为什么收藏高。"
- "找最近英国春天相关的爆款素材，不够就去小红书继续找。"
- "把这个选题改成 Jasper_Page 的口吻，给 5 个标题。"
- "检查这篇发之前有没有风险。"
- "总结这篇评论区的用户痛点，给追更选题。"
- "监控英国留学对标账号，这周有新爆款提醒我。"

### 1.3 Semi-Automatic Boundary

The agreed product boundary is semi-automatic.

Automatically allowed:

- understand user goals
- plan subtasks
- search internal knowledge
- query dashboard data
- crawl Xiaohongshu candidate content
- fetch note details and comments
- deconstruct content
- generate drafts
- run risk review
- generate reports and recommendations

Requires human confirmation:

- create external discovery tasks if they may consume crawler quota
- save research conclusions as team notes
- approve external candidates into the knowledge base
- add topics or drafts to the content calendar
- assign work to an account or team member
- mark a post as a team template
- modify existing scheduled content

Forbidden in early versions:

- automatic Xiaohongshu publishing
- automatic comments, likes, favorites, or follows
- automatic deletion of team data
- automatic bulk schedule changes
- treating unreviewed external content as official team knowledge

## 2. Agent Strategy

### 2.1 What Agent Technology To Use

Version one should use a custom orchestrator inside the existing `crawler/ai_api.py` FastAPI service.

The orchestrator should call specialist modules and tools that we control. The LLM may help with planning, summarization, classification, and generation, but deterministic gates decide permissions, evidence quality, and review requirements.

Do not start with a full external multi-agent framework as the core runtime. The current product needs:

- explicit tool boundaries
- simple deployment with the existing dashboard
- auditable database state
- reliable human review
- tight integration with Supabase tables and the existing crawler

External frameworks can still inspire the design:

- OpenAI Agents SDK: useful reference for tools, handoffs, tracing, and guardrails.
- LangChain/LangGraph: useful reference for graph-like workflows and durable agent state.
- LlamaIndex Workflows: useful reference for event-driven RAG and human-in-the-loop flows.
- Xiaohongshu MCP/crawler projects: useful reference for tool adapters, not as product authority.

Decision: implement the first agent runtime ourselves with a small state machine, then keep the interfaces compatible with a future migration to a framework if needed.

### 2.2 One Agent, Many Specialist Skills

Users should see one agent. Internally, the system has specialist skills:

```text
XHS Operating Agent
├── Content Research Skill
├── Topic Planning Skill
├── Viral Deconstruction Skill
├── Content Production Skill
├── Data Review Skill
├── Risk Review Skill
├── Comment Insight Skill
├── Benchmark Monitoring Skill
└── Team Knowledge Skill
```

These are not separate autonomous services in version one. They are routed modules with clear prompts, input schemas, tools, and output schemas.

This avoids early complexity while keeping the design agent-ready.

## 3. Capability Matrix

| Skill | Core Jobs | Primary Inputs | Tools | Outputs | Confirmation Required |
| --- | --- | --- | --- | --- | --- |
| Content Research | find materials, trends, benchmark examples, knowledge gaps | user goal, account, country, topic, image | internal search, XHS search, note fetch | cited research answer, material shortlist | external candidate approval |
| Topic Planning | generate topics, split series, map topics to accounts | account personas, calendar, prior posts, materials | accounts, calendar, analytics, research | weekly plan, topic list, account fit | add to calendar, assign owner |
| Viral Deconstruction | analyze title hook, content structure, visuals, emotional trigger, comments | note URLs, candidate posts, metrics | note fetch, image analysis, comment fetch | reusable viral pattern, template | mark as team template |
| Content Production | draft titles, captions, cover text, tags, variants | cited sources, persona, topic, risk constraints | knowledge search, title bank, risk review | draft copy package | save draft, schedule, publish |
| Data Review | analyze post/account performance | post stats, account stats, calendar | Supabase analytics queries | weekly report, growth insights | adopt plan changes |
| Risk Review | check banned words, exaggerated claims, ad tone, persona conflict | draft copy, account persona, banned words | banned word lookup, policy prompt | risk report, rewrite suggestions | publish decision |
| Comment Insight | extract pain points, objections, FAQs, follow-up topics | comments, note metadata | comment fetch, clustering, sentiment | insight summary, follow-up ideas | save insight to memory |
| Benchmark Monitoring | monitor benchmark accounts and new viral posts | benchmark account list, schedule | crawler, external discovery, ranking | alerts, trend digest | add benchmark/material |
| Team Knowledge | dedupe, tag, approve, embed, remember rejections | review queue, saved notes, approved posts | knowledge indexer, embedding worker | searchable memory updates | approve/delete/merge |

## 4. Agent Loop

### 4.1 Plan

The planner converts a user message into a structured run plan.

Recommended schema:

```json
{
  "intent": "content_research | topic_planning | viral_deconstruction | content_production | data_review | risk_review | comment_insight | benchmark_monitoring | knowledge_management | mixed",
  "confidence": 0.0,
  "country": "英国",
  "topic_tokens": ["春天"],
  "evidence_tokens": ["春天", "spring", "春日", "樱花", "花瓣"],
  "account_ids": [],
  "source_preferences": ["internal_knowledge", "viral_posts", "benchmark_posts"],
  "required_tools": ["internal_search"],
  "expected_output": "research_answer",
  "requires_confirmation": false
}
```

The planner should combine deterministic parsing with LLM planning:

- deterministic parser extracts obvious entities such as country, source type, image presence, account mentions, dates, and action verbs
- LLM planner resolves ambiguous intent and output shape
- deterministic permission checks override the LLM

### 4.2 Tool Call

Tools should be explicit Python functions or service methods with schemas. The agent should not directly access arbitrary database tables or crawler functions.

Initial tool registry:

| Tool | Purpose | Safety |
| --- | --- | --- |
| `internal_search` | search `knowledge_items` with task filters and similarity thresholds | automatic |
| `evaluate_evidence` | classify recall as none, weak, enough | automatic |
| `answer_from_sources` | generate grounded answer from approved sources | automatic |
| `create_discovery_job` | create Xiaohongshu discovery job | confirmation or config-gated |
| `fetch_discovery_results` | read job/candidates | automatic |
| `summarize_external_candidates` | generate temporary answer from unreviewed candidates | automatic, clearly labeled |
| `approve_candidate_to_knowledge` | insert approved candidate into official source tables/index | confirmation required |
| `save_research_note` | save user-approved research note | confirmation required |
| `query_calendar` | read scheduled posts | automatic |
| `propose_calendar_items` | generate candidate calendar items | automatic |
| `commit_calendar_items` | insert/update schedule | confirmation required |
| `query_post_stats` | read analytics | automatic |
| `fetch_xhs_note` | fetch note details by URL/id | automatic with rate limits |
| `fetch_xhs_comments` | fetch comments | automatic with rate limits |
| `risk_review` | check copy against banned words and risk rules | automatic |

### 4.3 Observe

Every tool call returns an observation, not just raw rows.

Example observation:

```json
{
  "tool": "internal_search",
  "status": "ok",
  "result_count": 4,
  "strong_evidence_count": 2,
  "top_similarity": 0.71,
  "evidence_quality": "enough",
  "missing_topics": [],
  "sources": []
}
```

The agent should store observations in `agent_steps` for traceability.

### 4.4 Decide

Decision rules are deterministic in version one.

Evidence gate:

```text
0 strong sources:
  Do not generate a grounded internal answer.
  Return "knowledge not found" and offer/create external discovery.

1 strong source:
  Generate a limited answer from that source.
  Clearly say internal references are limited.
  Offer external discovery.

2-8 strong sources:
  Generate normal grounded answer.

More than 8 strong sources:
  Select the best 5-8 for answer context.
  Keep extra precise matches as secondary exploration.
```

Action gate:

```text
Read/analyze/draft actions:
  May run automatically.

Write/approve/schedule/publish-like actions:
  Must create a pending confirmation step.

External candidates:
  May be used in temporary answers.
  Must not become official knowledge without approval.
```

### 4.5 Answer

Answers should include:

- direct conclusion
- evidence status
- cited sources
- recommended next actions
- pending confirmations, if any
- tool trace summary

The answer must distinguish:

- internal approved knowledge
- external unreviewed candidates
- general advice
- draft content
- final publishable copy

### 4.6 Human Review

Human review is a first-class product surface, not an error state.

Reviewable actions:

- approve external material into knowledge
- save research note
- add topic to calendar
- save generated draft
- mark viral pattern as reusable template
- reject candidate with reason

Review reasons should be structured:

```text
不相关
低质量
疑似广告
重复素材
不适合团队调性
数据异常
已入库
```

### 4.7 Memory Update

Memory should only update from trusted events:

- approved external candidates
- user-saved research notes
- approved reusable viral patterns
- final scheduled/published team posts
- post-performance data
- rejected candidate signals

Memory update flow:

```text
approved source
-> write to source table or memory table
-> upsert into knowledge_items
-> embed_status = pending
-> embedding worker creates vector
-> future agent runs can cite it
```

## 5. Retrieval And Evidence Gate

### 5.1 Why This Matters

The current search layer can retrieve `top 30` semantically nearest rows. `top 30` is a quantity limit, not a relevance guarantee. If no row is truly relevant, top-k still returns the least-bad rows.

The agent must not treat weak retrieval as evidence.

### 5.2 Required Retrieval Changes

Internal search should use:

- structured task filters
- country/source filters when available
- vector similarity threshold
- keyword evidence tokens
- final evidence-quality classification

Recommended default:

```text
vector_match_count = 30
min_similarity = 0.58
max_answer_sources = 8
min_enough_sources = 2
```

The threshold should be configurable by task type:

| Task | Starting `min_similarity` | Notes |
| --- | --- | --- |
| content research/material | 0.58 | needs reasonably strong semantic match |
| team experience | 0.55 | historical posts may be sparse |
| title-only retrieval | 0.52 + evidence token match | titles are short and embeddings are less stable |
| image reference | 0.55 | image analysis query may be noisy |

### 5.3 SQL Contract

`match_knowledge_items` should accept `min_similarity`.

Old behavior:

```text
Return the nearest N rows, even if weak.
```

New behavior:

```text
Return at most N rows whose similarity passes the threshold.
```

The SQL should compute similarity first, then filter:

```sql
where ranked.similarity >= min_similarity
order by ranked.similarity desc
limit match_count
```

Backend should also filter again after RPC. This protects the service if the deployed Supabase SQL is older than the code.

### 5.4 Query Understanding

The query parser should not rely only on:

```python
if any(word in text for word in (...)):
```

Version one parser should return structured fields:

```json
{
  "task_type": "material",
  "country": "英国",
  "intent": "title_material_research",
  "topic_tokens": ["春天"],
  "evidence_tokens": ["春天", "spring", "春日", "樱花", "花瓣"],
  "broad_tokens": ["英国"],
  "scaffold_tokens": ["帮我", "找一下", "关于", "标题", "素材"]
}
```

Use rules for stable extraction:

- countries and destinations
- platform terms such as 小红书, 爆款, 对标
- source preferences such as 团队历史, 素材库, 评论区
- action verbs such as 找, 写, 拆, 复盘, 审核, 监控
- output types such as 标题, 正文, 周计划, 风险报告

Use LLM only when intent remains ambiguous.

## 6. Data Model

### 6.1 New Tables

#### `agent_runs`

Represents one user-facing agent run.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `user_message` | text | original request |
| `status` | text | planning, running, waiting_for_review, completed, failed |
| `intent` | text | planner result |
| `plan` | jsonb | structured plan |
| `final_answer` | jsonb | final response payload |
| `evidence_quality` | text | none, weak, enough |
| `created_by_member_id` | uuid nullable | future auth link |
| `created_at` | timestamptz | creation time |
| `updated_at` | timestamptz | update time |

#### `agent_steps`

Trace of plan, tool calls, observations, decisions, and review events.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `run_id` | uuid | references `agent_runs` |
| `step_type` | text | plan, tool_call, observation, decision, answer, review, memory_update |
| `tool_name` | text nullable | set for tool steps |
| `input_payload` | jsonb | tool/step input |
| `output_payload` | jsonb | tool/step output |
| `status` | text | pending, running, completed, failed |
| `error_message` | text nullable | failure reason |
| `created_at` | timestamptz | creation time |

#### `agent_review_actions`

Pending human confirmations.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `run_id` | uuid | related agent run |
| `action_type` | text | approve_candidate, save_note, add_calendar_item, save_draft, mark_template |
| `status` | text | pending, approved, rejected, cancelled |
| `payload` | jsonb | proposed write action |
| `review_reason` | text nullable | rejection reason |
| `reviewed_by_member_id` | uuid nullable | future auth link |
| `created_at` | timestamptz | creation time |
| `reviewed_at` | timestamptz nullable | review time |

### 6.2 Existing Tables To Reuse

- `knowledge_items`
- `ai_research_notes`
- `external_discovery_jobs`
- `external_discovery_candidates`
- `viral_posts`
- `benchmark_accounts`
- `topics`
- `titles`
- `banned_words`
- `posts`
- `post_stats`
- `account_stats_history`

Do not duplicate source data into agent tables. Agent tables store process and decisions; source tables store business records.

## 7. UX Shape

### 7.1 Agent Workbench

Add or evolve `AI 搜索中心` into an `Agent 工作台`.

Suggested layout:

```text
Left / top:
  user prompt, image upload, account/context selectors

Center:
  agent answer, draft, report, plan

Right:
  evidence, tool trace, pending review actions

Bottom / cards:
  suggested next actions
```

### 7.2 Tool Trace

Users should see a concise trace:

```text
已理解任务：内容研究 / 英国 / 春天
已搜索内部知识库：2 条强匹配
未调用外部发现：内部证据足够
待确认动作：无
```

This makes the agent feel reliable rather than magical.

### 7.3 Review Queue

Review cards should show:

- source preview
- why the agent selected it
- evidence score
- duplicate warning
- approve/reject actions

## 8. Implementation Phases

### Phase 1: Agent-Ready Retrieval Core

Goal: make the current AI Search Center safe enough to be a tool.

Deliverables:

- structured query parser
- `min_similarity` in vector search
- backend similarity fallback filter
- evidence quality gate
- max 5-8 sources passed to answer generation
- no hard answer when evidence is empty
- tests for task parsing, sparse recall, and source limits

### Phase 2: Agent Run And Trace

Goal: wrap research flow in a real agent run.

Deliverables:

- `agent_runs`
- `agent_steps`
- internal tool registry
- run status lifecycle
- trace UI
- migrate `/ai/research` behavior into `internal_search -> answer_from_sources`

### Phase 3: External Discovery As Tool

Goal: make external discovery a first-class tool call.

Deliverables:

- agent can decide to create discovery job when evidence is weak
- discovery results become observations
- external candidates can generate temporary answers
- review actions connect to candidate approval

### Phase 4: Specialist Skills

Goal: add the remaining specialist capabilities behind the same orchestrator.

Order:

1. Content Research
2. Viral Deconstruction
3. Topic Planning
4. Content Production
5. Risk Review
6. Comment Insight
7. Data Review
8. Benchmark Monitoring
9. Team Knowledge

### Phase 5: Scheduled And Proactive Agent

Goal: let the agent run scheduled monitoring jobs.

Deliverables:

- benchmark monitoring runs
- weekly review runs
- alerts for new high-save benchmark posts
- pending review queue updates

Keep all write actions review-gated.

## 9. Non-Goals

Do not build in early versions:

- automatic publishing
- automatic commenting/liking/following
- fully autonomous long-running web exploration
- arbitrary browser automation controlled by free-form prompts
- unreviewed knowledge ingestion
- multi-agent framework complexity before the state machine is stable

## 10. Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Agent confidently answers with weak evidence | evidence gate, min similarity, source limit, refusal path |
| External crawler brings noisy content | candidate scoring, duplicate detection, human review |
| Prompt injection from external posts/comments | treat external text as data, not instructions; isolate tool prompts |
| User cannot trust autonomous actions | trace log and explicit review actions |
| Too many pending review items | ranking threshold, batch review, auto-hide rejected duplicates |
| Agent becomes a large untestable prompt | specialist schemas, tool contracts, deterministic gates |
| Data model duplicates source records | process tables only store runs/steps/reviews; source tables remain truth |

## 11. Success Criteria

The first useful version is successful when:

- users can ask a broad Xiaohongshu operations question in one place
- the agent can explain what it understood and which tools it used
- weak internal evidence does not produce a fake confident answer
- external candidates remain clearly marked until reviewed
- approved candidates become searchable memory after embedding
- generated plans/drafts always show evidence and pending confirmations

## 12. Reference Ideas

Useful external references for implementation style and tool adapters:

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents): tools, handoffs, tracing, guardrails
- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents): stateful agent graphs and tool routing
- [LlamaIndex Workflows](https://docs.llamaindex.ai/en/stable/workflows/): event-driven RAG and human-in-the-loop workflows
- [autoclaw-cc/xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills): Xiaohongshu-oriented skill/tool ideas
- [RedNote-MCP](https://github.com/iFurySt/RedNote-MCP): Xiaohongshu search, note fetch, and comment-fetch adapter ideas
- [NoteRx](https://noterx.muran.tech/): multi-angle content, visual, growth, and comment deconstruction inspiration

These are references, not required dependencies. The first implementation should stay close to the current FastAPI + Supabase + crawler architecture.
