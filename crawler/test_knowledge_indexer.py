import unittest

from knowledge_indexer import (
    build_benchmark_account_item,
    build_benchmark_post_item,
    build_content_hash,
    build_team_post_item,
    build_title_item,
    detect_language,
    upsert_knowledge_item,
)


class FakeTable:
    def __init__(self, client):
        self.client = client
        self.calls = []
        self.upsert_payload = None

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def maybe_single(self):
        self.calls.append(("maybe_single",))
        return self

    def upsert(self, payload, on_conflict=None):
        self.calls.append(("upsert", payload, on_conflict))
        self.upsert_payload = payload
        self.client.upserts.append((payload, on_conflict))
        return self

    def execute(self):
        self.calls.append(("execute",))
        if self.upsert_payload is not None:
            return None
        return self.client.select_response


class FakeSupabase:
    def __init__(self, select_response=None):
        self.select_response = select_response
        self.upserts = []
        self.tables = []

    def table(self, name):
        table = FakeTable(self)
        self.tables.append((name, table))
        return table


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

    def test_upsert_knowledge_item_handles_empty_maybe_single_response(self):
        sb = FakeSupabase(select_response=None)
        item = build_title_item({"id": "title-1", "title": "英国春天标题"})

        upsert_knowledge_item(sb, item)

        self.assertEqual(len(sb.upserts), 1)
        payload, on_conflict = sb.upserts[0]
        self.assertEqual(payload["source_type"], "title")
        self.assertEqual(on_conflict, "source_type,source_key")


if __name__ == "__main__":
    unittest.main()
