import asyncio
import json
import math
import unittest
from types import SimpleNamespace

import ai_api
from discovery import (
    build_candidate_url,
    candidate_dedupe_key,
    derive_search_queries,
    normalize_question,
    score_candidate,
    validate_external_candidate_ids,
)
import research_service
import discovery_service
from ai_api import CreateDiscoveryJobReq, ReviewCandidateReq
from discovery_service import DiscoveryService
from research_models import ResearchAnswer, ResearchRequest
from research_service import model_to_dict
from retrieval_pipeline import parse_query_fallback


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
        self.upsert_payload = None
        self.upsert_on_conflict = None

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

    def in_(self, column, values):
        self.calls.append(("in_", column, values))
        return self

    def or_(self, clauses):
        self.calls.append(("or_", clauses))
        return self

    def single(self):
        self.calls.append(("single",))
        return self

    def maybe_single(self):
        self.calls.append(("maybe_single",))
        return self

    def order(self, column, desc=False):
        self.calls.append(("order", column, desc))
        return self

    def update(self, payload):
        self.calls.append(("update", payload))
        self.update_payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.calls.append(("upsert", payload, on_conflict))
        self.upsert_payload = payload
        self.upsert_on_conflict = on_conflict
        return self

    def limit(self, count):
        self.calls.append(("limit", count))
        return self

    def execute(self):
        self.calls.append(("execute",))
        if self.insert_payload is not None:
            if self.name in self.client.insert_responses:
                return FakeResult(self.client.insert_responses[self.name])
            return FakeResult(self.insert_payload)
        if self.update_payload is not None:
            if self.name in self.client.update_response_sequences and self.client.update_response_sequences[self.name]:
                return FakeResult(self.client.update_response_sequences[self.name].pop(0))
            if self.name in self.client.update_responses:
                return FakeResult(self.client.update_responses[self.name])
            return FakeResult([self.update_payload])
        if self.upsert_payload is not None:
            self.client.upserts.append({
                "table": self.name,
                "payload": self.upsert_payload,
                "on_conflict": self.upsert_on_conflict,
            })
            if self.name in self.client.upsert_responses:
                return FakeResult(self.client.upsert_responses[self.name])
            return FakeResult([self.upsert_payload])
        if self.name in self.client.response_sequences and self.client.response_sequences[self.name]:
            return FakeResult(self.client.response_sequences[self.name].pop(0))
        return FakeResult(self.client.responses.get(self.name, []))


class FakeRpc:
    def __init__(self, name, params, client):
        self.name = name
        self.params = params
        self.client = client

    def execute(self):
        if self.client.rpc_errors:
            raise self.client.rpc_errors.pop(0)
        return FakeResult(self.client.responses.get(self.name, []))


class FakeSupabase:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.response_sequences = {}
        self.insert_responses = {}
        self.update_responses = {}
        self.update_response_sequences = {}
        self.upsert_responses = {}
        self.upserts = []
        self.tables = []
        self.rpc_calls = []
        self.rpc_errors = []

    def table(self, name):
        table = FakeTable(name, self)
        self.tables.append(table)
        return table

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return FakeRpc(name, params, self)


class FakeSearchClient:
    async def search_note(self, keyword, page=1, page_size=10, sort="general"):
        return {
            "items": [
                {"note_id": "n1", "display_title": keyword, "xsec_token": "token"}
            ]
        }


class FakeKeywordClient:
    async def get_note_by_keyword(self, keyword, page=1, page_size=10, sort=None):
        self.assert_sort(sort)
        return {
            "items": [
                {"note_id": "n2", "display_title": keyword, "xsec_token": "token2"}
            ]
        }

    def assert_sort(self, sort):
        if not hasattr(sort, "value"):
            raise AttributeError("sort must expose value")
        if sort.value not in ("popularity_descending", "general"):
            raise AssertionError(f"unexpected sort value: {sort.value}")


class FakeExplodingSearchClient:
    def __init__(self, message="api exploded"):
        self.calls = 0
        self.message = message

    async def search_note(self, keyword, page=1, page_size=10, sort=None):
        self.calls += 1
        raise AttributeError(self.message)


class FakeTypeErrorSearchClient:
    def __init__(self, message):
        self.calls = 0
        self.message = message

    async def search_note(self, keyword, page=1, page_size=10, sort=None):
        self.calls += 1
        raise TypeError(self.message)


class FakeSignatureMismatchSearchClient:
    def __init__(self):
        self.calls = 0

    async def search_note(self, keyword, page=1, page_size=10, sort=None):
        self.calls += 1
        if sort is not None:
            raise TypeError("search_note() got an unexpected keyword argument 'sort'")
        return {
            "items": [
                {"note_id": "fallback-1", "display_title": keyword}
            ]
        }


class FakeInternalTypeErrorAfterSortFallbackClient:
    def __init__(self):
        self.calls = []

    async def search_note(self, *args, **kwargs):
        if args:
            self.calls.append("positional")
            return {
                "items": [
                    {"note_id": "masked-internal-error"}
                ]
            }

        if "sort" in kwargs:
            self.calls.append("sort")
            raise TypeError("search_note() got an unexpected keyword argument 'sort'")

        self.calls.append("keyword")
        raise TypeError("internal parser failed")


class XhsDiscoveryAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_adapter_uses_available_search_method(self):
        from xhs_discovery import search_keyword_notes

        rows = await search_keyword_notes(FakeSearchClient(), "英国留学", limit=5)
        self.assertEqual(rows[0]["note_id"], "n1")
        self.assertEqual(rows[0]["display_title"], "英国留学")

    async def test_search_adapter_passes_sort_object_to_keyword_method(self):
        from xhs_discovery import search_keyword_notes

        rows = await search_keyword_notes(FakeKeywordClient(), "美国申请", limit=5)
        self.assertEqual(rows[0]["note_id"], "n2")
        self.assertEqual(rows[0]["display_title"], "美国申请")

    async def test_search_adapter_does_not_retry_arbitrary_attribute_error(self):
        from xhs_discovery import search_keyword_notes

        client = FakeExplodingSearchClient()
        with self.assertRaisesRegex(AttributeError, "api exploded"):
            await search_keyword_notes(client, "澳洲申请", limit=5)

        self.assertEqual(client.calls, 1)

    async def test_search_adapter_does_not_retry_internal_attribute_error_mentioning_value(self):
        from xhs_discovery import search_keyword_notes

        messages = [
            "response has no attribute value",
            "sort parser has no attribute value",
        ]
        for message in messages:
            with self.subTest(message=message):
                client = FakeExplodingSearchClient(message)
                with self.assertRaisesRegex(AttributeError, message):
                    await search_keyword_notes(client, "澳洲申请", limit=5)

                self.assertEqual(client.calls, 1)

    async def test_search_adapter_does_not_retry_internal_type_error(self):
        from xhs_discovery import search_keyword_notes

        client = FakeTypeErrorSearchClient("internal parser failed")
        with self.assertRaisesRegex(TypeError, "internal parser failed"):
            await search_keyword_notes(client, "澳洲申请", limit=5)

        self.assertEqual(client.calls, 1)

    async def test_search_adapter_retries_signature_type_error_without_sort(self):
        from xhs_discovery import search_keyword_notes

        client = FakeSignatureMismatchSearchClient()
        rows = await search_keyword_notes(client, "澳洲申请", limit=5)

        self.assertEqual(rows[0]["note_id"], "fallback-1")
        self.assertEqual(client.calls, 2)

    async def test_search_adapter_preserves_internal_type_error_after_sort_fallback(self):
        from xhs_discovery import search_keyword_notes

        client = FakeInternalTypeErrorAfterSortFallbackClient()
        with self.assertRaisesRegex(TypeError, "internal parser failed"):
            await search_keyword_notes(client, "澳洲申请", limit=5)

        self.assertEqual(client.calls, ["sort", "keyword"])


class DiscoveryServiceTests(unittest.TestCase):
    def test_create_job_truncates_provided_queries_and_inserts_pending_job(self):
        sb = FakeSupabase()
        service = DiscoveryService(sb, max_queries=2)

        job = service.create_job(
            user_question="英国申请焦虑方向有什么爆款素材？",
            task_type="material",
            trigger_reason="user_requested",
            internal_answer_payload={"conclusion": "内部资料不足"},
            search_queries=["英国留学 焦虑", "英国申请 文书", "多余查询"],
            benchmark_account_ids=["account-1"],
            created_by_member_id="member-1",
        )

        self.assertEqual(job["search_queries"], ["英国留学 焦虑", "英国申请 文书"])
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["benchmark_account_ids"], ["account-1"])
        self.assertEqual(sb.tables[0].name, "external_discovery_jobs")
        self.assertEqual(sb.tables[0].insert_payload[0]["created_by_member_id"], "member-1")

    def test_create_job_preserves_explicit_empty_search_queries(self):
        sb = FakeSupabase()
        service = DiscoveryService(sb, max_queries=2)

        job = service.create_job(
            user_question="英国申请焦虑方向有什么爆款素材？",
            task_type="material",
            trigger_reason="user_requested",
            internal_answer_payload={"conclusion": "内部资料不足"},
            search_queries=[],
        )

        self.assertEqual(job["search_queries"], [])

    def test_get_job_with_candidates_orders_candidates_by_score_desc(self):
        sb = FakeSupabase({
            "external_discovery_jobs": {"id": "job-1", "status": "pending"},
            "external_discovery_candidates": [{"id": "candidate-1", "candidate_score": 0.8}],
        })
        service = DiscoveryService(sb)

        result = service.get_job_with_candidates("job-1")

        self.assertEqual(result["job"], {"id": "job-1", "status": "pending"})
        self.assertEqual(result["candidates"], [{"id": "candidate-1", "candidate_score": 0.8}])
        self.assertIn(("order", "candidate_score", True), sb.tables[1].calls)

    def test_get_job_with_candidates_raises_when_job_is_missing(self):
        sb = FakeSupabase({
            "external_discovery_jobs": None,
            "external_discovery_candidates": [],
        })
        service = DiscoveryService(sb)

        with self.assertRaises(discovery_service.DiscoveryNotFoundError) as ctx:
            service.get_job_with_candidates("missing-job")

        self.assertEqual(str(ctx.exception), "外部发现任务不存在")
        self.assertIn(("maybe_single",), sb.tables[0].calls)
        self.assertNotIn(("single",), sb.tables[0].calls)

    def test_mark_candidate_review_writes_status_reason_and_reviewed_at(self):
        sb = FakeSupabase()
        service = DiscoveryService(sb)

        candidate = service.mark_candidate_review("candidate-1", "rejected", "不相关")

        self.assertEqual(candidate["review_status"], "rejected")
        self.assertEqual(candidate["review_reason"], "不相关")
        self.assertIn("reviewed_at", candidate)
        self.assertIn(("eq", "id", "candidate-1"), sb.tables[0].calls)
        self.assertIn(("eq", "review_status", "pending"), sb.tables[0].calls)

    def test_mark_candidate_review_raises_when_no_pending_row_is_updated(self):
        sb = FakeSupabase()
        sb.update_responses["external_discovery_candidates"] = []
        service = DiscoveryService(sb)

        with self.assertRaises(discovery_service.DiscoveryNotFoundError) as ctx:
            service.mark_candidate_review("candidate-1", "ignored")

        self.assertEqual(str(ctx.exception), "候选素材不存在或已审核")

    def test_approve_candidate_inserts_viral_post_marks_candidate_and_indexes_knowledge(self):
        candidate = {
            "id": "candidate-1",
            "review_status": "pending",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
            "title": "英国申请焦虑",
            "caption": "真实申请故事",
            "cover_image": "https://example.com/cover.jpg",
            "images": ["https://example.com/cover.jpg"],
            "tags": ["英国留学", "申请焦虑"],
            "author_name": "学姐",
            "likes": 1200,
            "saves": 330,
            "comments": 45,
            "views": 9000,
            "ai_reason": "评论区需求明确",
        }
        viral_post = {
            "id": "viral-1",
            "created_at": "2026-05-09T00:00:00+00:00",
            **{key: value for key, value in candidate.items() if key != "id"},
        }
        approved_candidate = {
            **candidate,
            "review_status": "approved",
            "approved_viral_post_id": "viral-1",
        }
        sb = FakeSupabase({
            "external_discovery_candidates": candidate,
            "viral_posts": None,
            "knowledge_items": None,
        })
        sb.insert_responses["viral_posts"] = [viral_post]
        sb.update_responses["external_discovery_candidates"] = [approved_candidate]
        service = DiscoveryService(sb)

        result = service.approve_candidate("candidate-1")

        self.assertEqual(result["review_status"], "approved")
        self.assertEqual(result["approved_viral_post_id"], "viral-1")
        candidate_lookup = sb.tables[0]
        self.assertEqual(candidate_lookup.name, "external_discovery_candidates")
        self.assertIn(("eq", "id", "candidate-1"), candidate_lookup.calls)
        self.assertIn(("eq", "review_status", "pending"), candidate_lookup.calls)
        viral_insert = next(table for table in sb.tables if table.name == "viral_posts" and table.insert_payload)
        inserted = viral_insert.insert_payload[0]
        self.assertEqual(inserted["source_origin"], "ai_external_discovery")
        self.assertEqual(inserted["discovery_candidate_id"], "candidate-1")
        self.assertEqual(inserted["fetch_status"], "done")
        self.assertEqual(inserted["country"], None)
        self.assertIn("来源：AI 外部发现", inserted["note"])
        self.assertIn("评论区需求明确", inserted["note"])
        knowledge_upsert = sb.upserts[0]
        self.assertEqual(knowledge_upsert["table"], "knowledge_items")
        self.assertEqual(knowledge_upsert["on_conflict"], "source_type,source_key")
        self.assertEqual(knowledge_upsert["payload"]["source_type"], "viral_post")
        self.assertEqual(knowledge_upsert["payload"]["source_id"], "viral-1")
        self.assertEqual(knowledge_upsert["payload"]["embed_status"], "pending")

    def test_approve_candidate_updates_existing_viral_post_by_note_id_and_preserves_id(self):
        candidate = {
            "id": "candidate-1",
            "review_status": "pending",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
            "title": "新标题",
            "caption": "新正文",
            "tags": ["英国"],
        }
        existing_viral_post = {
            "id": "viral-existing",
            "url": "https://old.example.com",
            "xhs_note_id": "note-1",
            "title": "旧标题",
            "fetch_status": "done",
        }
        approved_candidate = {
            **candidate,
            "review_status": "approved",
            "approved_viral_post_id": "viral-existing",
        }
        sb = FakeSupabase({
            "external_discovery_candidates": candidate,
            "viral_posts": existing_viral_post,
            "knowledge_items": None,
        })
        sb.update_responses["viral_posts"] = [{**existing_viral_post, "title": "新标题"}]
        sb.update_response_sequences["external_discovery_candidates"] = [
            [{**candidate, "review_status": "approved"}],
            [approved_candidate],
        ]
        service = DiscoveryService(sb)

        result = service.approve_candidate("candidate-1")

        self.assertEqual(result["approved_viral_post_id"], "viral-existing")
        viral_update = next(table for table in sb.tables if table.name == "viral_posts" and table.update_payload)
        self.assertEqual(viral_update.update_payload["title"], "新标题")
        self.assertIn(("eq", "id", "viral-existing"), viral_update.calls)
        self.assertFalse(any(table.name == "viral_posts" and table.insert_payload for table in sb.tables))
        self.assertEqual(sb.upserts[0]["payload"]["source_id"], "viral-existing")

    def test_approve_candidate_falls_back_to_url_when_note_id_lookup_misses(self):
        candidate = {
            "id": "candidate-1",
            "review_status": "pending",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
            "title": "新标题",
            "caption": "新正文",
            "tags": ["英国"],
        }
        existing_viral_post = {
            "id": "viral-url-match",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "old-note-id",
            "title": "旧标题",
            "fetch_status": "done",
        }
        approved_candidate = {
            **candidate,
            "review_status": "approved",
            "approved_viral_post_id": "viral-url-match",
        }
        sb = FakeSupabase({
            "external_discovery_candidates": candidate,
            "knowledge_items": None,
        })
        sb.response_sequences["viral_posts"] = [None, existing_viral_post]
        sb.update_responses["viral_posts"] = [{**existing_viral_post, "title": "新标题"}]
        sb.update_response_sequences["external_discovery_candidates"] = [
            [{**candidate, "review_status": "approved"}],
            [approved_candidate],
        ]
        service = DiscoveryService(sb)

        result = service.approve_candidate("candidate-1")

        self.assertEqual(result["approved_viral_post_id"], "viral-url-match")
        viral_lookups = [table for table in sb.tables if table.name == "viral_posts" and table.update_payload is None]
        self.assertIn(("eq", "xhs_note_id", "note-1"), viral_lookups[0].calls)
        self.assertIn(("eq", "url", "https://www.xiaohongshu.com/explore/note-1"), viral_lookups[1].calls)
        self.assertIn(("order", "created_at", True), viral_lookups[1].calls)
        self.assertIn(("limit", 1), viral_lookups[1].calls)
        self.assertNotIn(("maybe_single",), viral_lookups[1].calls)
        viral_update = next(table for table in sb.tables if table.name == "viral_posts" and table.update_payload)
        self.assertIn(("eq", "id", "viral-url-match"), viral_update.calls)
        self.assertFalse(any(table.name == "viral_posts" and table.insert_payload for table in sb.tables))

    def test_approve_candidate_raises_when_candidate_is_missing_or_already_reviewed(self):
        for row in (None, {"id": "candidate-1", "review_status": "ignored"}):
            with self.subTest(row=row):
                sb = FakeSupabase({"external_discovery_candidates": row})
                sb.update_response_sequences["external_discovery_candidates"] = [[]]
                service = DiscoveryService(sb)

                with self.assertRaises(discovery_service.DiscoveryNotFoundError) as ctx:
                    service.approve_candidate("candidate-1")

                self.assertEqual(str(ctx.exception), "候选素材不存在或已审核")

    def test_approve_candidate_lost_claim_to_rejected_does_not_mutate_viral_or_knowledge(self):
        rejected_candidate = {
            "id": "candidate-1",
            "review_status": "rejected",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
        }
        sb = FakeSupabase({"external_discovery_candidates": rejected_candidate})
        sb.update_response_sequences["external_discovery_candidates"] = [[]]
        service = DiscoveryService(sb)

        with self.assertRaises(discovery_service.DiscoveryNotFoundError) as ctx:
            service.approve_candidate("candidate-1")

        self.assertEqual(str(ctx.exception), "候选素材不存在或已审核")
        self.assertEqual(sb.tables[0].name, "external_discovery_candidates")
        self.assertIsNotNone(sb.tables[0].update_payload)
        self.assertEqual(sb.tables[0].update_payload["review_status"], "approved")
        self.assertIn(("eq", "review_status", "pending"), sb.tables[0].calls)
        self.assertFalse(any(table.name == "viral_posts" and (table.insert_payload or table.update_payload) for table in sb.tables))
        self.assertEqual(sb.upserts, [])

    def test_approve_candidate_repairs_already_approved_candidate_with_link_by_indexing(self):
        approved_candidate = {
            "id": "candidate-1",
            "review_status": "approved",
            "approved_viral_post_id": "viral-1",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
        }
        linked_viral_post = {
            "id": "viral-1",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
            "title": "已入库标题",
            "caption": "已入库正文",
            "fetch_status": "done",
            "created_at": "2026-05-09T00:00:00+00:00",
        }
        sb = FakeSupabase({"knowledge_items": None})
        sb.update_response_sequences["external_discovery_candidates"] = [[]]
        sb.response_sequences["external_discovery_candidates"] = [approved_candidate]
        sb.response_sequences["viral_posts"] = [[linked_viral_post]]
        service = DiscoveryService(sb)

        result = service.approve_candidate("candidate-1")

        self.assertEqual(result["review_status"], "approved")
        self.assertEqual(result["approved_viral_post_id"], "viral-1")
        self.assertFalse(any(table.name == "viral_posts" and (table.insert_payload or table.update_payload) for table in sb.tables))
        self.assertEqual(sb.upserts[0]["table"], "knowledge_items")
        self.assertEqual(sb.upserts[0]["payload"]["source_type"], "viral_post")
        self.assertEqual(sb.upserts[0]["payload"]["source_id"], "viral-1")

    def test_find_existing_viral_post_uses_order_and_limit_for_duplicate_note_lookup(self):
        candidate = {
            "id": "candidate-1",
            "review_status": "pending",
            "url": "https://www.xiaohongshu.com/explore/note-1",
            "xhs_note_id": "note-1",
            "title": "新标题",
            "caption": "新正文",
            "tags": ["英国"],
        }
        duplicate_rows = [
            {
                "id": "viral-newer",
                "url": "https://new.example.com",
                "xhs_note_id": "note-1",
                "title": "较新重复",
                "fetch_status": "done",
                "created_at": "2026-05-09T00:00:00+00:00",
            },
            {
                "id": "viral-older",
                "url": "https://old.example.com",
                "xhs_note_id": "note-1",
                "title": "较旧重复",
                "fetch_status": "done",
                "created_at": "2026-05-08T00:00:00+00:00",
            },
        ]
        approved_candidate = {
            **candidate,
            "review_status": "approved",
            "approved_viral_post_id": "viral-newer",
        }
        sb = FakeSupabase({"knowledge_items": None})
        sb.update_response_sequences["external_discovery_candidates"] = [[{**candidate, "review_status": "approved"}], [approved_candidate]]
        sb.response_sequences["viral_posts"] = [duplicate_rows]
        sb.update_responses["viral_posts"] = [{**duplicate_rows[0], "title": "新标题"}]
        service = DiscoveryService(sb)

        result = service.approve_candidate("candidate-1")

        self.assertEqual(result["approved_viral_post_id"], "viral-newer")
        viral_lookup = next(table for table in sb.tables if table.name == "viral_posts" and table.update_payload is None)
        self.assertIn(("order", "created_at", True), viral_lookup.calls)
        self.assertIn(("limit", 1), viral_lookup.calls)
        self.assertNotIn(("maybe_single",), viral_lookup.calls)
        viral_update = next(table for table in sb.tables if table.name == "viral_posts" and table.update_payload)
        self.assertIn(("eq", "id", "viral-newer"), viral_update.calls)
        self.assertFalse(any(table.name == "viral_posts" and table.insert_payload for table in sb.tables))

    def test_create_discovery_job_req_validates_enum_fields(self):
        with self.assertRaises(ValueError):
            CreateDiscoveryJobReq(
                user_question="帮我找素材",
                task_type="invalid",
                trigger_reason="user_requested",
            )
        with self.assertRaises(ValueError):
            CreateDiscoveryJobReq(
                user_question="帮我找素材",
                task_type="mixed",
                trigger_reason="invalid",
            )

    def test_review_candidate_req_validates_optional_reason_enum(self):
        self.assertIsNone(ReviewCandidateReq().reason)
        self.assertEqual(ReviewCandidateReq(reason="低质量").reason, "低质量")
        with self.assertRaises(ValueError):
            ReviewCandidateReq(reason="随便写的原因")


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.original_discovery_service = ai_api.discovery_service

    def tearDown(self):
        ai_api.discovery_service = self.original_discovery_service

    def test_get_discovery_job_translates_missing_job_to_404(self):
        class MissingJobService:
            def get_job_with_candidates(self, job_id):
                raise discovery_service.DiscoveryNotFoundError("外部发现任务不存在")

        ai_api.discovery_service = MissingJobService()

        with self.assertRaises(ai_api.HTTPException) as ctx:
            asyncio.run(ai_api.get_discovery_job("missing-job"))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "外部发现任务不存在")

    def test_ignore_discovery_candidate_translates_finalized_candidate_to_404(self):
        class FinalizedCandidateService:
            def mark_candidate_review(self, candidate_id, review_status, review_reason=None):
                raise discovery_service.DiscoveryNotFoundError("候选素材不存在或已审核")

        ai_api.discovery_service = FinalizedCandidateService()

        with self.assertRaises(ai_api.HTTPException) as ctx:
            asyncio.run(ai_api.ignore_discovery_candidate("candidate-1"))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "候选素材不存在或已审核")

    def test_reject_discovery_candidate_translates_finalized_candidate_to_404(self):
        class FinalizedCandidateService:
            def mark_candidate_review(self, candidate_id, review_status, review_reason=None):
                raise discovery_service.DiscoveryNotFoundError("候选素材不存在或已审核")

        ai_api.discovery_service = FinalizedCandidateService()

        with self.assertRaises(ai_api.HTTPException) as ctx:
            asyncio.run(ai_api.reject_discovery_candidate("candidate-1", ReviewCandidateReq(reason="不相关")))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "候选素材不存在或已审核")

    def test_approve_discovery_candidate_translates_finalized_candidate_to_404(self):
        class FinalizedCandidateService:
            def approve_candidate(self, candidate_id):
                raise discovery_service.DiscoveryNotFoundError("候选素材不存在或已审核")

        ai_api.discovery_service = FinalizedCandidateService()

        with self.assertRaises(ai_api.HTTPException) as ctx:
            asyncio.run(ai_api.approve_discovery_candidate("candidate-1"))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "候选素材不存在或已审核")


class ExternalSupplementTests(unittest.TestCase):
    def test_external_supplement_fallback_uses_top_three_allowed_candidates(self):
        service = research_service.ResearchService(None, None)
        service.openai = None
        candidates = [
            {"id": "c1", "title": "英国申请焦虑", "caption": "焦虑开头"},
            {"id": "c2", "title": "文书避坑", "caption": "避坑清单"},
            {"id": "c3", "title": "选校经验", "caption": "真实案例"},
            {"id": "c4", "title": "多余素材", "caption": "不会进入前三"},
        ]

        answer = asyncio.run(service.generate_external_supplement(
            job_id="job-1",
            question="英国申请焦虑方向有什么爆款素材？",
            candidates=candidates,
        ))

        self.assertEqual(answer.job_id, "job-1")
        self.assertEqual(answer.warning, "以下内容来自待审核外部素材，尚未进入团队知识库。")
        self.assertEqual(answer.candidate_references, ["c1", "c2", "c3"])
        self.assertEqual(len(answer.recommendations), 3)
        self.assertEqual(
            [candidate_id for rec in answer.recommendations for candidate_id in rec.candidate_ids],
            ["c1", "c2", "c3"],
        )

    def test_external_supplement_returns_empty_answer_without_candidates(self):
        service = research_service.ResearchService(None, None)
        service.openai = None

        answer = asyncio.run(service.generate_external_supplement(
            job_id="job-empty",
            question="找素材",
            candidates=[],
        ))

        self.assertEqual(answer.conclusion, "本次外部发现没有找到可用候选素材。")
        self.assertEqual(answer.recommendations, [])
        self.assertEqual(answer.candidate_references, [])


class ResearchReferenceTests(unittest.TestCase):
    def test_resolve_llm_settings_prefers_gemini_provider(self):
        settings = research_service.resolve_llm_settings(
            SimpleNamespace(
                LLM_PROVIDER="gemini",
                GEMINI_API_KEY="gemini-key",
                GEMINI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
                GEMINI_TEXT_MODEL="gemini-3-pro-preview",
                GEMINI_VISION_MODEL="gemini-3-pro-preview",
                OPENAI_API_KEY="openai-key",
            ),
            env={},
        )

        self.assertEqual(settings.provider, "gemini")
        self.assertEqual(settings.api_key, "gemini-key")
        self.assertEqual(settings.base_url, "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.assertEqual(settings.text_model, "gemini-3-pro-preview")
        self.assertEqual(settings.vision_model, "gemini-3-pro-preview")

    def test_resolve_llm_settings_uses_env_when_config_secret_is_blank(self):
        settings = research_service.resolve_llm_settings(
            SimpleNamespace(
                LLM_PROVIDER="gemini",
                GEMINI_API_KEY="",
                GEMINI_TEXT_MODEL="",
                GEMINI_VISION_MODEL="",
            ),
            env={"GEMINI_API_KEY": "env-gemini-key"},
        )

        self.assertEqual(settings.provider, "gemini")
        self.assertEqual(settings.api_key, "env-gemini-key")
        self.assertEqual(settings.text_model, "gemini-3-pro-preview")

    def test_generate_answer_uses_gemini_chat_completions(self):
        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                payload = {
                    "conclusion": "Gemini 已整理内部素材。",
                    "recommendations": [{"text": "参考春日标题结构。", "source_ids": ["row-1"]}],
                    "material_references": ["row-1"],
                    "team_history_references": [],
                    "image_analysis": None,
                    "general_advice": [],
                }
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
                        )
                    ]
                )

        completions = FakeCompletions()
        service = research_service.ResearchService(None, None)
        service.openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        service.llm_provider = "gemini"
        service.text_model = "gemini-3-pro-preview"

        answer = asyncio.run(service.generate_answer(
            question="英国春天标题素材",
            task_type="material",
            rows=[{
                "id": "row-1",
                "source_type": "viral_post",
                "title": "英国春天标题",
                "content": "春天、野餐、留学生周末。",
                "likes_count": 100,
                "saves_count": 50,
            }],
            sparse=False,
            image_analysis=None,
        ))

        self.assertEqual(answer["conclusion"], "Gemini 已整理内部素材。")
        self.assertEqual(answer["material_references"], ["row-1"])
        self.assertEqual(completions.calls[0]["model"], "gemini-3-pro-preview")
        self.assertEqual(completions.calls[0]["response_format"]["type"], "json_schema")
        self.assertEqual(completions.calls[0]["messages"][0]["role"], "system")
        self.assertIn("allowed_sources", completions.calls[0]["messages"][1]["content"])

    def test_fallback_answer_only_references_top_recommendations(self):
        service = research_service.ResearchService(None, None)
        rows = [
            {"id": f"row-{index}", "source_type": "viral_post", "title": f"素材 {index}"}
            for index in range(5)
        ]

        answer = service.generate_fallback_answer(
            question="英国春天标题素材",
            task_type="material",
            rows=rows,
            sparse=False,
            image_analysis=None,
        )

        self.assertEqual(answer["material_references"], ["row-0", "row-1", "row-2"])

    def test_fallback_answer_prefers_topic_evidence_over_broad_country_matches(self):
        service = research_service.ResearchService(None, None)
        rows = [
            {
                "id": "row-0",
                "source_type": "viral_post",
                "title": "2025还敢来英国留学！叫你狠人",
                "content": "关于英国留学，滤镜早该碎了。",
            },
            {
                "id": "row-1",
                "source_type": "viral_post",
                "title": "🇬🇧散步伦敦｜Spring in Richmond",
                "content": "社区网球场边的樱花开了，在公园里分享野餐。",
            },
            {
                "id": "row-2",
                "source_type": "viral_post",
                "title": "🇬🇧 用live打开伦敦的春天",
                "content": "用live感受伦敦春日鲜活的生命力，看小狗在花瓣堆里打滚。",
            },
            {
                "id": "row-3",
                "source_type": "viral_post",
                "title": "考研后逆袭英国名校？当然来得及",
                "content": "考研出分才申英国也可以准备。",
            },
        ]

        answer = service.generate_fallback_answer(
            question="帮我找一下有关于英国春天的标题素材",
            task_type="material",
            rows=rows,
            sparse=False,
            image_analysis=None,
        )

        self.assertEqual(answer["material_references"], ["row-2", "row-1"])
        self.assertEqual(
            [item["source_ids"][0] for item in answer["recommendations"]],
            ["row-2", "row-1"],
        )

    def test_research_cited_sources_follow_recommendation_ids_not_all_material_refs(self):
        rows = [
            {
                "id": f"row-{index}",
                "source_type": "viral_post",
                "source_key": f"row-{index}",
                "title": f"素材 {index}",
                "content": f"英国春天内容 {index}",
                "similarity": 0.9,
            }
            for index in range(5)
        ]

        class NarrowReferenceService(research_service.ResearchService):
            async def retrieve(self, query, task_type):
                return rows

            async def generate_answer(self, question, task_type, rows, sparse, image_analysis):
                return {
                    "conclusion": "只引用推荐中真正用到的素材。",
                    "recommendations": [
                        {"text": "参考前两条春天素材。", "source_ids": ["row-0", "row-1"]},
                    ],
                    "material_references": [f"row-{index}" for index in range(5)],
                    "team_history_references": [],
                    "image_analysis": None,
                    "general_advice": [],
                }

        service = NarrowReferenceService(None, None)

        answer = asyncio.run(service.research(ResearchRequest(question="英国春天标题素材")))

        self.assertEqual(answer.material_references, ["row-0", "row-1"])
        self.assertEqual([source.id for source in answer.cited_sources], ["row-0", "row-1"])
        self.assertEqual([source.id for source in answer.related_sources], ["row-2", "row-3", "row-4"])

    def test_related_sources_exclude_broad_non_evidence_matches(self):
        rows = [
            {
                "id": "cited-spring",
                "source_type": "viral_post",
                "source_key": "cited-spring",
                "title": "伦敦春天散步",
                "content": "春日和樱花路线。",
                "similarity": 0.9,
            },
            {
                "id": "broad-uk",
                "source_type": "viral_post",
                "source_key": "broad-uk",
                "title": "英国留学申请攻略",
                "content": "只有英国申请信息，没有季节素材。",
                "similarity": 0.88,
            },
            {
                "id": "related-spring",
                "source_type": "viral_post",
                "source_key": "related-spring",
                "title": "Spring in Richmond",
                "content": "樱花和公园野餐。",
                "similarity": 0.86,
            },
            {
                "id": "broad-manchester",
                "source_type": "benchmark_post",
                "source_key": "broad-manchester",
                "title": "拿下曼彻斯特大学",
                "content": "英国学校 offer 复盘。",
                "similarity": 0.84,
            },
        ]

        class NarrowRelatedService(research_service.ResearchService):
            async def retrieve(self, query, task_type):
                return rows

            async def generate_answer(self, question, task_type, rows, sparse, image_analysis):
                return {
                    "conclusion": "引用春天素材。",
                    "recommendations": [
                        {"text": "先参考伦敦春天散步。", "source_ids": ["cited-spring"]},
                    ],
                    "material_references": ["cited-spring"],
                    "team_history_references": [],
                    "image_analysis": None,
                    "general_advice": [],
                }

        service = NarrowRelatedService(None, None)

        answer = asyncio.run(service.research(ResearchRequest(question="帮我找一下英国春天标题素材")))

        self.assertEqual([source.id for source in answer.cited_sources], ["cited-spring"])
        self.assertEqual([source.id for source in answer.related_sources], ["related-spring"])

    def test_source_shape_normalizes_xhs_links(self):
        service = research_service.ResearchService(None, None)

        source = service._source_shape({
            "id": "row-1",
            "source_type": "viral_post",
            "source_id": "abc123",
            "source_key": "row-1",
            "title": "春天素材",
            "source_url": "https://www.xiaohongshu.com/explore/abc123?xsec_token=stale&xsec_source=pc_search&source=unknown#comments",
        })

        self.assertEqual(source["source_url"], "https://www.xiaohongshu.com/explore/abc123")

    def test_keyword_candidates_filters_prompt_scaffold_tokens(self):
        sb = FakeSupabase({"knowledge_items": []})
        service = research_service.ResearchService(sb, None)

        service.keyword_candidates(
            "帮我找一下有关于英国春天的标题素材",
            source_types=["viral_post"],
        )

        or_call = [
            call for table in sb.tables
            for call in table.calls
            if call[0] == "or_"
        ][0]
        clauses = or_call[1]

        self.assertIn("英国", clauses)
        self.assertIn("春天", clauses)
        self.assertNotIn("帮我", clauses)
        self.assertNotIn("标题", clauses)
        self.assertNotIn("素材", clauses)

    def test_retrieve_passes_min_similarity_and_filters_rpc_tail(self):
        async def fake_embed(texts, input_type="query"):
            return [[0.1, 0.2, 0.3]]

        sb = FakeSupabase({
            "match_knowledge_items": [
                {
                    "id": "strong",
                    "source_type": "viral_post",
                    "source_key": "strong",
                    "title": "英国春天素材",
                    "content": "伦敦春日樱花",
                    "similarity": 0.80,
                },
                {
                    "id": "weak-tail",
                    "source_type": "viral_post",
                    "source_key": "weak-tail",
                    "title": "英国申请",
                    "content": "泛英国申请信息",
                    "similarity": 0.20,
                },
            ],
            "knowledge_items": [],
        })
        service = research_service.ResearchService(sb, fake_embed)
        intent_payload = parse_query_fallback("帮我找一下有关于英国春天的标题素材")

        rows = asyncio.run(service.retrieve(
            "帮我找一下有关于英国春天的标题素材",
            "material",
            intent_payload=intent_payload,
        ))

        self.assertEqual([row["id"] for row in rows], ["strong"])
        self.assertEqual(sb.rpc_calls[0][0], "match_knowledge_items")
        self.assertIn("min_similarity", sb.rpc_calls[0][1])
        self.assertEqual(sb.rpc_calls[0][1]["country_filter"], "英国")

    def test_retrieve_falls_back_when_deployed_rpc_has_old_signature(self):
        async def fake_embed(texts, input_type="query"):
            return [[0.1, 0.2, 0.3]]

        sb = FakeSupabase({
            "match_knowledge_items": [
                {
                    "id": "strong",
                    "source_type": "viral_post",
                    "source_key": "strong",
                    "title": "英国春天素材",
                    "content": "伦敦春日樱花",
                    "similarity": 0.80,
                },
            ],
            "knowledge_items": [],
        })
        sb.rpc_errors.append(Exception("function match_knowledge_items(min_similarity) does not exist"))
        service = research_service.ResearchService(sb, fake_embed)

        rows = asyncio.run(service.retrieve(
            "英国春天标题素材",
            "material",
            intent_payload=parse_query_fallback("英国春天标题素材"),
        ))

        self.assertEqual([row["id"] for row in rows], ["strong"])
        self.assertEqual(len(sb.rpc_calls), 2)
        self.assertIn("min_similarity", sb.rpc_calls[0][1])
        self.assertNotIn("min_similarity", sb.rpc_calls[1][1])

    def test_research_empty_evidence_does_not_call_llm(self):
        class EmptyEvidenceService(research_service.ResearchService):
            async def retrieve(self, query, task_type):
                return []

            async def generate_answer(self, question, task_type, rows, sparse, image_analysis):
                raise AssertionError("LLM should not be called without evidence")

        sb = FakeSupabase()
        service = EmptyEvidenceService(sb, None)

        answer = asyncio.run(service.research(ResearchRequest(question="英国春天标题素材")))

        self.assertEqual(answer.conclusion, "知识库中没有匹配内容。")
        self.assertEqual(answer.evidence_quality, "empty")
        self.assertTrue(answer.sparse)
        self.assertEqual(answer.cited_sources, [])

    def test_research_only_allows_selected_evidence_as_citations(self):
        rows = [
            {
                "id": "selected",
                "source_type": "viral_post",
                "source_key": "selected",
                "title": "伦敦春天素材",
                "content": "春日樱花和公园野餐。",
                "similarity": 0.82,
            },
            {
                "id": "filtered-tail",
                "source_type": "viral_post",
                "source_key": "filtered-tail",
                "title": "英国申请泛内容",
                "content": "没有春天细节。",
                "similarity": 0.20,
            },
        ]

        class SelectedEvidenceService(research_service.ResearchService):
            def __init__(self):
                super().__init__(FakeSupabase(), None)
                self.seen_row_ids = []

            async def retrieve(self, query, task_type):
                return rows

            async def generate_answer(self, question, task_type, rows, sparse, image_analysis):
                self.seen_row_ids = [row["id"] for row in rows]
                return {
                    "conclusion": "只允许引用筛选后的素材。",
                    "recommendations": [
                        {"text": "参考春天素材。", "source_ids": ["selected", "filtered-tail"]},
                    ],
                    "material_references": ["selected", "filtered-tail"],
                    "team_history_references": [],
                    "image_analysis": None,
                    "general_advice": [],
                }

        service = SelectedEvidenceService()

        answer = asyncio.run(service.research(ResearchRequest(question="英国春天标题素材")))

        self.assertEqual(service.seen_row_ids, ["selected"])
        self.assertEqual(answer.material_references, ["selected"])
        self.assertEqual([source.id for source in answer.cited_sources], ["selected"])
        self.assertEqual(answer.evidence_quality, "weak")

    def test_research_writes_trace_payload_best_effort(self):
        rows = [
            {
                "id": "row-1",
                "source_type": "viral_post",
                "source_key": "row-1",
                "title": "伦敦春天素材",
                "content": "春日樱花和公园野餐。",
                "similarity": 0.82,
            },
            {
                "id": "row-2",
                "source_type": "viral_post",
                "source_key": "row-2",
                "title": "英国春日标题",
                "content": "花瓣和live图。",
                "similarity": 0.78,
            },
            {
                "id": "row-3",
                "source_type": "topic",
                "source_key": "row-3",
                "title": "春天选题",
                "content": "春天情绪选题。",
                "similarity": 0.72,
            },
        ]

        class TraceService(research_service.ResearchService):
            async def retrieve(self, query, task_type):
                return rows

            async def generate_answer(self, question, task_type, rows, sparse, image_analysis):
                return {
                    "conclusion": "引用内部素材回答。",
                    "recommendations": [
                        {"text": "参考伦敦春天素材。", "source_ids": ["row-1"]},
                    ],
                    "material_references": ["row-1"],
                    "team_history_references": [],
                    "image_analysis": None,
                    "general_advice": [],
                }

        sb = FakeSupabase()
        service = TraceService(sb, None)

        answer = asyncio.run(service.research(ResearchRequest(question="英国春天标题素材")))

        self.assertIsNotNone(answer.trace_id)
        trace_table = next(table for table in sb.tables if table.name == "research_traces")
        self.assertEqual(trace_table.insert_payload["id"], answer.trace_id)
        self.assertEqual(trace_table.insert_payload["evidence_quality"], "strong")
        self.assertEqual(trace_table.insert_payload["selected_evidence_ids"], ["row-1", "row-2", "row-3"])
        self.assertEqual(answer.selected_source_ids, ["row-1", "row-2", "row-3"])


class DiscoveryHelperTests(unittest.TestCase):
    def test_research_answer_omits_inactive_discovery_trigger_mode_by_default(self):
        answer = ResearchAnswer(
            question="英国申请焦虑方向有什么爆款素材？",
            task_type="material",
            conclusion="内部资料足够回答。",
        )

        self.assertIsNone(model_to_dict(answer)["discovery_trigger_mode"])

    def test_research_answer_serializes_explicit_discovery_trigger_mode(self):
        answer = ResearchAnswer(
            question="英国申请焦虑方向有什么爆款素材？",
            task_type="material",
            conclusion="内部资料不足，需要外部发现。",
            discovery_trigger_mode="ask_first",
        )

        self.assertEqual(model_to_dict(answer)["discovery_trigger_mode"], "ask_first")

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

    def test_derive_search_queries_returns_empty_when_max_queries_is_zero(self):
        self.assertEqual(
            derive_search_queries(
                question="英国申请焦虑方向有什么爆款素材？",
                max_queries=0,
            ),
            [],
        )

    def test_query_derivation_uses_image_keywords(self):
        queries = derive_search_queries(
            question="帮我找相似参考",
            image_keywords=["英国", "申请", "焦虑"],
            weak_titles=[],
            max_queries=3,
        )
        self.assertTrue(any("英国" in query for query in queries))
        self.assertTrue(any("申请" in query for query in queries))

    def test_config_value_preserves_legacy_values_when_discovery_fields_missing(self):
        original_config = research_service.app_config
        research_service.app_config = SimpleNamespace(
            OPENAI_API_KEY="legacy-key",
            AI_RESEARCH_MIN_RESULTS=7,
        )
        try:
            self.assertEqual(research_service._config_value("OPENAI_API_KEY", ""), "legacy-key")
            self.assertEqual(research_service._config_value("AI_RESEARCH_MIN_RESULTS", 3), 7)
            self.assertFalse(research_service._config_value("EXTERNAL_DISCOVERY_ENABLED", False))
        finally:
            research_service.app_config = original_config

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

    def test_score_candidate_defaults_invalid_relevance_score_safely(self):
        row = {"likes": 1000, "saves": 300, "comments": 50, "views": 10000}
        self.assertIsInstance(score_candidate(row, relevance_score=None), float)
        self.assertIsInstance(score_candidate(row, relevance_score="not-a-number"), float)

    def test_score_candidate_defaults_non_finite_relevance_score_safely(self):
        row = {"likes": 1000, "saves": 300, "comments": 50, "views": 10000}
        self.assertTrue(math.isfinite(score_candidate(row, relevance_score=float("nan"))))
        self.assertTrue(math.isfinite(score_candidate(row, relevance_score=float("inf"))))
        self.assertTrue(math.isfinite(score_candidate(row, relevance_score=float("-inf"))))

    def test_candidate_dedupe_prefers_note_id(self):
        row = {"xhs_note_id": "note-1", "url": "https://example.com/a"}
        self.assertEqual(candidate_dedupe_key(row), "note:note-1")

    def test_candidate_dedupe_falls_back_to_url(self):
        row = {"xhs_note_id": "", "url": "https://example.com/a?x=1"}
        self.assertEqual(candidate_dedupe_key(row), "url:https://example.com/a?x=1")

    def test_candidate_dedupe_strips_tracking_query_and_fragment_noise(self):
        noisy = {
            "xhs_note_id": "",
            "url": "https://example.com/a?xsec_token=1&utm_source=x#frag",
        }
        clean = {"xhs_note_id": "", "url": "https://example.com/a"}
        self.assertEqual(candidate_dedupe_key(noisy), candidate_dedupe_key(clean))

    def test_candidate_dedupe_preserves_generic_type_and_from_query_params(self):
        row = {
            "xhs_note_id": "",
            "url": "https://example.com/a?type=note&from=dashboard&xsec_token=1",
        }
        self.assertEqual(
            candidate_dedupe_key(row),
            "url:https://example.com/a?type=note&from=dashboard",
        )

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

    def test_validate_external_candidate_ids_handles_nullable_and_string_fields(self):
        payload = {
            "recommendations": [
                {"text": "空候选", "candidate_ids": None},
                {"text": "字符串候选", "candidate_ids": "c1"},
            ],
            "general_advice": [],
            "candidate_references": "c1",
        }
        cleaned = validate_external_candidate_ids(payload, allowed_candidate_ids={"c1"})
        self.assertEqual(cleaned["recommendations"], [{"text": "字符串候选", "candidate_ids": ["c1"]}])
        self.assertEqual(cleaned["general_advice"][0]["text"], "空候选")
        self.assertEqual(cleaned["candidate_references"], ["c1"])

    def test_validate_external_candidate_ids_converts_nullable_references_to_empty_list(self):
        payload = {
            "recommendations": [],
            "general_advice": [],
            "candidate_references": None,
        }
        cleaned = validate_external_candidate_ids(payload, allowed_candidate_ids={"c1"})
        self.assertEqual(cleaned["candidate_references"], [])

    def test_validate_external_candidate_ids_treats_mapping_values_as_malformed(self):
        payload = {
            "recommendations": [
                {"text": "字典候选", "candidate_ids": {"id": "c1"}},
            ],
            "general_advice": [],
            "candidate_references": {"id": "c1"},
        }
        cleaned = validate_external_candidate_ids(payload, allowed_candidate_ids={"id", "c1"})
        self.assertEqual(cleaned["recommendations"], [])
        self.assertEqual(cleaned["candidate_references"], [])
        self.assertEqual(cleaned["general_advice"][0]["text"], "字典候选")


if __name__ == "__main__":
    unittest.main()
