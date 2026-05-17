import asyncio
import unittest

from agent.conversation_store import ConversationStore
from clarification_service import ClarificationService


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

    async def test_build_crawler_brief_includes_secondary_scene_queries(self):
        service = ClarificationService(structured_completion=None)

        brief = await service.build_crawler_brief(
            original_request="帮我找英国方面的素材",
            selections={
                "content_scene": ["life", "housing"],
                "expression_type": ["experience"],
            },
        )

        queries = brief["crawler_brief"]["search_queries"]

        self.assertIn("住宿租房", brief["crawler_brief"]["content_scenes"])
        self.assertTrue(any("租房" in query for query in queries))
        self.assertLessEqual(len(queries), 4)

    async def test_valid_llm_payload_uses_configured_model_and_returns_payload(self):
        calls = []
        payload = {
            "needs_clarification": True,
            "detected_country": "美国",
            "question": "你想找美国哪个方向？",
            "option_groups": [
                {"id": "content_scene", "label": "内容场景", "max_select": 2, "options": []},
            ],
            "free_text_prompt": "补充偏好",
        }

        def valid_completion(**kwargs):
            calls.append(kwargs)
            return payload

        service = ClarificationService(structured_completion=valid_completion, text_model="unit-test-model")

        result = await service.clarify_request("帮我找美国方面的素材")

        self.assertEqual(result, payload)
        self.assertEqual(calls[0]["model"], "unit-test-model")

    async def test_structured_completion_requires_configured_model(self):
        def valid_completion(**kwargs):
            return {"needs_clarification": True, "option_groups": []}

        with self.assertRaisesRegex(ValueError, "text_model is required"):
            ClarificationService(structured_completion=valid_completion)

    async def test_invalid_llm_payload_falls_back_to_deterministic_brief(self):
        def invalid_completion(**kwargs):
            return {"broken": True}

        service = ClarificationService(structured_completion=invalid_completion, text_model="unit-test-model")

        result = await service.clarify_request("帮我找新加坡申请素材")

        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["detected_country"], "新加坡")


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
