from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence

from retrieval import KEYWORD_HINTS, rrf_merge, tokenize_query


Intent = Literal[
    "find_material",
    "recall_team_history",
    "image_reference",
    "compare",
    "evaluate",
    "general_qa",
]

SparseLevel = Literal["empty", "weak", "strong"]

COUNTRY_TOKENS = ("英国", "美国", "澳洲", "澳大利亚", "加拿大", "新加坡", "香港")
TEAM_HISTORY_HINTS = ("过去", "历史", "我们写过", "团队", "之前", "过往")
MATERIAL_HINTS = ("素材", "爆款", "参考", "对标", "收藏", "标题")
COMPARE_HINTS = ("对比", "比较", "区别", "哪个更好")
EVALUATE_HINTS = ("评价", "检查", "审核", "风险", "违禁词", "广告感", "好不好")
TIME_RECENT_HINTS = ("最近", "今天", "本周", "这周", "趋势", "热点", "正在火")

SCAFFOLD_PHRASES = (
    "帮我找一下",
    "帮我",
    "找一下",
    "有关于",
    "有没有",
    "关于",
    "有关",
    "一下",
)

SCAFFOLD_TOKENS = {
    "帮我",
    "我找",
    "找一",
    "一下",
    "下有",
    "有关",
    "关于",
    "标题",
    "素材",
    "内容",
    "方向",
    "参考",
    "相关",
}

DOMAIN_HINTS = tuple(dict.fromkeys((
    *KEYWORD_HINTS,
    "春天",
    "春日",
    "春季",
    "夏天",
    "秋天",
    "冬天",
    "樱花",
    "花瓣",
    "违禁词",
    "广告感",
    "选题",
    "文案",
)))

EVIDENCE_TOKEN_SYNONYMS = {
    "春天": ("春天", "春日", "春季", "spring", "樱花", "花瓣"),
    "夏天": ("夏天", "夏日", "夏季", "summer"),
    "秋天": ("秋天", "秋日", "秋季", "autumn", "fall"),
    "冬天": ("冬天", "冬日", "冬季", "winter"),
}


@dataclass
class IntentFilters:
    country: Optional[str] = None
    source_type_preference: List[str] = field(default_factory=list)
    account_id: Optional[int] = None


@dataclass
class IntentPayload:
    raw_question: str
    intent: Intent
    domain_entities: List[str] = field(default_factory=list)
    time_sensitivity: Literal["none", "recent", "trending"] = "none"
    filters: IntentFilters = field(default_factory=IntentFilters)
    expanded_queries: List[str] = field(default_factory=list)
    confidence: float = 0.0
    parser_version: str = "fallback-v1"
    topic_tokens: List[str] = field(default_factory=list)
    evidence_tokens: List[str] = field(default_factory=list)
    broad_tokens: List[str] = field(default_factory=list)
    scaffold_tokens: List[str] = field(default_factory=list)


@dataclass
class RetrievalProfile:
    name: str
    absolute_floor: float
    relative_floor_ratio: float
    strong_threshold: float
    evidence_budget: Dict[str, int]
    evidence_total: int
    content_max_chars: int
    sparse_empty_threshold: float
    sparse_weak_threshold: float
    sparse_min_count: int
    sparse_min_strong: int
    vector_match_count: int = 30


@dataclass
class FilteredCandidates:
    rows: List[Dict[str, Any]]
    dropped_counts: Dict[str, int]
    top_similarity: float
    candidate_count: int
    filtered_count: int


@dataclass
class SelectedEvidence:
    rows: List[Dict[str, Any]]
    overflow_ids: List[str]


PROFILES: Dict[str, RetrievalProfile] = {
    "find_material": RetrievalProfile(
        name="find_material",
        absolute_floor=0.35,
        relative_floor_ratio=0.70,
        strong_threshold=0.55,
        evidence_budget={"viral_post": 3, "benchmark_post": 2, "topic": 1, "title": 1},
        evidence_total=7,
        content_max_chars=400,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=3,
        sparse_min_strong=2,
    ),
    "recall_team_history": RetrievalProfile(
        name="recall_team_history",
        absolute_floor=0.45,
        relative_floor_ratio=0.70,
        strong_threshold=0.60,
        evidence_budget={"team_post": 4, "account": 1, "benchmark_account": 1, "viral_post": 1},
        evidence_total=7,
        content_max_chars=400,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=3,
        sparse_min_strong=2,
    ),
    "image_reference": RetrievalProfile(
        name="image_reference",
        absolute_floor=0.35,
        relative_floor_ratio=0.68,
        strong_threshold=0.55,
        evidence_budget={"viral_post": 3, "benchmark_post": 2, "team_post": 2},
        evidence_total=7,
        content_max_chars=350,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=3,
        sparse_min_strong=2,
    ),
    "compare": RetrievalProfile(
        name="compare",
        absolute_floor=0.40,
        relative_floor_ratio=0.70,
        strong_threshold=0.58,
        evidence_budget={"viral_post": 2, "benchmark_post": 2, "team_post": 2, "topic": 1},
        evidence_total=7,
        content_max_chars=400,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=3,
        sparse_min_strong=2,
    ),
    "evaluate": RetrievalProfile(
        name="evaluate",
        absolute_floor=0.35,
        relative_floor_ratio=0.70,
        strong_threshold=0.55,
        evidence_budget={"banned_word": 3, "team_post": 2, "topic": 1, "title": 1},
        evidence_total=7,
        content_max_chars=400,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=2,
        sparse_min_strong=1,
    ),
    "general_qa": RetrievalProfile(
        name="general_qa",
        absolute_floor=0.40,
        relative_floor_ratio=0.70,
        strong_threshold=0.58,
        evidence_budget={"viral_post": 2, "benchmark_post": 2, "team_post": 2, "topic": 1},
        evidence_total=7,
        content_max_chars=400,
        sparse_empty_threshold=0.30,
        sparse_weak_threshold=0.45,
        sparse_min_count=3,
        sparse_min_strong=2,
    ),
}


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _intent_for_text(text: str, has_image: bool = False) -> Intent:
    if has_image:
        return "image_reference"
    if any(hint in text for hint in EVALUATE_HINTS):
        return "evaluate"
    if any(hint in text for hint in COMPARE_HINTS):
        return "compare"
    if any(hint in text for hint in TEAM_HISTORY_HINTS):
        return "recall_team_history"
    if any(hint in text for hint in MATERIAL_HINTS):
        return "find_material"
    return "general_qa"


def _source_preferences(intent: Intent) -> List[str]:
    return list(profile_for_intent(intent).evidence_budget.keys())


def _strip_scaffold(text: str) -> str:
    cleaned = text
    for phrase in SCAFFOLD_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    return cleaned


def parse_query_fallback(question: str, has_image: bool = False) -> IntentPayload:
    raw = str(question or "").strip()
    intent = _intent_for_text(raw, has_image=has_image)
    countries = [country for country in COUNTRY_TOKENS if country in raw]
    country = countries[0] if countries else None
    scaffold_tokens = [token for token in SCAFFOLD_TOKENS if token in raw]
    cleaned = _strip_scaffold(raw)

    explicit_hints = [hint for hint in DOMAIN_HINTS if hint.lower() in raw.lower()]
    lexical_tokens = tokenize_query(cleaned, max_tokens=24)
    topic_tokens = _unique([
        token
        for token in [*explicit_hints, *lexical_tokens]
        if token not in SCAFFOLD_TOKENS and token not in COUNTRY_TOKENS and len(token) >= 2
    ])
    broad_tokens = _unique([*countries, *[token for token in lexical_tokens if token in COUNTRY_TOKENS]])

    evidence_tokens: List[str] = []
    for token in topic_tokens:
        evidence_tokens.extend(EVIDENCE_TOKEN_SYNONYMS.get(token, (token,)))
    evidence_tokens = _unique(evidence_tokens)

    time_sensitivity: Literal["none", "recent", "trending"] = "none"
    if any(hint in raw for hint in TIME_RECENT_HINTS):
        time_sensitivity = "trending" if any(hint in raw for hint in ("趋势", "热点", "正在火")) else "recent"

    expanded_queries = _unique([
        raw,
        " ".join([part for part in [country, *topic_tokens[:3]] if part]),
        " ".join(topic_tokens[:4]),
    ])

    return IntentPayload(
        raw_question=raw,
        intent=intent,
        domain_entities=broad_tokens,
        time_sensitivity=time_sensitivity,
        filters=IntentFilters(
            country=country,
            source_type_preference=_source_preferences(intent),
        ),
        expanded_queries=expanded_queries,
        confidence=0.72 if intent != "general_qa" else 0.45,
        topic_tokens=topic_tokens,
        evidence_tokens=evidence_tokens,
        broad_tokens=broad_tokens,
        scaffold_tokens=scaffold_tokens,
    )


def profile_for_intent(intent: str) -> RetrievalProfile:
    return copy.deepcopy(PROFILES.get(str(intent), PROFILES["general_qa"]))


def _similarity(row: Dict[str, Any]) -> float:
    try:
        return float(row.get("similarity") or 0)
    except (TypeError, ValueError):
        return 0.0


def filter_candidates(result_lists: Sequence[Sequence[Dict[str, Any]]], profile: RetrievalProfile) -> FilteredCandidates:
    merged = rrf_merge(result_lists)
    merged = sorted(
        merged,
        key=lambda row: (_similarity(row), float(row.get("rrf_score") or 0)),
        reverse=True,
    )
    top_similarity = _similarity(merged[0]) if merged else 0.0
    relative_floor = top_similarity * profile.relative_floor_ratio if top_similarity > 0 else 0.0
    dropped_counts = {"below_absolute": 0, "below_relative": 0}
    kept: List[Dict[str, Any]] = []

    for row in merged:
        similarity = _similarity(row)
        if similarity < profile.absolute_floor:
            dropped_counts["below_absolute"] += 1
            continue
        if top_similarity > 0 and similarity < relative_floor:
            dropped_counts["below_relative"] += 1
            continue
        kept.append(row)

    return FilteredCandidates(
        rows=kept,
        dropped_counts=dropped_counts,
        top_similarity=top_similarity,
        candidate_count=len(merged),
        filtered_count=len(kept),
    )


def select_evidence(rows: Sequence[Dict[str, Any]], profile: RetrievalProfile) -> SelectedEvidence:
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    overflow_ids: List[str] = []

    for source_type, budget in profile.evidence_budget.items():
        typed_rows = [row for row in rows if row.get("source_type") == source_type]
        for row in typed_rows[:budget]:
            row_id = str(row.get("id"))
            if row_id in selected_ids or len(selected) >= profile.evidence_total:
                continue
            selected.append(row)
            selected_ids.add(row_id)
        for row in typed_rows[budget:]:
            row_id = str(row.get("id"))
            if row_id not in selected_ids:
                overflow_ids.append(row_id)

    if len(selected) < profile.evidence_total:
        for row in rows:
            row_id = str(row.get("id"))
            if row_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(row_id)
            if len(selected) >= profile.evidence_total:
                break

    for row in rows:
        row_id = str(row.get("id"))
        if row_id not in selected_ids and row_id not in overflow_ids:
            overflow_ids.append(row_id)

    return SelectedEvidence(rows=selected, overflow_ids=overflow_ids)


def classify_sparse(rows: Sequence[Dict[str, Any]], profile: RetrievalProfile) -> SparseLevel:
    if not rows:
        return "empty"

    similarities = [_similarity(row) for row in rows if row.get("similarity") is not None]
    if not similarities:
        return "empty"

    top_similarity = max(similarities)
    strong_count = sum(1 for similarity in similarities if similarity >= profile.strong_threshold)
    if (
        len(rows) >= profile.sparse_min_count
        and strong_count >= profile.sparse_min_strong
        and top_similarity >= profile.sparse_weak_threshold
    ):
        return "strong"
    return "weak"
