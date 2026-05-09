import unittest

from knowledge_indexer import (
    build_benchmark_account_item,
    build_benchmark_post_item,
    build_content_hash,
    build_team_post_item,
    detect_language,
)


class KnowledgeIndexerTests(unittest.TestCase):
    def test_detect_language(self):
        self.assertEqual(detect_language("英国留学申请"), "zh")
        self.assertEqual(detect_language("personal statement checklist"), "en")
        self.assertEqual(detect_language("英国 UCAS checklist"), "mixed")

    def test_build_content_hash_changes_when_content_changes(self):
        first = build_content_hash("title", "caption")
        second = build_content_hash("title", "different caption")
        self.assertNotEqual(first, second)

    def test_build_team_post_item_uses_post_stats(self):
        item = build_team_post_item(
            {
                "id": "post-1",
                "title": "英国文书怎么准备",
                "caption": "三步拆解申请文书",
                "tags": ["英国", "文书"],
                "images": ["https://example.com/a.jpg"],
                "account_id": 7,
                "status": "published",
                "created_at": "2026-05-01T00:00:00+00:00",
            },
            {"likes": 12, "saves": 34, "comments": 5, "views": 1000},
        )
        self.assertEqual(item["source_type"], "team_post")
        self.assertEqual(item["source_key"], "post-1")
        self.assertEqual(item["saves_count"], 34)
        self.assertIn("英国文书怎么准备", item["content"])

    def test_build_benchmark_post_item_has_parent_and_stable_key(self):
        item = build_benchmark_post_item(
            benchmark_id="bench-1",
            account_name="英国申请学姐",
            post={
                "note_id": "note-9",
                "title": "申请季别崩",
                "caption": "焦虑也能拆成步骤",
                "tags": ["申请焦虑"],
                "likes": 99,
                "cover_image": "https://example.com/cover.jpg",
            },
        )
        self.assertEqual(item["source_type"], "benchmark_post")
        self.assertEqual(item["source_key"], "bench-1:note-9")
        self.assertEqual(item["parent_source_id"], "bench-1")
        self.assertEqual(item["likes_count"], 99)

    def test_build_benchmark_account_item_uses_positioning_fields(self):
        item = build_benchmark_account_item({
            "id": "bench-1",
            "name": "英国申请学姐",
            "bio": "专讲英国申请",
            "destination": "英国",
            "content_type": "申请干货",
            "note_direction": "焦虑拆解",
            "consumer_words": "怕错过DDL",
            "followers": 12000,
            "fetch_status": "done",
        })
        self.assertEqual(item["source_type"], "benchmark_account")
        self.assertTrue(item["is_active"])
        self.assertIn("怕错过DDL", item["content"])


if __name__ == "__main__":
    unittest.main()
