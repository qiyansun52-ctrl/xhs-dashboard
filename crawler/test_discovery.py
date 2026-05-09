import math
import unittest
from types import SimpleNamespace

from discovery import (
    build_candidate_url,
    candidate_dedupe_key,
    derive_search_queries,
    normalize_question,
    score_candidate,
    validate_external_candidate_ids,
)
import research_service


class DiscoveryHelperTests(unittest.TestCase):
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
