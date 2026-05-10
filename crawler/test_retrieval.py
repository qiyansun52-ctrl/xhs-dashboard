import unittest

from retrieval import (
    detect_task_type,
    is_sparse_result,
    rrf_merge,
    tokenize_query,
    validate_citations,
)


class RetrievalTests(unittest.TestCase):
    def test_rrf_merge_promotes_items_seen_in_both_lists(self):
        semantic = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        keyword = [{"id": "b"}, {"id": "d"}, {"id": "a"}]

        merged = rrf_merge([semantic, keyword], k=60)

        self.assertEqual(merged[0]["id"], "b")
        self.assertEqual({row["id"] for row in merged[:4]}, {"a", "b", "c", "d"})
        self.assertGreater(merged[0]["rrf_score"], merged[-1]["rrf_score"])

    def test_detect_task_type_prefers_experience_for_history_words(self):
        self.assertEqual(detect_task_type("我们过去写过哪些文书相关内容"), "experience")
        self.assertEqual(detect_task_type("帮我找英国申请焦虑爆款素材"), "material")
        self.assertEqual(detect_task_type("结合这张图找参考", has_image=True), "image_reference")

    def test_sparse_result_uses_similarity_signal(self):
        self.assertTrue(is_sparse_result([]))
        self.assertTrue(is_sparse_result([{"similarity": 0.9}]))
        self.assertTrue(is_sparse_result([
            {"similarity": 0.3}, {"similarity": 0.2}, {"similarity": 0.1},
        ]))
        self.assertFalse(is_sparse_result([
            {"similarity": 0.7}, {"similarity": 0.6}, {"similarity": 0.55},
        ]))
        self.assertTrue(is_sparse_result([
            {"rrf_score": 0.02}, {"rrf_score": 0.018}, {"rrf_score": 0.016},
        ]))

    def test_tokenize_query_handles_chinese_no_whitespace(self):
        tokens = tokenize_query("我们过去写过哪些文书相关内容")
        self.assertGreater(len(tokens), 1)
        self.assertIn("文书", tokens)
        self.assertIn("历史", tokenize_query("只参考团队历史内容"))

    def test_tokenize_query_strips_dangerous_chars_and_dedupes(self):
        tokens = tokenize_query("ab,cd (test) 申请 申请")
        for tok in tokens:
            self.assertFalse(any(ch in tok for ch in ",()*%"))
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_validate_citations_removes_fabricated_ids(self):
        answer = {
            "recommendations": [
                {"text": "用焦虑共鸣开头", "source_ids": ["ki_1", "fake"]},
                {"text": "加入清单式步骤", "source_ids": ["fake_only"]},
            ],
            "general_advice": [],
        }
        validated = validate_citations(answer, retrieved_ids={"ki_1"})

        self.assertEqual(validated["recommendations"][0]["source_ids"], ["ki_1"])
        self.assertEqual(len(validated["recommendations"]), 1)
        self.assertEqual(validated["general_advice"][0]["text"], "加入清单式步骤")
        self.assertEqual(
            validated["general_advice"][0]["reason"],
            "citation validation removed unsupported source ids",
        )


if __name__ == "__main__":
    unittest.main()
