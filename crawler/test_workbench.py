import asyncio
import ast
from pathlib import Path
from typing import List, Optional, Tuple
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

    async def test_valid_llm_direct_brief_payload_is_accepted(self):
        payload = {
            "needs_clarification": False,
            "detected_country": "英国",
            "question": "",
            "option_groups": [],
            "free_text_prompt": "",
            "crawler_brief": {
                "goal": "寻找英国留学生活类真实经验素材",
                "country": "英国",
                "audiences": ["本科"],
                "content_scenes": ["生活类"],
                "expression_types": ["经验型"],
                "quality_targets": ["高收藏"],
                "exclusions": ["机构广告"],
                "search_queries": ["英国留学 生活 真实经验"],
                "candidate_scoring_hint": "优先真人经验",
            },
        }

        def valid_completion(**kwargs):
            return payload

        service = ClarificationService(structured_completion=valid_completion, text_model="unit-test-model")

        result = await service.clarify_request("帮我找英国留学生活类真实经验素材，不要机构广告")

        self.assertFalse(result["needs_clarification"])
        self.assertEqual(result["crawler_brief"]["country"], "英国")

    async def test_llm_false_without_brief_falls_back_to_clarification(self):
        def invalid_completion(**kwargs):
            return {
                "needs_clarification": False,
                "detected_country": "英国",
                "question": "",
                "option_groups": [],
                "free_text_prompt": "",
            }

        service = ClarificationService(structured_completion=invalid_completion, text_model="unit-test-model")

        result = await service.clarify_request("帮我找英国方面的素材")

        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["detected_country"], "英国")

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
from discovery import derive_search_queries_from_brief


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

    async def test_clarify_conversation_direct_brief_updates_context(self):
        class DirectBriefClarifier:
            async def clarify_request(inner_self, message, messages=None):
                return {
                    "needs_clarification": False,
                    "crawler_brief": {
                        "goal": "寻找英国留学生活类真实经验素材",
                        "country": "英国",
                        "search_queries": ["英国留学 生活 真实经验"],
                    },
                }

        ai_api.clarification_service = DirectBriefClarifier()
        created = await ai_api.create_ai_conversation(ai_api.CreateConversationReq(title="英国素材"))
        conversation_id = created["conversation"]["id"]

        result = await ai_api.clarify_ai_conversation(
            conversation_id,
            ai_api.ClarifyConversationReq(message="帮我找英国留学生活类真实经验素材"),
        )
        snapshot = await ai_api.get_ai_conversation(conversation_id)

        self.assertFalse(result["clarification"]["needs_clarification"])
        self.assertEqual(snapshot["context"]["latest_crawler_brief"]["country"], "英国")


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

    def test_derive_search_queries_from_brief_normalizes_malformed_values(self):
        brief = {
            "country": ["英国"],
            "content_scenes": "住宿租房",
            "expression_types": "干货攻略",
            "search_queries": "英国留学 租房 攻略",
        }

        queries = derive_search_queries_from_brief("帮我找英国方面的素材", brief, max_queries=4)

        self.assertEqual(queries, ["英国留学 租房 攻略"])

    def test_derive_search_queries_from_brief_falls_back_for_invalid_country(self):
        brief = {
            "country": "火星",
            "content_scenes": "住宿租房",
            "expression_types": "干货攻略",
            "search_queries": [],
        }

        queries = derive_search_queries_from_brief("帮我找英国方面的素材", brief, max_queries=4)

        self.assertEqual(queries[0], "英国留学 租房 攻略")


def load_server_helper(name):
    server_path = Path(__file__).with_name("server.py")
    module_ast = ast.parse(server_path.read_text(encoding="utf-8"))
    function_ast = next(
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function_ast], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"List": List, "Optional": Optional, "Tuple": Tuple}
    exec(compile(module, str(server_path), "exec"), namespace)
    return namespace[name]


class DiscoveryFinalStatusTests(unittest.TestCase):
    def test_resolve_external_discovery_final_status(self):
        resolve_status = load_server_helper("resolve_external_discovery_final_status")

        self.assertEqual(
            resolve_status(0, 0, []),
            ("failed", "没有抓到可用候选。"),
        )
        self.assertEqual(
            resolve_status(3, 2, ["timeout"]),
            ("partial", "2 条候选详情抓取失败；已保留可用候选。"),
        )
        self.assertEqual(resolve_status(3, 0, []), ("completed", None))


class DiscoveryJobApiBriefTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_service = getattr(ai_api, "discovery_service", None)
        self.original_store = getattr(ai_api, "conversation_store", None)
        ai_api.conversation_store = ConversationStore()
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
        ai_api.conversation_store = self.original_store

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
        )

        result = await ai_api.create_discovery_job(req)

        self.assertEqual(result["job"]["search_queries"], ["英国留学 生活 真实经验"])
        self.assertEqual(self.created_payloads[0]["crawler_brief"]["country"], "英国")

    async def test_create_discovery_job_updates_conversation_context(self):
        created = await ai_api.create_ai_conversation(ai_api.CreateConversationReq(title="英国素材"))
        conversation_id = created["conversation"]["id"]
        req = ai_api.CreateDiscoveryJobReq(
            user_question="帮我找英国方面的素材",
            task_type="material",
            trigger_reason="user_requested",
            internal_answer_payload={},
            crawler_brief={
                "country": "英国",
                "search_queries": ["英国留学 生活 真实经验"],
            },
            conversation_id=conversation_id,
        )

        result = await ai_api.create_discovery_job(req)
        snapshot = await ai_api.get_ai_conversation(conversation_id)

        self.assertEqual(result["job"]["id"], "job-1")
        self.assertEqual(snapshot["context"]["active_discovery_job_id"], "job-1")
