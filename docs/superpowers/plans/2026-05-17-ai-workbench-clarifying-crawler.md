# AI Workbench Clarifying Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified ChatGPT-style AI workbench that stores conversation history, asks LLM-powered clarification questions before crawling, and makes external discovery jobs failure-tolerant.

**Architecture:** Add durable conversation storage and conversation-scoped API endpoints on top of the existing FastAPI service. Add a small LLM clarification service that turns broad user requests into selectable option groups and crawler briefs. Reuse the existing AI search, agent run, discovery candidate, and review-action systems inside a new frontend workbench shell.

**Tech Stack:** FastAPI, Supabase PostgREST, Python `unittest`, React/Vite, Node `node:test`, existing OpenAI-compatible Gemini adapter, existing crawler/server process.

---

## File Structure

Backend files:

- Create `crawler/agent/conversation_store.py`: durable conversation, message, and context store with in-memory fallback.
- Create `crawler/clarification_service.py`: LLM-backed clarification and crawler brief builder with deterministic fallback.
- Modify `crawler/ai_api.py`: conversation endpoints, clarification endpoints, conversation-scoped discovery endpoints.
- Modify `crawler/ai_schema.sql`: new conversation tables, new `conversation_id` links, new crawler brief columns, `partial` job status.
- Modify `crawler/discovery.py`: derive search queries and candidate scoring inputs from crawler brief fields.
- Modify `crawler/server.py`: tolerate per-note fetch failures and mark jobs `completed`, `partial`, or `failed`.
- Create `crawler/test_workbench.py`: backend tests for conversation store, clarification service, API endpoints, and crawler partial behavior.

Frontend files:

- Create `src/aiWorkbench.js`: pure state helpers for conversation UI, clarification selections, and crawler brief payloads.
- Create `src/aiWorkbenchApi.js`: conversation-scoped API client.
- Create `src/components/AIWorkbenchPage.jsx`: unified ChatGPT-style workbench.
- Create `src/components/DiscoveryCandidateCard.jsx`: shared candidate review card moved out of `AISearchPage`.
- Modify `src/components/AISearchPage.jsx`: import shared candidate card or keep legacy page stable during migration.
- Modify `src/App.jsx`: replace the current AI search/agent mode switch with the new workbench while keeping old components importable.
- Create `src/aiWorkbench.test.js`: frontend helper tests.
- Modify `package.json`: add `src/aiWorkbench.test.js` to `test:frontend`.

---

## Task 1: Conversation Schema And Store

**Files:**
- Modify: `crawler/ai_schema.sql`
- Create: `crawler/agent/conversation_store.py`
- Create: `crawler/test_workbench.py`

- [ ] **Step 1: Write failing conversation store tests**

Add this file:

```python
# crawler/test_workbench.py
import asyncio
import unittest

from agent.conversation_store import ConversationStore


class FakeResult:
    def __init__(self, data=None):
        self.data = data


class FakeTable:
    def __init__(self, name, client):
        self.name = name
        self.client = client
        self.calls = []
        self.insert_payload = None
        self.update_payload = None

    def insert(self, payload):
        self.calls.append(("insert", payload))
        self.insert_payload = payload
        return self

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def order(self, column, desc=False):
        self.calls.append(("order", column, desc))
        return self

    def limit(self, count):
        self.calls.append(("limit", count))
        return self

    def maybe_single(self):
        self.calls.append(("maybe_single",))
        return self

    def update(self, payload):
        self.calls.append(("update", payload))
        self.update_payload = payload
        return self

    def execute(self):
        self.calls.append(("execute",))
        if self.insert_payload is not None:
            self.client.inserts.append((self.name, self.insert_payload))
            return FakeResult(self.insert_payload)
        if self.update_payload is not None:
            self.client.updates.append((self.name, self.update_payload))
            return FakeResult([self.update_payload])
        return FakeResult(self.client.responses.get(self.name, []))


class FakeSupabase:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.tables = []
        self.inserts = []
        self.updates = []

    def table(self, name):
        table = FakeTable(name, self)
        self.tables.append(table)
        return table


class ConversationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_conversation_add_message_and_read_snapshot(self):
        store = ConversationStore()

        conversation = await store.create_conversation(
            title="英国素材调研",
            member_id="member-1",
        )
        message = await store.add_message(
            conversation_id=conversation["id"],
            role="user",
            message_type="text",
            content="帮我找英国方面的素材",
            payload={"source": "manual"},
        )
        snapshot = await store.get_conversation_snapshot(conversation["id"])

        self.assertEqual(conversation["title"], "英国素材调研")
        self.assertEqual(message["content"], "帮我找英国方面的素材")
        self.assertEqual(snapshot["conversation"]["id"], conversation["id"])
        self.assertEqual(snapshot["messages"][0]["id"], message["id"])

    async def test_list_conversations_orders_newest_first(self):
        store = ConversationStore()
        first = await store.create_conversation(title="first")
        second = await store.create_conversation(title="second")

        rows = await store.list_conversations()

        self.assertEqual([row["id"] for row in rows], [second["id"], first["id"]])

    async def test_store_persists_to_supabase_when_client_is_present(self):
        sb = FakeSupabase()
        store = ConversationStore(sb)

        conversation = await store.create_conversation(title="英国素材")
        await store.add_message(conversation["id"], "assistant", "answer", "已生成 brief")

        table_names = [name for name, payload in sb.inserts]
        self.assertIn("ai_conversations", table_names)
        self.assertIn("ai_messages", table_names)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.conversation_store'`.

- [ ] **Step 3: Add schema for conversations and links**

Append this SQL to `crawler/ai_schema.sql` after the existing Agent tables and before `match_knowledge_items`:

```sql
create table if not exists ai_conversations (
  id uuid primary key default gen_random_uuid(),
  title text not null default '新对话',
  member_id uuid references members(id) on delete set null,
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  archived_at timestamptz
);

create index if not exists idx_ai_conversations_updated_at
  on ai_conversations(updated_at desc);

alter table ai_conversations enable row level security;
drop policy if exists "team_access" on ai_conversations;
create policy "team_access" on ai_conversations for all using (true) with check (true);

create table if not exists ai_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references ai_conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system', 'tool')),
  message_type text not null check (message_type in (
    'text',
    'clarification',
    'crawler_brief',
    'answer',
    'event',
    'candidate_summary'
  )),
  content text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);

create index if not exists idx_ai_messages_conversation_created_at
  on ai_messages(conversation_id, created_at);

alter table ai_messages enable row level security;
drop policy if exists "team_access" on ai_messages;
create policy "team_access" on ai_messages for all using (true) with check (true);

create table if not exists ai_conversation_context (
  conversation_id uuid primary key references ai_conversations(id) on delete cascade,
  latest_answer_payload jsonb not null default '{}'::jsonb,
  latest_crawler_brief jsonb not null default '{}'::jsonb,
  active_discovery_job_id uuid references external_discovery_jobs(id) on delete set null,
  active_agent_run_id uuid references agent_runs(id) on delete set null,
  selected_candidate_ids uuid[] not null default '{}',
  pending_review_action_ids uuid[] not null default '{}',
  updated_at timestamptz default now()
);

alter table ai_conversation_context enable row level security;
drop policy if exists "team_access" on ai_conversation_context;
create policy "team_access" on ai_conversation_context for all using (true) with check (true);

alter table agent_runs
  add column if not exists conversation_id uuid references ai_conversations(id) on delete set null;

alter table agent_review_actions
  add column if not exists conversation_id uuid references ai_conversations(id) on delete set null;

alter table external_discovery_jobs
  add column if not exists conversation_id uuid references ai_conversations(id) on delete set null;
```

- [ ] **Step 4: Implement the conversation store**

Create `crawler/agent/conversation_store.py`:

```python
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class ConversationStore:
    def __init__(self, supabase_client=None):
        self.sb = supabase_client
        self._conversations: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[Dict[str, Any]]] = {}
        self._contexts: Dict[str, Dict[str, Any]] = {}
        self._db_disabled = False

    def _can_persist(self) -> bool:
        return self.sb is not None and not self._db_disabled

    async def create_conversation(
        self,
        title: str = "新对话",
        member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        row = {
            "id": conversation_id,
            "title": title or "新对话",
            "member_id": member_id,
            "status": "active",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "archived_at": None,
        }
        self._conversations[conversation_id] = row
        self._messages.setdefault(conversation_id, [])
        self._contexts[conversation_id] = self._empty_context(conversation_id)
        if self._can_persist():
            self.sb.table("ai_conversations").insert([json_safe(row)]).execute()
            self.sb.table("ai_conversation_context").insert([json_safe(self._contexts[conversation_id])]).execute()
        return copy.deepcopy(row)

    async def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self._can_persist():
            rows = (
                self.sb.table("ai_conversations")
                .select("*")
                .eq("status", "active")
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
                .data
                or []
            )
            for row in rows:
                self._conversations[row["id"]] = dict(row)
            return copy.deepcopy(rows)

        rows = [row for row in self._conversations.values() if row.get("status") == "active"]
        rows.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
        return copy.deepcopy(rows[:limit])

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        message_type: str,
        content: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        conversation = await self._ensure_conversation(conversation_id)
        message = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "message_type": message_type,
            "content": content or "",
            "payload": json_safe(payload or {}),
            "created_at": now_iso(),
        }
        self._messages.setdefault(conversation_id, []).append(message)
        conversation["updated_at"] = now_iso()
        if self._can_persist():
            self.sb.table("ai_messages").insert([json_safe(message)]).execute()
            self.sb.table("ai_conversations").update({"updated_at": conversation["updated_at"]}).eq("id", conversation_id).execute()
        return copy.deepcopy(message)

    async def update_context(self, conversation_id: str, **fields) -> Dict[str, Any]:
        await self._ensure_conversation(conversation_id)
        context = self._contexts.get(conversation_id) or self._empty_context(conversation_id)
        context.update(json_safe(fields))
        context["updated_at"] = now_iso()
        self._contexts[conversation_id] = context
        if self._can_persist():
            self.sb.table("ai_conversation_context").update(json_safe(context)).eq("conversation_id", conversation_id).execute()
        return copy.deepcopy(context)

    async def get_conversation_snapshot(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        conversation = self._conversations.get(conversation_id)
        messages = self._messages.get(conversation_id)
        context = self._contexts.get(conversation_id)

        if self._can_persist() and not conversation:
            conversation = (
                self.sb.table("ai_conversations")
                .select("*")
                .eq("id", conversation_id)
                .maybe_single()
                .execute()
                .data
            )
            if conversation:
                self._conversations[conversation_id] = dict(conversation)

        if self._can_persist() and messages is None:
            messages = (
                self.sb.table("ai_messages")
                .select("*")
                .eq("conversation_id", conversation_id)
                .order("created_at")
                .execute()
                .data
                or []
            )
            self._messages[conversation_id] = [dict(row) for row in messages]

        if self._can_persist() and context is None:
            context = (
                self.sb.table("ai_conversation_context")
                .select("*")
                .eq("conversation_id", conversation_id)
                .maybe_single()
                .execute()
                .data
            )
            if context:
                self._contexts[conversation_id] = dict(context)

        if not conversation:
            return None

        return {
            "conversation": copy.deepcopy(conversation),
            "messages": copy.deepcopy(messages or []),
            "context": copy.deepcopy(context or self._empty_context(conversation_id)),
        }

    async def _ensure_conversation(self, conversation_id: str) -> Dict[str, Any]:
        snapshot = await self.get_conversation_snapshot(conversation_id)
        if not snapshot:
            raise KeyError(f"conversation not found: {conversation_id}")
        return self._conversations[conversation_id]

    def _empty_context(self, conversation_id: str) -> Dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "latest_answer_payload": {},
            "latest_crawler_brief": {},
            "active_discovery_job_id": None,
            "active_agent_run_id": None,
            "selected_candidate_ids": [],
            "pending_review_action_ids": [],
            "updated_at": now_iso(),
        }
```

- [ ] **Step 5: Verify Task 1**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: all tests in `test_workbench.py` pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add crawler/ai_schema.sql crawler/agent/conversation_store.py crawler/test_workbench.py
git commit -m "feat(ai): add conversation store"
```

---

## Task 2: LLM Clarification And Crawler Brief Service

**Files:**
- Create: `crawler/clarification_service.py`
- Modify: `crawler/test_workbench.py`

- [ ] **Step 1: Add failing clarification service tests**

Append to `crawler/test_workbench.py`:

```python
from clarification_service import ClarificationService


class ClarificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_broad_material_request_returns_option_groups(self):
        service = ClarificationService(structured_completion=None)

        result = await service.clarify_request("帮我找英国方面的素材")

        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["detected_country"], "英国")
        self.assertEqual(result["option_groups"][0]["id"], "content_scene")
        labels = [item["label"] for item in result["option_groups"][0]["options"]]
        self.assertIn("生活类", labels)
        self.assertIn("作业论文考试类", labels)

    async def test_build_crawler_brief_merges_selections_and_free_text(self):
        service = ClarificationService(structured_completion=None)

        brief = await service.build_crawler_brief(
            original_request="帮我找英国方面的素材",
            selections={
                "content_scene": ["life"],
                "expression_type": ["experience", "emotion"],
            },
            free_text="不要机构广告，偏真实留学生日常",
        )

        self.assertFalse(brief["needs_clarification"])
        self.assertEqual(brief["crawler_brief"]["country"], "英国")
        self.assertIn("生活类", brief["crawler_brief"]["content_scenes"])
        self.assertIn("经验型", brief["crawler_brief"]["expression_types"])
        self.assertIn("机构广告", brief["crawler_brief"]["exclusions"])
        self.assertGreaterEqual(len(brief["crawler_brief"]["search_queries"]), 3)

    async def test_invalid_llm_payload_falls_back_to_deterministic_brief(self):
        def invalid_completion(**kwargs):
            return {"broken": True}

        service = ClarificationService(structured_completion=invalid_completion)

        result = await service.clarify_request("帮我找新加坡申请素材")

        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["detected_country"], "新加坡")
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: fail with `ModuleNotFoundError: No module named 'clarification_service'`.

- [ ] **Step 3: Implement deterministic fallback and LLM wrapper**

Create `crawler/clarification_service.py`:

```python
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional


COUNTRIES = ("英国", "新加坡", "澳洲", "美国", "加拿大", "香港")

CONTENT_SCENE_OPTIONS = [
    {"id": "life", "label": "生活类"},
    {"id": "application", "label": "申请类"},
    {"id": "academic", "label": "作业论文考试类"},
    {"id": "housing", "label": "住宿租房"},
    {"id": "campus", "label": "校园日常"},
    {"id": "career", "label": "就业实习"},
    {"id": "saving", "label": "省钱攻略"},
    {"id": "safety", "label": "安全避坑"},
]

EXPRESSION_TYPE_OPTIONS = [
    {"id": "experience", "label": "经验型"},
    {"id": "complaint", "label": "吐槽型"},
    {"id": "guide", "label": "干货攻略"},
    {"id": "warning", "label": "避坑警示"},
    {"id": "emotion", "label": "情绪共鸣"},
    {"id": "contrast", "label": "对比反差"},
    {"id": "story", "label": "故事叙事"},
]

QUALITY_OPTIONS = [
    {"id": "high_save", "label": "高收藏"},
    {"id": "high_comment", "label": "高评论"},
    {"id": "real_person", "label": "真人经历"},
    {"id": "strong_hook", "label": "标题强钩子"},
    {"id": "comment_pain", "label": "评论区有痛点"},
]

EXCLUSION_OPTIONS = [
    {"id": "agency_ads", "label": "机构广告"},
    {"id": "low_quality", "label": "低质搬运"},
    {"id": "marketing", "label": "纯营销"},
    {"id": "no_real_story", "label": "无真人经验"},
    {"id": "generic_tags", "label": "太泛 hashtag"},
    {"id": "duplicates", "label": "重复旧素材"},
]


class ClarificationService:
    def __init__(self, structured_completion: Optional[Callable[..., Dict[str, Any]]] = None):
        self.structured_completion = structured_completion

    async def clarify_request(self, question: str, messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if self.structured_completion:
            try:
                payload = await asyncio.to_thread(self._call_clarification_llm, question, messages or [])
                if self._valid_clarification_payload(payload):
                    return payload
            except Exception:
                pass
        return self._fallback_clarification(question)

    async def build_crawler_brief(
        self,
        original_request: str,
        selections: Dict[str, List[str]],
        free_text: str = "",
    ) -> Dict[str, Any]:
        country = self._detect_country(original_request)
        content_scenes = self._labels_for(selections.get("content_scene") or [], CONTENT_SCENE_OPTIONS)
        expression_types = self._labels_for(selections.get("expression_type") or [], EXPRESSION_TYPE_OPTIONS)
        quality_targets = self._labels_for(selections.get("quality_target") or [], QUALITY_OPTIONS) or ["高收藏", "真人经历", "评论区有痛点"]
        exclusions = self._labels_for(selections.get("exclusion") or [], EXCLUSION_OPTIONS)
        if "机构广告" not in exclusions and ("不要机构" in free_text or "机构广告" in free_text):
            exclusions.append("机构广告")
        if "低质搬运" not in exclusions and "搬运" in free_text:
            exclusions.append("低质搬运")
        if not content_scenes:
            content_scenes = ["生活类"]
        if not expression_types:
            expression_types = ["经验型"]
        search_queries = self._build_queries(country, content_scenes, expression_types, free_text)
        return {
            "needs_clarification": False,
            "crawler_brief": {
                "goal": f"寻找{country}留学{content_scenes[0]}素材，偏{'、'.join(expression_types)}",
                "country": country,
                "audiences": self._infer_audiences(free_text),
                "content_scenes": content_scenes,
                "expression_types": expression_types,
                "quality_targets": quality_targets,
                "exclusions": exclusions or ["机构广告", "低质搬运", "重复旧素材"],
                "search_queries": search_queries,
                "candidate_scoring_hint": "优先高收藏/高评论/真人叙事，降低机构口吻、空标题、泛 hashtag 和重复素材分数",
                "free_text": free_text,
            },
        }

    def _call_clarification_llm(self, question: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        schema = self._clarification_schema()
        prompt = {
            "question": question,
            "recent_messages": messages[-8:],
            "rules": [
                "如果请求很泛，返回 needs_clarification=true 和 2 到 4 个 option_groups。",
                "只询问能提高小红书爬虫精准度的信息。",
                "选项必须来自内容场景、表达类型、质量目标、排除项。",
                "中文输出。",
            ],
        }
        return self.structured_completion(
            model=None,
            system_message="你是小红书留学素材爬虫的 brief 规划员。",
            user_content=json.dumps(prompt, ensure_ascii=False),
            schema_name="crawler_clarification",
            schema=schema,
        )

    def _fallback_clarification(self, question: str) -> Dict[str, Any]:
        country = self._detect_country(question)
        return {
            "needs_clarification": True,
            "detected_country": country,
            "question": f"你想优先找{country}留学的哪个方向？",
            "option_groups": [
                {"id": "content_scene", "label": "内容场景", "max_select": 2, "options": CONTENT_SCENE_OPTIONS[:6]},
                {"id": "expression_type", "label": "表达类型", "max_select": 2, "options": EXPRESSION_TYPE_OPTIONS[:5]},
                {"id": "quality_target", "label": "质量目标", "max_select": 3, "options": QUALITY_OPTIONS},
                {"id": "exclusion", "label": "排除项", "max_select": 3, "options": EXCLUSION_OPTIONS},
            ],
            "free_text_prompt": "你也可以补充：不要什么、偏什么风格、给哪个账号用。",
        }

    def _detect_country(self, text: str) -> str:
        for country in COUNTRIES:
            if country in text:
                return country
        return "英国"

    def _labels_for(self, ids: List[str], options: List[Dict[str, str]]) -> List[str]:
        labels = {item["id"]: item["label"] for item in options}
        return [labels[item_id] for item_id in ids if item_id in labels]

    def _infer_audiences(self, free_text: str) -> List[str]:
        audiences = []
        for label in ("高中生", "本科", "研究生", "家长", "工作后留学", "新留子"):
            if label in free_text:
                audiences.append(label)
        return audiences or ["本科", "研究生", "新留子"]

    def _build_queries(self, country: str, scenes: List[str], expression_types: List[str], free_text: str) -> List[str]:
        scene_terms = {
            "生活类": "生活",
            "申请类": "申请",
            "作业论文考试类": "论文 考试",
            "住宿租房": "租房",
            "校园日常": "校园 日常",
            "就业实习": "就业 实习",
        }
        expression_terms = {
            "经验型": "真实经验",
            "吐槽型": "吐槽",
            "干货攻略": "攻略",
            "避坑警示": "避坑",
            "情绪共鸣": "日常",
        }
        primary_scene = scene_terms.get(scenes[0], scenes[0])
        primary_expression = expression_terms.get(expression_types[0], expression_types[0])
        queries = [
            f"{country}留学 {primary_scene} {primary_expression}",
            f"{country}留学生 {primary_scene} 小红书",
            f"{country}留学 {primary_scene} 避坑",
        ]
        if len(expression_types) > 1:
            queries.append(f"{country}留学生 {expression_terms.get(expression_types[1], expression_types[1])}")
        if "租房" in free_text and f"{country}留学 租房 经验" not in queries:
            queries.append(f"{country}留学 租房 经验")
        return queries[:4]

    def _valid_clarification_payload(self, payload: Dict[str, Any]) -> bool:
        return isinstance(payload, dict) and isinstance(payload.get("needs_clarification"), bool) and isinstance(payload.get("option_groups"), list)

    def _clarification_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "needs_clarification": {"type": "boolean"},
                "detected_country": {"type": "string"},
                "question": {"type": "string"},
                "option_groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "max_select": {"type": "integer"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "id": {"type": "string"},
                                        "label": {"type": "string"},
                                    },
                                    "required": ["id", "label"],
                                },
                            },
                        },
                        "required": ["id", "label", "max_select", "options"],
                    },
                },
                "free_text_prompt": {"type": "string"},
            },
            "required": ["needs_clarification", "detected_country", "question", "option_groups", "free_text_prompt"],
        }
```

- [ ] **Step 4: Verify Task 2**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: conversation and clarification tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add crawler/clarification_service.py crawler/test_workbench.py
git commit -m "feat(ai): add crawler clarification service"
```

---

## Task 3: Conversation-Scoped API Endpoints

**Files:**
- Modify: `crawler/ai_api.py`
- Modify: `crawler/test_workbench.py`

- [ ] **Step 1: Add failing API tests**

Append to `crawler/test_workbench.py`:

```python
import ai_api


class WorkbenchApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_store = getattr(ai_api, "conversation_store", None)
        self.original_clarifier = getattr(ai_api, "clarification_service", None)
        ai_api.conversation_store = ConversationStore()
        ai_api.clarification_service = ClarificationService(structured_completion=None)

    def tearDown(self):
        ai_api.conversation_store = self.original_store
        ai_api.clarification_service = self.original_clarifier

    async def test_create_list_and_get_conversation(self):
        created = await ai_api.create_ai_conversation(ai_api.CreateConversationReq(title="英国素材"))
        listed = await ai_api.list_ai_conversations()
        snapshot = await ai_api.get_ai_conversation(created["conversation"]["id"])

        self.assertTrue(created["ok"])
        self.assertEqual(listed["conversations"][0]["id"], created["conversation"]["id"])
        self.assertEqual(snapshot["conversation"]["title"], "英国素材")

    async def test_clarify_conversation_message_persists_user_and_assistant_messages(self):
        created = await ai_api.create_ai_conversation(ai_api.CreateConversationReq(title="英国素材"))
        conversation_id = created["conversation"]["id"]

        result = await ai_api.clarify_ai_conversation(
            conversation_id,
            ai_api.ClarifyConversationReq(message="帮我找英国方面的素材"),
        )
        snapshot = await ai_api.get_ai_conversation(conversation_id)

        self.assertTrue(result["clarification"]["needs_clarification"])
        self.assertEqual([row["role"] for row in snapshot["messages"]], ["user", "assistant"])
        self.assertEqual(snapshot["messages"][1]["message_type"], "clarification")

    async def test_build_conversation_crawler_brief_updates_context(self):
        created = await ai_api.create_ai_conversation(ai_api.CreateConversationReq(title="英国素材"))
        conversation_id = created["conversation"]["id"]

        result = await ai_api.build_ai_conversation_crawler_brief(
            conversation_id,
            ai_api.BuildCrawlerBriefReq(
                original_request="帮我找英国方面的素材",
                selections={"content_scene": ["life"], "expression_type": ["experience"]},
                free_text="不要机构广告",
            ),
        )
        snapshot = await ai_api.get_ai_conversation(conversation_id)

        self.assertEqual(result["brief"]["crawler_brief"]["country"], "英国")
        self.assertEqual(snapshot["context"]["latest_crawler_brief"]["country"], "英国")
```

- [ ] **Step 2: Run the failing API tests**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: fail because the endpoint functions and request models do not exist.

- [ ] **Step 3: Wire stores and request models in `crawler/ai_api.py`**

Add imports:

```python
from agent.conversation_store import ConversationStore
from clarification_service import ClarificationService
```

Add global instances after `research_service` is created:

```python
conversation_store = ConversationStore(sb)
clarification_service = ClarificationService(
    structured_completion=research_service._create_structured_chat_completion
)
```

Add request models:

```python
class CreateConversationReq(BaseModel):
    title: str = "新对话"
    member_id: Optional[str] = None


class ClarifyConversationReq(BaseModel):
    message: str = Field(..., min_length=1)


class BuildCrawlerBriefReq(BaseModel):
    original_request: str = Field(..., min_length=1)
    selections: Dict[str, List[str]] = Field(default_factory=dict)
    free_text: str = ""
```

- [ ] **Step 4: Add conversation endpoints in `crawler/ai_api.py`**

Place these endpoints near the Agent endpoints:

```python
@app.get("/ai/conversations", dependencies=[Depends(require_api_key)])
async def list_ai_conversations():
    rows = await conversation_store.list_conversations()
    return {"ok": True, "conversations": rows}


@app.post("/ai/conversations", dependencies=[Depends(require_api_key)])
async def create_ai_conversation(req: CreateConversationReq):
    conversation = await conversation_store.create_conversation(
        title=req.title,
        member_id=req.member_id,
    )
    return {"ok": True, "conversation": conversation}


@app.get("/ai/conversations/{conversation_id}", dependencies=[Depends(require_api_key)])
async def get_ai_conversation(conversation_id: str):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    return {"ok": True, **snapshot}


@app.post("/ai/conversations/{conversation_id}/clarify", dependencies=[Depends(require_api_key)])
async def clarify_ai_conversation(conversation_id: str, req: ClarifyConversationReq):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    await conversation_store.add_message(conversation_id, "user", "text", req.message)
    clarification = await clarification_service.clarify_request(
        req.message,
        messages=snapshot.get("messages") or [],
    )
    await conversation_store.add_message(
        conversation_id,
        "assistant",
        "clarification" if clarification.get("needs_clarification") else "crawler_brief",
        clarification.get("question") or clarification.get("crawler_brief", {}).get("goal") or "",
        clarification,
    )
    return {"ok": True, "clarification": clarification}


@app.post("/ai/conversations/{conversation_id}/crawler-brief", dependencies=[Depends(require_api_key)])
async def build_ai_conversation_crawler_brief(conversation_id: str, req: BuildCrawlerBriefReq):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    brief_result = await clarification_service.build_crawler_brief(
        original_request=req.original_request,
        selections=req.selections,
        free_text=req.free_text,
    )
    crawler_brief = brief_result["crawler_brief"]
    await conversation_store.add_message(
        conversation_id,
        "assistant",
        "crawler_brief",
        crawler_brief.get("goal") or "已生成爬虫 brief",
        brief_result,
    )
    await conversation_store.update_context(
        conversation_id,
        latest_crawler_brief=crawler_brief,
    )
    return {"ok": True, "brief": brief_result}
```

- [ ] **Step 5: Verify Task 3**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py test_agent_api.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add crawler/ai_api.py crawler/test_workbench.py
git commit -m "feat(ai): add conversation workbench api"
```

---

## Task 4: Brief-Aware Discovery Jobs And Partial Crawler Status

**Files:**
- Modify: `crawler/ai_schema.sql`
- Modify: `crawler/ai_api.py`
- Modify: `crawler/discovery.py`
- Modify: `crawler/server.py`
- Modify: `crawler/test_workbench.py`

- [ ] **Step 1: Add failing partial-status and brief payload tests**

Append to `crawler/test_workbench.py`:

```python
from discovery import derive_search_queries_from_brief


class DiscoveryBriefTests(unittest.TestCase):
    def test_derive_search_queries_from_brief_prefers_llm_queries(self):
        brief = {
            "country": "英国",
            "content_scenes": ["生活类"],
            "expression_types": ["经验型"],
            "search_queries": ["英国留学 生活 真实经验", "英国留学生 日常 吐槽"],
        }

        queries = derive_search_queries_from_brief("帮我找英国方面的素材", brief, max_queries=4)

        self.assertEqual(queries[:2], ["英国留学 生活 真实经验", "英国留学生 日常 吐槽"])

    def test_derive_search_queries_from_brief_builds_fallback_queries(self):
        brief = {
            "country": "英国",
            "content_scenes": ["作业论文考试类"],
            "expression_types": ["避坑警示"],
            "search_queries": [],
        }

        queries = derive_search_queries_from_brief("帮我找英国方面的素材", brief, max_queries=4)

        self.assertIn("英国留学 论文 考试", queries[0])
        self.assertLessEqual(len(queries), 4)
```

Add this async API test:

```python
class DiscoveryJobApiBriefTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_service = getattr(ai_api, "discovery_service", None)
        self.created_payloads = []

        class FakeDiscoveryService:
            def __init__(inner_self, outer):
                inner_self.outer = outer

            def create_job(inner_self, **payload):
                inner_self.outer.created_payloads.append(payload)
                return {"id": "job-1", **payload, "status": "pending"}

        ai_api.discovery_service = FakeDiscoveryService(self)

    def tearDown(self):
        ai_api.discovery_service = self.original_service

    async def test_create_discovery_job_accepts_crawler_brief(self):
        req = ai_api.CreateDiscoveryJobReq(
            user_question="帮我找英国方面的素材",
            task_type="material",
            trigger_reason="user_requested",
            internal_answer_payload={},
            crawler_brief={
                "country": "英国",
                "search_queries": ["英国留学 生活 真实经验"],
                "quality_targets": ["高收藏"],
                "exclusions": ["机构广告"],
            },
            conversation_id="00000000-0000-0000-0000-000000000001",
        )

        result = await ai_api.create_discovery_job(req)

        self.assertEqual(result["job"]["search_queries"], ["英国留学 生活 真实经验"])
        self.assertEqual(self.created_payloads[0]["crawler_brief"]["country"], "英国")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py
```

Expected: fail because `derive_search_queries_from_brief`, `crawler_brief`, and `conversation_id` support do not exist.

- [ ] **Step 3: Update schema for brief fields and `partial`**

Modify `external_discovery_jobs.status` in `crawler/ai_schema.sql`. Because Postgres check constraints need named handling, append:

```sql
alter table external_discovery_jobs
  add column if not exists crawler_brief jsonb not null default '{}'::jsonb;

alter table external_discovery_jobs
  add column if not exists quality_targets text[] not null default '{}';

alter table external_discovery_jobs
  add column if not exists exclusions text[] not null default '{}';

alter table external_discovery_jobs
  add column if not exists candidate_scoring_hint text;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'external_discovery_jobs_status_check'
      and conrelid = 'external_discovery_jobs'::regclass
  ) then
    alter table external_discovery_jobs drop constraint external_discovery_jobs_status_check;
  end if;
end $$;

alter table external_discovery_jobs
  add constraint external_discovery_jobs_status_check
  check (status in ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled'));
```

- [ ] **Step 4: Add brief query helper**

Add to `crawler/discovery.py`:

```python
def derive_search_queries_from_brief(question: str, crawler_brief: dict, max_queries: int = 4) -> list[str]:
    provided = [
        str(query).strip()
        for query in (crawler_brief or {}).get("search_queries") or []
        if str(query).strip()
    ]
    if provided:
        return provided[:max_queries]

    country = (crawler_brief or {}).get("country") or "英国"
    scenes = (crawler_brief or {}).get("content_scenes") or []
    expressions = (crawler_brief or {}).get("expression_types") or []
    scene = scenes[0] if scenes else "生活类"
    expression = expressions[0] if expressions else "经验型"
    scene_term = {
        "生活类": "生活",
        "申请类": "申请",
        "作业论文考试类": "论文 考试",
        "住宿租房": "租房",
        "校园日常": "校园 日常",
        "就业实习": "就业 实习",
    }.get(scene, scene)
    expression_term = {
        "经验型": "真实经验",
        "吐槽型": "吐槽",
        "干货攻略": "攻略",
        "避坑警示": "避坑",
        "情绪共鸣": "日常",
    }.get(expression, expression)
    queries = [
        f"{country}留学 {scene_term} {expression_term}",
        f"{country}留学生 {scene_term} 小红书",
        f"{country}留学 {scene_term} 避坑",
        f"{country}留学生 {expression_term}",
    ]
    return queries[:max_queries]
```

- [ ] **Step 5: Update discovery job request and creation**

In `crawler/ai_api.py`, extend `CreateDiscoveryJobReq`:

```python
class CreateDiscoveryJobReq(BaseModel):
    user_question: str
    task_type: Literal["material", "experience", "image_reference", "mixed"] = "material"
    trigger_reason: Literal["sparse_recall", "zero_recall", "user_requested"] = "user_requested"
    internal_answer_payload: Dict[str, Any] = Field(default_factory=dict)
    search_queries: Optional[List[str]] = None
    benchmark_account_ids: List[str] = Field(default_factory=list)
    created_by_member_id: Optional[str] = None
    crawler_brief: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[str] = None
```

In `create_discovery_job`, derive queries this way:

```python
queries = req.search_queries
if not queries and req.crawler_brief:
    queries = derive_search_queries_from_brief(req.user_question, req.crawler_brief, max_queries=4)
if not queries:
    queries = derive_search_queries(req.user_question, max_queries=4)
job = discovery_service.create_job(
    user_question=req.user_question,
    task_type=req.task_type,
    trigger_reason=req.trigger_reason,
    internal_answer_payload=req.internal_answer_payload,
    search_queries=queries,
    benchmark_account_ids=req.benchmark_account_ids,
    created_by_member_id=req.created_by_member_id,
    crawler_brief=req.crawler_brief,
    quality_targets=req.crawler_brief.get("quality_targets") or [],
    exclusions=req.crawler_brief.get("exclusions") or [],
    candidate_scoring_hint=req.crawler_brief.get("candidate_scoring_hint"),
    conversation_id=req.conversation_id,
)
```

- [ ] **Step 6: Update `DiscoveryService.create_job` signature**

In `crawler/discovery_service.py`, add optional payload fields and insert them:

```python
def create_job(
    self,
    user_question: str,
    task_type: str,
    trigger_reason: str,
    internal_answer_payload: Dict[str, Any],
    search_queries: Optional[List[str]] = None,
    benchmark_account_ids: Optional[List[str]] = None,
    created_by_member_id: Optional[str] = None,
    crawler_brief: Optional[Dict[str, Any]] = None,
    quality_targets: Optional[List[str]] = None,
    exclusions: Optional[List[str]] = None,
    candidate_scoring_hint: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    queries = search_queries or derive_search_queries(user_question)
    payload = {
        "user_question": user_question,
        "task_type": task_type,
        "trigger_reason": trigger_reason,
        "internal_answer_payload": internal_answer_payload or {},
        "search_queries": queries,
        "benchmark_account_ids": benchmark_account_ids or [],
        "created_by_member_id": created_by_member_id,
        "crawler_brief": crawler_brief or {},
        "quality_targets": quality_targets or [],
        "exclusions": exclusions or [],
        "candidate_scoring_hint": candidate_scoring_hint,
        "conversation_id": conversation_id,
    }
    res = self.sb.table("external_discovery_jobs").insert([payload]).execute()
    return self._first_row(res.data) or payload
```

- [ ] **Step 7: Make crawler execution partial-tolerant**

In `crawler/server.py`, inside `process_external_discovery_jobs`, change per-note fetch logic from one outer exception for the whole job to counters:

```python
fetch_error_count = 0
fetch_errors = []
```

Wrap only `fetch_post_data(fetch_url)`:

```python
try:
    post_data = await fetch_post_data(fetch_url)
except Exception as fetch_error:
    fetch_error_count += 1
    fetch_errors.append(str(fetch_error)[:160])
    log.warning(f"  ⚠️ 外部发现候选详情抓取失败，跳过 note_id={note_id}: {fetch_error}")
    continue
post_data["url"] = url
await upsert_discovery_candidate(job_id, "keyword_search", {"search_query": query}, post_data)
stored_count += 1
```

At final update, replace the unconditional `completed` update with:

```python
final_status = "completed"
error_message = None
if stored_count > 0 and fetch_error_count > 0:
    final_status = "partial"
    error_message = f"{fetch_error_count} 条候选详情抓取失败；已保留可用候选。"
elif stored_count == 0 and fetch_error_count > 0:
    final_status = "failed"
    error_message = "; ".join(fetch_errors[:3]) or "没有抓到可用候选。"

sb.table("external_discovery_jobs").update({
    "status": final_status,
    "error_message": error_message,
    "finished_at": now_iso(),
    "updated_at": now_iso(),
}).eq("id", job_id).execute()
```

Do not catch Supabase write errors as per-note errors. Supabase write failures should still fail the job because candidates cannot be stored.

- [ ] **Step 8: Verify Task 4**

Run:

```bash
cd crawler && python3 -m unittest test_workbench.py test_discovery.py
```

Expected: all tests pass.

- [ ] **Step 9: Commit Task 4**

```bash
git add crawler/ai_schema.sql crawler/ai_api.py crawler/discovery.py crawler/discovery_service.py crawler/server.py crawler/test_workbench.py
git commit -m "feat(crawler): support clarified briefs and partial jobs"
```

---

## Task 5: Frontend Workbench Helpers And API Client

**Files:**
- Create: `src/aiWorkbench.js`
- Create: `src/aiWorkbenchApi.js`
- Create: `src/aiWorkbench.test.js`
- Modify: `package.json`

- [ ] **Step 1: Add frontend helper tests**

Create `src/aiWorkbench.test.js`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";

import {
  buildBriefRequest,
  getConversationTitle,
  mergeConversationMessages,
  summarizeJobStatus,
} from "./aiWorkbench.js";

test("getConversationTitle uses explicit title before first message", () => {
  assert.equal(getConversationTitle({ title: "英国素材调研" }, []), "英国素材调研");
  assert.equal(
    getConversationTitle({ title: "新对话" }, [{ role: "user", content: "帮我找英国方面的素材" }]),
    "帮我找英国方面的素材",
  );
});

test("mergeConversationMessages appends new messages without duplicating ids", () => {
  const result = mergeConversationMessages(
    [{ id: "m1", content: "old" }],
    [{ id: "m1", content: "old updated" }, { id: "m2", content: "new" }],
  );

  assert.deepEqual(result.map(item => item.id), ["m1", "m2"]);
  assert.equal(result[0].content, "old updated");
});

test("buildBriefRequest preserves selections and free text", () => {
  const result = buildBriefRequest({
    originalRequest: "帮我找英国方面的素材",
    selections: { content_scene: ["life"], expression_type: ["experience"] },
    freeText: "不要机构广告",
  });

  assert.equal(result.original_request, "帮我找英国方面的素材");
  assert.deepEqual(result.selections.content_scene, ["life"]);
  assert.equal(result.free_text, "不要机构广告");
});

test("summarizeJobStatus treats partial as usable", () => {
  assert.equal(summarizeJobStatus("partial").label, "部分完成");
  assert.equal(summarizeJobStatus("partial").canReviewCandidates, true);
  assert.equal(summarizeJobStatus("failed").canReviewCandidates, false);
});
```

Update `package.json` `test:frontend` script:

```json
"test:frontend": "node --test src/runtimeConfig.test.js src/aiDiscovery.test.js src/designSystem.test.js src/aiWorkbench.test.js"
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```bash
npm run test:frontend
```

Expected: fail because `src/aiWorkbench.js` does not exist.

- [ ] **Step 3: Implement pure frontend helpers**

Create `src/aiWorkbench.js`:

```javascript
export function getConversationTitle(conversation, messages = []) {
  const title = conversation?.title?.trim();
  if (title && title !== "新对话") return title;
  const firstUser = messages.find(message => message.role === "user" && message.content?.trim());
  return firstUser?.content?.trim()?.slice(0, 28) || "新对话";
}

export function mergeConversationMessages(prev = [], next = []) {
  const map = new Map(prev.map(message => [message.id, message]));
  for (const message of next) {
    map.set(message.id, { ...(map.get(message.id) || {}), ...message });
  }
  return [...map.values()].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
}

export function buildBriefRequest({ originalRequest, selections, freeText }) {
  return {
    original_request: originalRequest,
    selections: selections || {},
    free_text: freeText || "",
  };
}

export function summarizeJobStatus(status) {
  const map = {
    pending: { label: "等待开始", tone: "muted", canReviewCandidates: false },
    running: { label: "正在发现", tone: "info", canReviewCandidates: false },
    completed: { label: "已完成", tone: "success", canReviewCandidates: true },
    partial: { label: "部分完成", tone: "warning", canReviewCandidates: true },
    failed: { label: "失败", tone: "danger", canReviewCandidates: false },
    cancelled: { label: "已取消", tone: "muted", canReviewCandidates: false },
  };
  return map[status] || { label: status || "未知", tone: "muted", canReviewCandidates: false };
}
```

- [ ] **Step 4: Implement conversation API client**

Create `src/aiWorkbenchApi.js`:

```javascript
import { resolveAiApiConfig } from "./runtimeConfig.js";

async function readErrorMessage(resp) {
  try {
    const data = await resp.json();
    return data?.detail || data?.message || "";
  } catch {
    return resp.text().catch(() => "");
  }
}

async function requestJson(path, options = {}) {
  const { baseUrl, apiKey } = resolveAiApiConfig();
  const resp = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) {
    throw new Error((await readErrorMessage(resp)) || "AI 工作台服务暂时不可用，请稍后再试。");
  }
  return resp.json();
}

export function listConversations() {
  return requestJson("/ai/conversations", { method: "GET" });
}

export function createConversation(payload = {}) {
  return requestJson("/ai/conversations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getConversation(conversationId) {
  return requestJson(`/ai/conversations/${conversationId}`, { method: "GET" });
}

export function clarifyConversation(conversationId, message) {
  return requestJson(`/ai/conversations/${conversationId}/clarify`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function buildCrawlerBrief(conversationId, payload) {
  return requestJson(`/ai/conversations/${conversationId}/crawler-brief`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 5: Verify Task 5**

Run:

```bash
npm run test:frontend
```

Expected: all frontend helper tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add package.json src/aiWorkbench.js src/aiWorkbenchApi.js src/aiWorkbench.test.js
git commit -m "feat(ui): add ai workbench client helpers"
```

---

## Task 6: Unified Workbench UI

**Files:**
- Create: `src/components/AIWorkbenchPage.jsx`
- Create: `src/components/DiscoveryCandidateCard.jsx`
- Modify: `src/components/AISearchPage.jsx`
- Modify: `src/App.jsx`

- [ ] **Step 1: Extract shared discovery candidate card**

Move `DiscoveryCandidateCard` from `src/components/AISearchPage.jsx` into `src/components/DiscoveryCandidateCard.jsx`.

The exported component signature should be:

```javascript
export default function DiscoveryCandidateCard({ candidate, onReview, isReviewing }) {
  return null;
}
```

Replace `return null` with the existing JSX from `AISearchPage`. Keep these button actions:

```javascript
onClick={() => onReview(candidate, "approve")}
onClick={() => onReview(candidate, "ignore")}
onClick={() => onReview(candidate, "reject")}
```

In `src/components/AISearchPage.jsx`, import it:

```javascript
import DiscoveryCandidateCard from "./DiscoveryCandidateCard.jsx";
```

Remove the local `DiscoveryCandidateCard` function from `AISearchPage`.

- [ ] **Step 2: Create `AIWorkbenchPage.jsx` shell**

Create `src/components/AIWorkbenchPage.jsx` with these state sections:

```javascript
import { useEffect, useMemo, useState } from "react";
import { Bot, CheckCircle2, Loader2, Plus, Send, Sparkles } from "lucide-react";
import {
  buildCrawlerBrief,
  clarifyConversation,
  createConversation,
  getConversation,
  listConversations,
} from "../aiWorkbenchApi.js";
import { buildBriefRequest, getConversationTitle, summarizeJobStatus } from "../aiWorkbench.js";
import { createDiscoveryJob, getDiscoveryJob, approveDiscoveryCandidate, ignoreDiscoveryCandidate, rejectDiscoveryCandidate } from "../aiApi.js";
import { Card, EmptyState, inputStyle, useIsMobile, useToast, createGlassCardStyle, createPrimaryButtonStyle, designTokens } from "./shared.jsx";
import DiscoveryCandidateCard from "./DiscoveryCandidateCard.jsx";

export default function AIWorkbenchPage() {
  const isMobile = useIsMobile();
  const toast = useToast();
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [context, setContext] = useState({});
  const [prompt, setPrompt] = useState("");
  const [clarification, setClarification] = useState(null);
  const [selections, setSelections] = useState({});
  const [freeText, setFreeText] = useState("");
  const [crawlerBrief, setCrawlerBrief] = useState(null);
  const [discoveryJob, setDiscoveryJob] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [reviewingCandidateId, setReviewingCandidateId] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    loadConversations().catch(error => setError(error.message || "读取历史对话失败"));
  }, []);

  const activeTitle = useMemo(
    () => getConversationTitle(activeConversation, messages),
    [activeConversation, messages],
  );

  async function loadConversations() {
    const payload = await listConversations();
    setConversations(payload.conversations || []);
  }

  async function openConversation(conversationId) {
    const snapshot = await getConversation(conversationId);
    setActiveConversation(snapshot.conversation);
    setMessages(snapshot.messages || []);
    setContext(snapshot.context || {});
    setCrawlerBrief(snapshot.context?.latest_crawler_brief || null);
    setClarification(null);
    setSelections({});
    setFreeText("");
    setPrompt("");
  }

  async function startNewConversation() {
    const created = await createConversation({ title: "新对话" });
    setConversations(prev => [created.conversation, ...prev]);
    await openConversation(created.conversation.id);
  }

  async function ensureConversation() {
    if (activeConversation?.id) return activeConversation;
    const created = await createConversation({ title: "新对话" });
    setConversations(prev => [created.conversation, ...prev]);
    setActiveConversation(created.conversation);
    setMessages([]);
    setContext({});
    return created.conversation;
  }

  async function submitPrompt() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      const conversation = await ensureConversation();
      const result = await clarifyConversation(conversation.id, prompt.trim());
      const snapshot = await getConversation(conversation.id);
      setActiveConversation(snapshot.conversation);
      setMessages(snapshot.messages || []);
      setContext(snapshot.context || {});
      setClarification(result.clarification);
      setCrawlerBrief(result.clarification?.crawler_brief || null);
      setPrompt("");
      await loadConversations();
    } catch (error) {
      setError(error.message || "提交失败");
    } finally {
      setLoading(false);
    }
  }

  function toggleSelection(groupId, optionId, maxSelect) {
    setSelections(prev => {
      const current = prev[groupId] || [];
      const exists = current.includes(optionId);
      const next = exists ? current.filter(id => id !== optionId) : [...current, optionId].slice(-maxSelect);
      return { ...prev, [groupId]: next };
    });
  }

  async function generateBrief() {
    if (!activeConversation?.id || !clarification) return;
    setLoading(true);
    setError("");
    try {
      const originalRequest = [...messages].reverse().find(message => message.role === "user")?.content || "";
      const result = await buildCrawlerBrief(
        activeConversation.id,
        buildBriefRequest({ originalRequest, selections, freeText }),
      );
      setCrawlerBrief(result.brief.crawler_brief);
      const snapshot = await getConversation(activeConversation.id);
      setMessages(snapshot.messages || []);
      setContext(snapshot.context || {});
    } catch (error) {
      setError(error.message || "生成 brief 失败");
    } finally {
      setLoading(false);
    }
  }

  async function startDiscovery() {
    if (!crawlerBrief) return;
    setLoading(true);
    setError("");
    try {
      const jobResp = await createDiscoveryJob({
        user_question: crawlerBrief.goal,
        task_type: "material",
        trigger_reason: "user_requested",
        internal_answer_payload: { source: "ai_workbench", crawler_brief: crawlerBrief },
        search_queries: crawlerBrief.search_queries,
        crawler_brief: crawlerBrief,
        conversation_id: activeConversation?.id || null,
      });
      setDiscoveryJob(jobResp.job);
      setCandidates([]);
      toast("已启动精准发现");
    } catch (error) {
      setError(error.message || "启动外部发现失败");
    } finally {
      setLoading(false);
    }
  }

  async function refreshDiscovery() {
    if (!discoveryJob?.id) return;
    const payload = await getDiscoveryJob(discoveryJob.id);
    setDiscoveryJob(payload.job);
    setCandidates(payload.candidates || []);
  }

  async function reviewCandidate(candidate, action) {
    setReviewingCandidateId(candidate.id);
    try {
      const resp = action === "approve"
        ? await approveDiscoveryCandidate(candidate.id)
        : action === "ignore"
          ? await ignoreDiscoveryCandidate(candidate.id)
          : await rejectDiscoveryCandidate(candidate.id, "不相关");
      setCandidates(prev => prev.map(item => item.id === candidate.id ? { ...item, ...resp.candidate } : item));
    } catch (error) {
      setError(error.message || "候选操作失败");
    } finally {
      setReviewingCandidateId(null);
    }
  }

  const jobStatus = summarizeJobStatus(discoveryJob?.status);

  return (
    <div style={{ padding: isMobile ? 12 : 20, display: "grid", gridTemplateColumns: isMobile ? "1fr" : "240px minmax(0, 1fr) 340px", gap: 16 }}>
      <aside style={{ ...createGlassCardStyle({ padding: 14 }), minHeight: isMobile ? "auto" : "calc(100vh - 40px)" }}>
        <button type="button" onClick={startNewConversation} style={{ ...createPrimaryButtonStyle(), width: "100%", marginBottom: 12 }}>
          <Plus size={14} /> 新对话
        </button>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {conversations.map(conversation => (
            <button key={conversation.id} type="button" onClick={() => openConversation(conversation.id)} style={{
              textAlign: "left",
              border: `1px solid ${activeConversation?.id === conversation.id ? "rgba(255,36,66,0.35)" : designTokens.color.cardBorder}`,
              background: activeConversation?.id === conversation.id ? "rgba(255,36,66,0.1)" : "rgba(255,255,255,0.025)",
              color: activeConversation?.id === conversation.id ? "#fff" : designTokens.color.textMuted,
              borderRadius: 8,
              padding: 10,
              cursor: "pointer",
              fontSize: 12,
            }}>
              {conversation.title || "新对话"}
            </button>
          ))}
        </div>
      </aside>

      <main style={{ ...createGlassCardStyle({ padding: 16 }), minHeight: "calc(100vh - 40px)", display: "flex", flexDirection: "column" }}>
        <div style={{ fontSize: 18, fontWeight: 800, color: "#fff", marginBottom: 12 }}>{activeTitle}</div>
        {error && <div style={{ color: "#FF5C7A", marginBottom: 12, fontSize: 12 }}>{error}</div>}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
          {messages.length === 0 && <EmptyState title="开始一个 AI 工作台对话" description="例如：帮我找英国方面的素材" />}
          {messages.map(message => (
            <div key={message.id} style={{
              alignSelf: message.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "78%",
              background: message.role === "user" ? "rgba(255,36,66,0.14)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${designTokens.color.cardBorder}`,
              borderRadius: 12,
              padding: 12,
              color: "#e8e8e8",
              fontSize: 13,
              lineHeight: 1.7,
            }}>
              {message.content || message.payload?.question || message.message_type}
            </div>
          ))}
          {clarification?.needs_clarification && (
            <div style={{ ...createGlassCardStyle({ padding: 14 }), borderColor: "rgba(84,160,255,0.22)" }}>
              <div style={{ color: "#fff", fontWeight: 800, marginBottom: 8 }}>{clarification.question}</div>
              {clarification.option_groups.map(group => (
                <div key={group.id} style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, color: designTokens.color.textMuted, marginBottom: 8 }}>{group.label}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {group.options.map(option => {
                      const selected = (selections[group.id] || []).includes(option.id);
                      return (
                        <button key={option.id} type="button" onClick={() => toggleSelection(group.id, option.id, group.max_select)} style={{
                          border: `1px solid ${selected ? "rgba(255,36,66,0.45)" : designTokens.color.cardBorder}`,
                          background: selected ? "rgba(255,36,66,0.12)" : "rgba(255,255,255,0.03)",
                          color: selected ? "#FF2442" : designTokens.color.textMuted,
                          borderRadius: 999,
                          padding: "7px 10px",
                          cursor: "pointer",
                          fontSize: 12,
                        }}>
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              <textarea value={freeText} onChange={event => setFreeText(event.target.value)} aria-label={clarification.free_text_prompt} style={{ ...inputStyle, marginTop: 12, minHeight: 76 }} />
              <button type="button" onClick={generateBrief} disabled={loading} style={{ ...createPrimaryButtonStyle({ disabled: loading }), marginTop: 10 }}>
                {loading ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />} 生成搜索 brief
              </button>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <textarea value={prompt} onChange={event => setPrompt(event.target.value)} aria-label="输入运营目标或素材需求" style={{ ...inputStyle, minHeight: 54, resize: "vertical" }} />
          <button type="button" onClick={submitPrompt} disabled={loading || !prompt.trim()} style={{ ...createPrimaryButtonStyle({ disabled: loading || !prompt.trim() }), alignSelf: "stretch" }}>
            {loading ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
          </button>
        </div>
      </main>

      <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Card title="爬虫 Brief">
          {crawlerBrief ? (
            <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.7 }}>
              <div style={{ color: "#fff", fontWeight: 700 }}>{crawlerBrief.goal}</div>
              <div style={{ marginTop: 8 }}>搜索词：{(crawlerBrief.search_queries || []).join(" / ")}</div>
              <button type="button" onClick={startDiscovery} disabled={loading} style={{ ...createPrimaryButtonStyle({ disabled: loading }), marginTop: 12 }}>
                <Sparkles size={14} /> 确认并启动精准发现
              </button>
            </div>
          ) : (
            <EmptyState title="暂无 brief" description="泛需求会先通过反问生成 brief。" />
          )}
        </Card>
        <Card title="外部发现">
          {discoveryJob ? (
            <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.7 }}>
              <div>状态：{jobStatus.label}</div>
              <button type="button" onClick={refreshDiscovery} style={{ marginTop: 10, ...createGlassCardStyle({ padding: 8 }) }}>刷新</button>
            </div>
          ) : (
            <EmptyState title="未启动" description="确认 brief 后开始抓取候选素材。" />
          )}
        </Card>
        {candidates.map(candidate => (
          <DiscoveryCandidateCard key={candidate.id} candidate={candidate} onReview={reviewCandidate} isReviewing={reviewingCandidateId === candidate.id} />
        ))}
      </aside>
    </div>
  );
}
```

- [ ] **Step 3: Wire App to the new workbench**

In `src/App.jsx`, add:

```javascript
const AIWorkbenchPage = lazy(() => import("./components/AIWorkbenchPage.jsx"));
```

Replace the AI mode switch block inside `{shouldRenderAi && (...)}` with:

```javascript
{shouldRenderAi && (
  <div style={{ display: view === "ai" ? "block" : "none" }}>
    <AIWorkbenchPage />
  </div>
)}
```

Keep the old `AISearchPage` and `AgentPage` files in the repo for reference and gradual migration.

- [ ] **Step 4: Verify Task 6**

Run:

```bash
npm run test:frontend
npm run build
```

Expected: tests pass and Vite build completes.

- [ ] **Step 5: Commit Task 6**

```bash
git add src/App.jsx src/components/AIWorkbenchPage.jsx src/components/DiscoveryCandidateCard.jsx src/components/AISearchPage.jsx
git commit -m "feat(ui): add unified ai workbench"
```

---

## Task 7: End-To-End Verification And Database Migration Note

**Files:**
- Modify: `docs/superpowers/specs/2026-05-17-ai-workbench-clarifying-crawler-design.md`
- Modify: `docs/superpowers/plans/2026-05-17-ai-workbench-clarifying-crawler.md`

- [ ] **Step 1: Run backend verification**

Run:

```bash
npm run test:ai
npm run test:agent
cd crawler && python3 -m unittest test_workbench.py
```

Expected:

- `test:ai` passes.
- `test:agent` passes.
- `test_workbench.py` passes.

- [ ] **Step 2: Run frontend verification**

Run:

```bash
npm run test:frontend
npm run build
```

Expected:

- Frontend tests pass.
- Vite production build succeeds.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Apply Supabase SQL manually or provide migration block**

If the local API logs show missing columns or tables, open:

`https://supabase.com/dashboard/project/nlsgqlkqimedgftkmzxn/sql/new`

Run the updated `crawler/ai_schema.sql` sections for:

- `ai_conversations`
- `ai_messages`
- `ai_conversation_context`
- `conversation_id` link columns
- `external_discovery_jobs` crawler brief fields
- `external_discovery_jobs.status` `partial` check constraint

- [ ] **Step 5: Manual browser verification**

Start services:

```bash
cd crawler && python3 ai_api.py
npm run dev -- --host 127.0.0.1
```

Open:

`http://127.0.0.1:5173/`

Manual flow:

1. Open AI 工作台.
2. Start a new chat.
3. Enter `帮我找英国方面的素材`.
4. Confirm clarification cards render.
5. Select `生活类` and `经验型`.
6. Enter free text `不要机构广告，偏真实留学生日常`.
7. Generate crawler brief.
8. Confirm and start discovery.
9. Refresh external discovery until candidates appear.
10. Confirm `partial` jobs still show usable candidates.
11. Approve one candidate.
12. Confirm approved candidate is marked and appears in material library after embedding worker runs.

- [ ] **Step 6: Final commit and push**

Run:

```bash
git status -sb
git log --oneline -5
git push
```

Expected:

- Only intentional tracked changes are committed.
- Untracked `.superpowers/`, `.playwright-cli/`, and `output/` are not included.
- Remote branch receives the implementation commits.

---

## Self-Review Checklist

- Spec coverage:
  - Unified ChatGPT-style workbench: Task 6.
  - Conversation history and continuing conversations: Tasks 1, 3, 5, 6.
  - LLM clarification layer: Task 2.
  - Crawler brief before external discovery: Tasks 2, 3, 4, 6.
  - Partial crawler status: Task 4.
  - Candidate approval remains available: Task 6.
  - Testing and manual verification: Task 7.
- Type consistency:
  - Backend uses `crawler_brief`, `conversation_id`, `option_groups`, `selections`, and `free_text`.
  - Frontend sends `original_request`, `selections`, and `free_text` to match FastAPI models.
  - Job status includes `partial` in backend schema and frontend status helper.
- Scope:
  - First version excludes multi-user project management, prompt library management, and LLM reranking.
  - Existing AI search and Agent pages remain available in source files during migration.
