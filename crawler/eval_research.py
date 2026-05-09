#!/usr/bin/env python3
"""Run retrieval eval against the same hybrid pipeline used by /ai/research."""

import argparse
import asyncio
import json
import os
from typing import List

import voyageai
from supabase import create_client

import config as app_config
from retrieval import detect_task_type
from research_service import ResearchService

SUPABASE_URL = app_config.SUPABASE_URL
SUPABASE_KEY = app_config.SUPABASE_KEY
VOYAGE_API_KEY = getattr(app_config, "VOYAGE_API_KEY", os.getenv("VOYAGE_API_KEY", ""))

vo = None


def get_voyage_client():
    global vo
    if vo is None:
        if not VOYAGE_API_KEY:
            raise RuntimeError("未配置 VOYAGE_API_KEY，请在 crawler/config.py 或环境变量中设置。")
        vo = voyageai.Client(api_key=VOYAGE_API_KEY)
    return vo


async def embed_texts(texts: List[str], input_type: str = "document") -> List[List[float]]:
    return await asyncio.to_thread(
        lambda: get_voyage_client().embed(texts, model="voyage-3-lite", input_type=input_type).embeddings
    )


def recall_at_k(returned: List[str], expected: List[str], k: int = 10) -> float:
    if not expected:
        return 0.0
    hits = set(returned[:k]) & set(expected)
    return len(hits) / len(set(expected))


def reciprocal_rank(returned: List[str], expected: List[str]) -> float:
    expected_set = set(expected)
    for index, item_id in enumerate(returned, start=1):
        if item_id in expected_set:
            return 1.0 / index
    return 0.0


async def main_async(golden_set_path: str):
    with open(golden_set_path, "r", encoding="utf-8") as file_handle:
        questions = json.load(file_handle)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    service = ResearchService(sb, embed_texts)

    recalls: List[float] = []
    reciprocal_ranks: List[float] = []
    details = []

    for item in questions:
        task_type = detect_task_type(item["question"], has_image=bool(item.get("image_url")))
        rows = await service.retrieve(query=item["question"], task_type=task_type)
        returned = [str(row["id"]) for row in rows]
        expected = [str(value) for value in (item.get("expected_source_ids") or [])]
        recalls.append(recall_at_k(returned, expected))
        reciprocal_ranks.append(reciprocal_rank(returned, expected))
        details.append({
            "id": item.get("id"),
            "question": item.get("question"),
            "task_type": task_type,
            "expected": expected,
            "returned_top10": returned[:10],
        })

    report = {
        "questions": len(questions),
        "recall_at_10": sum(recalls) / len(recalls) if recalls else 0.0,
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "details": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("golden_set")
    args = parser.parse_args()
    asyncio.run(main_async(args.golden_set))


if __name__ == "__main__":
    main()
