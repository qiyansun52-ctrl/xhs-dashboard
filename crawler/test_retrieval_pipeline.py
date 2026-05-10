import unittest

from retrieval_pipeline import (
    EVIDENCE_TOKEN_SYNONYMS,
    IntentPayload,
    classify_sparse,
    filter_candidates,
    parse_query_fallback,
    profile_for_intent,
    select_evidence,
)


class QueryUnderstandingTests(unittest.TestCase):
    def test_parse_material_country_and_topic(self):
        payload = parse_query_fallback("帮我找一下有关于英国春天的标题素材")

        self.assertEqual(payload.intent, "find_material")
        self.assertEqual(payload.filters.country, "英国")
        self.assertIn("春天", payload.topic_tokens)
        self.assertIn("春天", payload.evidence_tokens)
        self.assertIn("spring", payload.evidence_tokens)
        self.assertIn("英国", payload.broad_tokens)
        self.assertIn("标题", payload.scaffold_tokens)

    def test_parse_team_history(self):
        payload = parse_query_fallback("我们之前写过哪些英国申请内容")

        self.assertEqual(payload.intent, "recall_team_history")
        self.assertIn("英国", payload.domain_entities)
        self.assertIn("申请", payload.evidence_tokens)

    def test_parse_risk_review(self):
        payload = parse_query_fallback("帮我检查这篇文案有没有违禁词和广告感")

        self.assertEqual(payload.intent, "evaluate")
        self.assertIn("违禁词", payload.topic_tokens)

    def test_profile_for_material_has_thresholds_and_budget(self):
        profile = profile_for_intent("find_material")

        self.assertEqual(profile.name, "find_material")
        self.assertGreaterEqual(profile.absolute_floor, 0.3)
        self.assertEqual(profile.evidence_total, 7)
        self.assertEqual(profile.evidence_budget["viral_post"], 3)

    def test_season_synonyms_are_available(self):
        self.assertEqual(
            EVIDENCE_TOKEN_SYNONYMS["春天"],
            ("春天", "春日", "春季", "spring", "樱花", "花瓣"),
        )


class CandidateFilteringTests(unittest.TestCase):
    def test_filter_candidates_applies_absolute_and_relative_thresholds(self):
        profile = profile_for_intent("find_material")
        profile.absolute_floor = 0.35
        profile.relative_floor_ratio = 0.7
        rows = [
            {"id": "top", "source_type": "viral_post", "similarity": 0.80},
            {"id": "relative-tail", "source_type": "viral_post", "similarity": 0.50},
            {"id": "kept", "source_type": "topic", "similarity": 0.58},
            {"id": "absolute-tail", "source_type": "title", "similarity": 0.20},
        ]

        result = filter_candidates([rows], profile)

        self.assertEqual([row["id"] for row in result.rows], ["top", "kept"])
        self.assertEqual(result.dropped_counts["below_relative"], 1)
        self.assertEqual(result.dropped_counts["below_absolute"], 1)
        self.assertAlmostEqual(result.top_similarity, 0.80)
        self.assertGreater(result.candidate_count, result.filtered_count)

    def test_select_evidence_respects_source_budgets_and_total(self):
        profile = profile_for_intent("find_material")
        rows = [
            {"id": f"v{index}", "source_type": "viral_post", "similarity": 0.9 - index * 0.01}
            for index in range(5)
        ] + [
            {"id": f"b{index}", "source_type": "benchmark_post", "similarity": 0.8 - index * 0.01}
            for index in range(4)
        ] + [
            {"id": "topic", "source_type": "topic", "similarity": 0.7},
            {"id": "title", "source_type": "title", "similarity": 0.69},
        ]

        selected = select_evidence(rows, profile)

        self.assertEqual(len(selected.rows), 7)
        self.assertEqual(
            [row["id"] for row in selected.rows],
            ["v0", "v1", "v2", "b0", "b1", "topic", "title"],
        )
        self.assertIn("v3", selected.overflow_ids)

    def test_classify_sparse_empty_weak_and_strong(self):
        profile = profile_for_intent("find_material")

        self.assertEqual(classify_sparse([], profile), "empty")
        self.assertEqual(
            classify_sparse(
                [
                    {"id": "one", "similarity": 0.50},
                    {"id": "two", "similarity": 0.42},
                ],
                profile,
            ),
            "weak",
        )
        self.assertEqual(
            classify_sparse(
                [
                    {"id": "one", "similarity": 0.70},
                    {"id": "two", "similarity": 0.61},
                    {"id": "three", "similarity": 0.50},
                ],
                profile,
            ),
            "strong",
        )


class DataclassContractTests(unittest.TestCase):
    def test_intent_payload_defaults_are_safe_lists(self):
        first = IntentPayload(raw_question="a", intent="general_qa")
        second = IntentPayload(raw_question="b", intent="general_qa")

        first.topic_tokens.append("英国")

        self.assertEqual(second.topic_tokens, [])


if __name__ == "__main__":
    unittest.main()
