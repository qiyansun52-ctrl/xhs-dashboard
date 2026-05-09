import asyncio
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
from research_models import ResearchAnswer
from research_service import model_to_dict


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

    def execute(self):
        self.calls.append(("execute",))
        if self.insert_payload is not None:
            return FakeResult(self.insert_payload)
        if self.update_payload is not None:
            if self.name in self.client.update_responses:
                return FakeResult(self.client.update_responses[self.name])
            return FakeResult([self.update_payload])
        return FakeResult(self.client.responses.get(self.name, []))


class FakeSupabase:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.update_responses = {}
        self.tables = []

    def table(self, name):
        table = FakeTable(name, self)
        self.tables.append(table)
        return table


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
