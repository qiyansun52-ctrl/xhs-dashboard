from __future__ import annotations

import asyncio
from typing import Any, Dict, List


class _SearchSort:
    def __init__(self, value: str):
        self.value = value


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


def _extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "notes", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("items", "notes"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return []


def _is_signature_fallback_error(exc: Exception) -> bool:
    if isinstance(exc, TypeError):
        return True
    if not isinstance(exc, AttributeError):
        return False

    message = str(exc).lower()
    return (
        "sort" in message and "value" in message
    ) or (
        "has no attribute" in message and "value" in message
    ) or (
        "unexpected keyword" in message
    ) or (
        "unexpected argument" in message
    ) or (
        "positional argument" in message
    ) or (
        "required positional argument" in message
    )


async def search_keyword_notes(client, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    method_names = ("search_note", "search_notes", "get_note_by_keyword")
    for method_name in method_names:
        method = getattr(client, method_name, None)
        if not method:
            continue
        try:
            payload = await _maybe_await(
                method(
                    keyword=keyword,
                    page=1,
                    page_size=limit,
                    sort=_SearchSort("popularity_descending"),
                )
            )
        except (TypeError, AttributeError) as exc:
            if not _is_signature_fallback_error(exc):
                raise
            try:
                payload = await _maybe_await(method(keyword=keyword, page=1, page_size=limit))
            except TypeError:
                payload = await _maybe_await(method(keyword, 1, limit))
        return _extract_items(payload)[:limit]

    raise RuntimeError("当前 MediaCrawler 客户端不支持关键词搜索，请先补充 XHS 搜索适配器。")


def select_benchmark_accounts(rows: List[Dict[str, Any]], queries: List[str], max_accounts: int = 3) -> List[Dict[str, Any]]:
    query_text = " ".join(queries)

    def score(row: Dict[str, Any]) -> tuple:
        destination = row.get("destination") or ""
        content_type = row.get("content_type") or ""
        note_direction = row.get("note_direction") or ""
        match_score = sum(1 for value in (destination, content_type, note_direction) if value and value in query_text)
        return (match_score, int(row.get("followers") or 0), str(row.get("fetched_at") or ""))

    return sorted(rows, key=score, reverse=True)[:max_accounts]


async def delay_between_requests(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
