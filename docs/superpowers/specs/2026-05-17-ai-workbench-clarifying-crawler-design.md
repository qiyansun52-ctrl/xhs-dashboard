# AI Workbench Clarifying Crawler Design

Date: 2026-05-17
Status: Approved for planning

## Context

The current dashboard has two adjacent AI surfaces:

- AI 搜索中心: asks a question, retrieves internal knowledge, can trigger external discovery when evidence is sparse.
- 运营助手: runs an agent task, streams progress, and creates human-reviewed actions.

The external discovery crawler is working partially, but the user experience is misleading. Recent failed jobs still produced usable candidates, but one Xiaohongshu detail fetch raised `Note not found or abnormal, code: -510000`, which caused the whole job to be marked `failed`. The current crawler also receives broad search terms such as “英国方面的素材”, so it searches too widely and returns noisy candidates.

## Goal

Merge AI 搜索中心 and 运营助手 into one ChatGPT-style AI workbench with:

- A left-side conversation history list.
- A central continuous chat thread.
- A right-side context panel for evidence, crawler brief, discovery jobs, candidates, and review actions.
- A hybrid LLM clarification flow before crawler jobs are created.
- Support for viewing and continuing historical conversations.

## Product Direction

Use the unified ChatGPT-style workbench, not separate “AI 搜索 / 运营助手” tabs.

The user can type naturally, for example:

> 帮我找英国方面的素材

The system should not immediately launch a broad crawler job. It should first use an LLM clarification layer to produce structured choices and a draft crawler brief.

The clarification UI is hybrid:

- The LLM presents option chips/cards for fast selection.
- The user can also add free-form text.
- The LLM then summarizes the selected constraints into a crawler-ready brief.
- The user confirms before external discovery starts.

## Main Workflow

1. User opens AI 工作台.
2. User starts or resumes a conversation from the left sidebar.
3. User enters a broad request.
4. Backend creates a conversation message and runs the clarification planner.
5. If the request is specific enough, the assistant may answer or propose a crawler brief directly.
6. If the request is too broad, the assistant returns a clarification card with selectable options.
7. User selects options and optionally adds free-form constraints.
8. LLM converts the choices into a structured crawler brief.
9. User confirms the brief.
10. Backend creates an external discovery job from the brief.
11. Crawler writes candidates as they are found.
12. UI shows job status and candidates in the right panel.
13. User approves, ignores, or rejects candidates.
14. Approved candidates are inserted into `viral_posts` and indexed into `knowledge_items`.
15. The conversation can continue using the same context.

## Clarification Model

The clarification layer should ask only for information that improves crawler precision.

Core dimensions:

- Country or market: 英国, 新加坡, 澳洲, 美国, or mixed.
- Audience: 高中生, 本科, 研究生, 家长, 工作后留学, 新留子, 已毕业留学生.
- Content scene: 生活类, 申请类, 作业论文考试类, 住宿租房, 校园日常, 就业实习, 省钱攻略, 情感社交, 安全避坑.
- Expression type: 经验型, 吐槽型, 干货攻略, 避坑警示, 情绪共鸣, 对比反差, 故事叙事.
- Quality target: 高收藏, 高评论, 真人经历, 标题强钩子, 图片可参考, 评论区有痛点.
- Exclusions: 机构广告, 低质搬运, 纯营销, 无真人经验, 太泛 hashtag, 重复旧素材.

Example output from LLM:

```json
{
  "needs_clarification": true,
  "question": "你想优先找英国留学的哪个方向？",
  "option_groups": [
    {
      "id": "content_scene",
      "label": "内容场景",
      "max_select": 2,
      "options": [
        {"id": "life", "label": "生活类"},
        {"id": "application", "label": "申请类"},
        {"id": "academic", "label": "作业论文考试类"},
        {"id": "housing", "label": "住宿租房"},
        {"id": "career", "label": "就业实习"}
      ]
    },
    {
      "id": "expression_type",
      "label": "表达类型",
      "max_select": 2,
      "options": [
        {"id": "experience", "label": "经验型"},
        {"id": "complaint", "label": "吐槽型"},
        {"id": "guide", "label": "干货攻略"},
        {"id": "warning", "label": "避坑警示"},
        {"id": "emotion", "label": "情绪共鸣"}
      ]
    }
  ],
  "free_text_prompt": "你也可以补充：不要什么、偏什么风格、给哪个账号用。"
}
```

After the user answers, the LLM produces:

```json
{
  "needs_clarification": false,
  "crawler_brief": {
    "goal": "寻找英国留学生活类真实经验素材，偏经验型和情绪共鸣",
    "country": "英国",
    "audiences": ["本科", "研究生", "新留子"],
    "content_scenes": ["生活类"],
    "expression_types": ["经验型", "情绪共鸣"],
    "quality_targets": ["高收藏", "真人经历", "评论区有痛点"],
    "exclusions": ["机构广告", "低质搬运", "重复旧素材"],
    "search_queries": [
      "英国留学 生活 真实经验",
      "英国留学生 日常 吐槽",
      "英国留学 避坑 生活",
      "留学生 英国 租房 经验"
    ],
    "candidate_scoring_hint": "优先高收藏/高评论/真人叙事，降低机构口吻和空标题素材分数"
  }
}
```

## UI Design

### Layout

Desktop layout:

- Left sidebar: conversation list.
- Main panel: chat messages and input box.
- Right panel: current context.

Mobile layout:

- Conversation list becomes a drawer.
- Right context becomes a collapsible bottom or tab panel.
- Chat remains the primary surface.

### Left Sidebar

The sidebar should show:

- New chat button.
- Recent conversations sorted by `updated_at`.
- Conversation title generated from the first useful user request.
- Status badges when a conversation has pending review actions or running discovery jobs.

### Main Chat

Message types:

- User text.
- Assistant answer.
- Clarification card.
- Crawler brief card.
- Discovery progress event.
- Candidate summary.
- Human review action result.

The input box supports normal text first. Image input can remain supported later through the existing AI search upload flow.

### Right Context Panel

The right panel shows the current conversation state:

- Internal evidence quality.
- Generated crawler brief.
- External discovery job status.
- Candidate list with approve / ignore / reject.
- Pending review actions.
- Saved notes or drafts from this conversation.

## Backend Design

### Conversation Persistence

Add persistent conversations rather than relying only on `agent_runs`.

Proposed tables:

- `ai_conversations`
- `ai_messages`
- `ai_conversation_context`

`ai_conversations` stores the durable thread:

- `id`
- `title`
- `member_id`
- `status`
- `created_at`
- `updated_at`
- `archived_at`

`ai_messages` stores all visible and system-use messages:

- `id`
- `conversation_id`
- `role`: `user`, `assistant`, `system`, `tool`
- `message_type`: `text`, `clarification`, `crawler_brief`, `answer`, `event`, `candidate_summary`
- `content`
- `payload`
- `created_at`

`ai_conversation_context` stores the latest operational state:

- `conversation_id`
- `latest_answer_payload`
- `latest_crawler_brief`
- `active_discovery_job_id`
- `active_agent_run_id`
- `selected_candidate_ids`
- `pending_review_action_ids`
- `updated_at`

Existing `agent_runs`, `agent_steps`, `agent_review_actions`, `external_discovery_jobs`, and `external_discovery_candidates` should be linked to `conversation_id` where relevant.

### API Surface

Add endpoints:

- `GET /ai/conversations`
- `POST /ai/conversations`
- `GET /ai/conversations/{conversation_id}`
- `POST /ai/conversations/{conversation_id}/messages`
- `POST /ai/conversations/{conversation_id}/clarify`
- `POST /ai/conversations/{conversation_id}/crawler-brief`
- `POST /ai/conversations/{conversation_id}/discovery-jobs`

Existing endpoints can remain during migration, but the new workbench should use conversation-scoped endpoints.

### LLM Clarification Layer

Implement a new service responsible for:

- Determining whether a request is specific enough.
- Producing clarification option groups.
- Merging user selections and free text.
- Producing crawler brief JSON.
- Producing search queries from the brief.

The service should use the configured LLM provider. The current provider is Gemini through the OpenAI-compatible adapter.

The LLM output must be schema-constrained and validated before use.

### Crawler Job Changes

External discovery jobs should accept the structured crawler brief. The existing `search_queries` field remains, but the job should also store:

- `crawler_brief`
- `quality_targets`
- `exclusions`
- `candidate_scoring_hint`
- `conversation_id`

Crawler execution should become failure-tolerant:

- If one keyword result cannot be fetched, skip that note and record a warning.
- If at least one candidate is stored and at least one fetch fails, mark job `partial`.
- If no candidates are stored and all attempts fail, mark job `failed`.
- If candidates are stored and no fatal error remains, mark job `completed`.

This requires adding `partial` to `external_discovery_jobs.status`.

The UI should display:

- `completed`: 已完成
- `partial`: 部分完成，部分帖子抓取失败
- `failed`: 失败，没有可用候选

## Candidate Scoring

The current score is mostly metric-based. The brief should influence scoring:

- Boost candidates matching selected content scenes and expression types.
- Boost high saves and high comments more than likes.
- Penalize empty titles, institution-style copy, repeated URLs, and generic hashtags.
- Penalize candidates already approved or rejected in recent jobs.

The first implementation can be heuristic. A later version can use an LLM reranker for the top candidates.

## Migration Plan

Keep the existing screens working during migration:

- Reuse current `AISearchPage` retrieval logic as a tool inside the new workbench.
- Reuse current `AgentPage` run streaming and review action logic.
- Reuse existing candidate cards and approval endpoints where possible.
- Add the new conversation shell first, then retire the old AI mode tabs after parity.

## Error Handling

- LLM clarification failure: fall back to a simple fixed set of option groups based on detected country and topic.
- Brief generation failure: ask the user to provide one free-form sentence with direction and exclusions.
- Crawler detail fetch failure: skip note, keep job running.
- Supabase write failure: show retryable error and keep local UI state unsaved.
- Running job in an old conversation: show active status badge in left sidebar.

## Testing

Backend tests:

- Broad request returns clarification groups.
- Specific request can produce a crawler brief without extra questions.
- Selected chips plus free text produce expected search queries.
- Invalid LLM JSON falls back safely.
- Single note fetch failure does not fail the whole job when other candidates exist.
- Job becomes `partial` when candidates exist but some fetches fail.
- Conversation history persists and can be resumed.

Frontend tests:

- Conversation list renders and selects historical conversations.
- Broad prompt renders clarification cards.
- Selecting chips and adding free text submits a brief request.
- Generated brief renders before crawler launch.
- Partial crawler job still shows candidates.
- Review actions remain accessible from the right panel.

Manual verification:

- Start new chat with “帮我找英国方面的素材”.
- Select “生活类” and “经验型”, add “不要机构广告”.
- Confirm generated brief.
- Start discovery.
- Verify candidates appear even if one Xiaohongshu detail fetch fails.
- Approve one candidate and confirm it enters the material library.

## Non-Goals For First Version

- Full project management or multi-user assignment workflows.
- Advanced prompt library management.
- LLM reranking for every candidate.
- Real-time collaborative editing.
- Replacing all existing AI search endpoints immediately.

## Open Implementation Decisions

These are engineering choices for the implementation plan, not product blockers:

- Whether to implement conversation streaming with SSE from the start or use polling first.
- Whether to store brief fields directly on `external_discovery_jobs` or in a linked `crawler_briefs` table.
- Whether old `ai_research_notes` should remain separate or be linked to conversations.
