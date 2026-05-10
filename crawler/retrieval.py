from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Set


EXPERIENCE_WORDS = ("过去", "历史", "我们写过", "团队", "之前", "过往")
MATERIAL_WORDS = ("素材", "爆款", "参考", "对标", "收藏")
KEYWORD_HINTS = (
    "文书", "申请", "焦虑", "英国", "美国", "澳洲", "加拿大", "留学",
    "选校", "签证", "雅思", "托福", "offer", "标题", "收藏", "爆款",
)
_UNSAFE_TOKEN_CHARS = ",()*%"


def detect_task_type(question: str, has_image: bool = False) -> str:
    text = question or ""
    if has_image:
        return "image_reference"
    if any(word in text for word in EXPERIENCE_WORDS):
        return "experience"
    if any(word in text for word in MATERIAL_WORDS):
        return "material"
    return "mixed"


def tokenize_query(query: str, max_tokens: int = 12) -> List[str]:
    """Split Chinese-heavy queries into safe keyword tokens for ilike retrieval."""
    if not query:
        return []

    cleaned = query.replace("，", " ").replace(",", " ").replace("。", " ")
    raw_parts = [part for part in cleaned.split() if part]
    tokens: List[str] = []
    lowered = query.lower()

    for hint in KEYWORD_HINTS:
        if hint.lower() in lowered:
            tokens.append(hint)

    for part in raw_parts:
        cjk_chars = [char for char in part if "\u4e00" <= char <= "\u9fff"]
        ascii_word = re.sub(r"[^A-Za-z0-9]", "", part)
        if len(cjk_chars) >= 2:
            tokens.extend("".join(cjk_chars[index:index + 2]) for index in range(len(cjk_chars) - 1))
        elif cjk_chars:
            tokens.append(cjk_chars[0])
        if len(ascii_word) >= 2:
            tokens.append(ascii_word.lower())

    safe: List[str] = []
    seen: Set[str] = set()
    for token in tokens:
        if not token or any(char in token for char in _UNSAFE_TOKEN_CHARS):
            continue
        if token in seen:
            continue
        seen.add(token)
        safe.append(token)
        if len(safe) >= max_tokens:
            break
    return safe


def rrf_merge(result_lists: Sequence[Sequence[dict]], k: int = 60) -> List[dict]:
    scores: Dict[str, float] = {}
    rows: Dict[str, dict] = {}
    for result_list in result_lists:
        for rank, row in enumerate(result_list, start=1):
            item_id = str(row["id"])
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in rows:
                rows[item_id] = dict(row)

    merged: List[dict] = []
    for item_id, row in rows.items():
        row["rrf_score"] = scores[item_id]
        merged.append(row)
    return sorted(merged, key=lambda row: row["rrf_score"], reverse=True)


def is_sparse_result(rows: Sequence[dict], min_similarity: float = 0.55, min_count: int = 3) -> bool:
    """Decide whether the retrieved internal knowledge is too sparse for a confident answer."""
    if not rows or len(rows) < min_count:
        return True

    similarities = [
        float(row["similarity"])
        for row in rows
        if row.get("similarity") is not None
    ]
    if not similarities:
        return True
    return max(similarities) < min_similarity


def validate_citations(answer: dict, retrieved_ids: Iterable[str]) -> dict:
    allowed: Set[str] = {str(item_id) for item_id in retrieved_ids}
    cleaned = dict(answer)
    valid_recommendations = []
    general_advice = list(cleaned.get("general_advice") or [])

    for recommendation in cleaned.get("recommendations") or []:
        source_ids = [source_id for source_id in recommendation.get("source_ids", []) if source_id in allowed]
        if source_ids:
            updated = dict(recommendation)
            updated["source_ids"] = source_ids
            valid_recommendations.append(updated)
        else:
            general_advice.append({
                "text": recommendation.get("text", ""),
                "reason": "citation validation removed unsupported source ids",
            })

    cleaned["recommendations"] = valid_recommendations
    cleaned["general_advice"] = general_advice
    cleaned["material_references"] = [
        source_id for source_id in cleaned.get("material_references", []) if source_id in allowed
    ]
    cleaned["team_history_references"] = [
        source_id for source_id in cleaned.get("team_history_references", []) if source_id in allowed
    ]
    return cleaned
