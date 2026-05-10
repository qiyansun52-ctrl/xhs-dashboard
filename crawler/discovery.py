from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Sequence, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


COUNTRY_HINTS = ("英国", "美国", "澳洲", "澳大利亚", "加拿大", "香港", "新加坡")
CONTENT_HINTS = ("申请", "文书", "选校", "签证", "雅思", "托福", "offer", "留学", "焦虑")
MOOD_HINTS = ("焦虑", "崩溃", "后悔", "避坑", "真实", "省钱", "经验", "攻略")
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {"xsec_token", "spm", "share_from_user_hidden"}


def normalize_question(question: str) -> str:
    text = (question or "").strip()
    text = re.sub(r"[，。！？、,.!?]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_any(text: str, values: Sequence[str]) -> List[str]:
    return [value for value in values if value in text]


def derive_search_queries(
    question: str,
    image_keywords: Sequence[str] | None = None,
    weak_titles: Sequence[str] | None = None,
    max_queries: int = 4,
) -> List[str]:
    if max_queries <= 0:
        return []

    text = normalize_question(" ".join([
        question or "",
        " ".join(image_keywords or []),
        " ".join(weak_titles or []),
    ]))
    countries = _contains_any(text, COUNTRY_HINTS)
    content = _contains_any(text, CONTENT_HINTS)
    moods = _contains_any(text, MOOD_HINTS)

    country = countries[0] if countries else "留学"
    if country == "澳大利亚":
        country = "澳洲"
    topic = content[0] if content else "申请"
    mood = moods[0] if moods else "经验"

    candidates = [
        f"{country}留学 {topic}{mood}" if country != "留学" else f"留学 {topic}{mood}",
        f"{country}申请 {topic}" if country != "留学" else f"留学申请 {topic}",
        f"{country}留学 {mood}" if country != "留学" else f"留学 {mood}",
        f"{topic} {mood} 小红书",
    ]

    cleaned: List[str] = []
    seen: Set[str] = set()
    for query in candidates:
        query = normalize_question(query)
        if not query or query in seen:
            continue
        seen.add(query)
        cleaned.append(query[:24])
        if len(cleaned) >= max_queries:
            break
    return cleaned


def _log_norm(value: Any) -> float:
    try:
        number = max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        number = 0.0
    return math.log1p(number) / math.log1p(100000)


def _safe_relevance_score(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(min(number, 1.0), 0.0)


def score_candidate(row: Dict[str, Any], relevance_score: float = 0.5, source_path: str = "keyword_search") -> float:
    trust_boost = 1.0 if source_path == "benchmark_expansion" else 0.0
    score = (
        _safe_relevance_score(relevance_score) * 0.45
        + _log_norm(row.get("saves")) * 0.25
        + _log_norm(row.get("comments")) * 0.12
        + _log_norm(row.get("likes")) * 0.10
        + trust_boost * 0.05
        + _log_norm(row.get("views")) * 0.03
    )
    return round(score, 6)


def _is_tracking_query_param(name: str) -> bool:
    return name in TRACKING_QUERY_PARAMS or any(name.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)


def _normalize_candidate_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlsplit(url.strip())
    query_params = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_param(name)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_params), ""))


def candidate_dedupe_key(row: Dict[str, Any]) -> str:
    note_id = str(row.get("xhs_note_id") or row.get("note_id") or "").strip()
    if note_id:
        return f"note:{note_id}"
    return f"url:{_normalize_candidate_url(str(row.get('url') or ''))}"


def build_candidate_url(note_id: str | None, fallback_url: str | None = None) -> str:
    if note_id:
        return f"https://www.xiaohongshu.com/explore/{note_id}"
    return fallback_url or ""


def _as_candidate_id_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return []
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def validate_external_candidate_ids(answer: dict, allowed_candidate_ids: Iterable[str]) -> dict:
    allowed = {str(item_id) for item_id in allowed_candidate_ids}
    cleaned = dict(answer)
    valid_recommendations = []
    general_advice = list(cleaned.get("general_advice") or [])

    for recommendation in cleaned.get("recommendations") or []:
        candidate_ids = [
            str(candidate_id)
            for candidate_id in _as_candidate_id_list(recommendation.get("candidate_ids"))
            if str(candidate_id) in allowed
        ]
        if candidate_ids:
            updated = dict(recommendation)
            updated["candidate_ids"] = candidate_ids
            valid_recommendations.append(updated)
        else:
            general_advice.append({
                "text": recommendation.get("text", ""),
                "reason": "external candidate validation removed unsupported candidate ids",
            })

    cleaned["recommendations"] = valid_recommendations
    cleaned["general_advice"] = general_advice
    cleaned["candidate_references"] = [
        candidate_id
        for candidate_id in _as_candidate_id_list(cleaned.get("candidate_references"))
        if str(candidate_id) in allowed
    ]
    return cleaned
