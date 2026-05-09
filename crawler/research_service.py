from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from research_models import ImageAnalysis, KnowledgeSource, ResearchAnswer, ResearchRequest
from discovery import derive_search_queries
from retrieval import (
    detect_task_type,
    is_sparse_result,
    rrf_merge,
    tokenize_query,
    validate_citations,
)

try:
    import config as app_config
except Exception:
    app_config = None


def _config_value(name: str, default: Any) -> Any:
    return getattr(app_config, name, default) if app_config else default


OPENAI_API_KEY = _config_value("OPENAI_API_KEY", "")
OPENAI_TEXT_MODEL = _config_value("OPENAI_TEXT_MODEL", "gpt-4.1-mini")
OPENAI_VISION_MODEL = _config_value("OPENAI_VISION_MODEL", "gpt-4.1-mini")
AI_RESEARCH_MIN_RESULTS = _config_value("AI_RESEARCH_MIN_RESULTS", 3)
AI_RESEARCH_MIN_SIMILARITY = _config_value("AI_RESEARCH_MIN_SIMILARITY", 0.55)
EXTERNAL_DISCOVERY_ENABLED = _config_value("EXTERNAL_DISCOVERY_ENABLED", False)
EXTERNAL_DISCOVERY_TRIGGER_MODE = _config_value("EXTERNAL_DISCOVERY_TRIGGER_MODE", "ask_first")
EXTERNAL_DISCOVERY_MAX_QUERIES = _config_value("EXTERNAL_DISCOVERY_MAX_QUERIES", 4)


def model_to_dict(model) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class ResearchService:
    def __init__(self, supabase_client, embed_texts):
        self.sb = supabase_client
        self.embed_texts = embed_texts
        self.openai_key = OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.openai = OpenAI(api_key=self.openai_key) if self.openai_key and OpenAI else None

    async def research(self, req: ResearchRequest) -> ResearchAnswer:
        task_type = detect_task_type(req.question, has_image=bool(req.image_url))
        image_analysis = None
        image_query = ""
        messages: List[str] = []

        if req.image_url:
            try:
                image_analysis = await self.analyze_image(req.image_url)
                image_query = " ".join([
                    image_analysis.subject,
                    image_analysis.scene,
                    image_analysis.mood,
                    image_analysis.visual_style,
                    image_analysis.content_direction,
                    " ".join(image_analysis.keywords),
                ]).strip()
            except Exception:
                messages.append("图片分析失败，已先基于文字问题回答。")

        query = "\n".join(part for part in [
            req.question,
            req.previous_answer_summary or "",
            image_query,
        ] if part)
        retrieved_rows = await self.retrieve(query=query, task_type=task_type)
        sparse = is_sparse_result(
            retrieved_rows,
            min_similarity=AI_RESEARCH_MIN_SIMILARITY,
            min_count=AI_RESEARCH_MIN_RESULTS,
        )
        if sparse:
            messages.append("内部资料匹配较少，以下建议包含少量通用创作建议。")

        try:
            answer_payload = await self.generate_answer(
                question=req.question,
                task_type=task_type,
                rows=retrieved_rows,
                sparse=sparse,
                image_analysis=image_analysis,
            )
        except Exception:
            answer_payload = self.generate_fallback_answer(
                req.question,
                task_type,
                retrieved_rows,
                sparse,
                image_analysis,
            )

        validated = validate_citations(answer_payload, retrieved_ids={str(row["id"]) for row in retrieved_rows})
        sources = [KnowledgeSource(**self._source_shape(row)) for row in retrieved_rows]
        cited_ids = set()
        for recommendation in validated.get("recommendations", []) or []:
            cited_ids.update(recommendation.get("source_ids") or [])
        cited_ids.update(validated.get("material_references", []) or [])
        cited_ids.update(validated.get("team_history_references", []) or [])
        cited_sources = [source for source in sources if source.id in cited_ids]
        weak_titles = [
            str(row.get("title") or "")
            for row in retrieved_rows[:5]
            if row.get("title")
        ]
        suggested_search_queries = derive_search_queries(
            req.question,
            image_keywords=image_analysis.keywords if image_analysis else [],
            weak_titles=weak_titles,
            max_queries=EXTERNAL_DISCOVERY_MAX_QUERIES,
        ) if sparse and EXTERNAL_DISCOVERY_ENABLED else []
        discovery_trigger_reason = "zero_recall" if sparse and not retrieved_rows else "sparse_recall"

        return ResearchAnswer(
            question=req.question,
            task_type=task_type,
            conclusion=validated["conclusion"],
            recommendations=validated.get("recommendations", []),
            material_references=validated.get("material_references", []),
            team_history_references=validated.get("team_history_references", []),
            related_sources=sources,
            cited_sources=cited_sources,
            image_analysis=image_analysis,
            general_advice=validated.get("general_advice", []),
            sparse=sparse,
            can_external_discover=bool(sparse and EXTERNAL_DISCOVERY_ENABLED),
            discovery_trigger_reason=discovery_trigger_reason if sparse and EXTERNAL_DISCOVERY_ENABLED else None,
            suggested_search_queries=suggested_search_queries,
            discovery_trigger_mode=EXTERNAL_DISCOVERY_TRIGGER_MODE,
            discovery_job_id=None,
            message=" ".join(messages) if messages else None,
        )

    async def retrieve(self, query: str, task_type: str) -> List[Dict[str, Any]]:
        embeds = await self.embed_texts([query], input_type="query")
        source_types = self._source_types_for_task(task_type)
        vector_res = self.sb.rpc("match_knowledge_items", {
            "query_embedding": embeds[0],
            "match_count": 30,
            "source_types": source_types,
            "country_filter": None,
        }).execute()
        vector_rows = vector_res.data or []

        keyword_rows = self.keyword_candidates(query, source_types=source_types)
        merged = self._rerank_for_task(rrf_merge([vector_rows, keyword_rows]), task_type)
        return merged[:20]

    def keyword_candidates(self, query: str, source_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        tokens = tokenize_query(query)
        if not tokens:
            return []

        query_builder = self.sb.table("knowledge_items").select("*").eq("is_active", True).limit(30)
        if source_types:
            query_builder = query_builder.in_("source_type", source_types)

        clauses: List[str] = []
        for token in tokens:
            clauses.append(f"title.ilike.%{token}%")
            clauses.append(f"content.ilike.%{token}%")
        res = query_builder.or_(",".join(clauses)).execute()
        return res.data or []

    def _rerank_for_task(self, rows: List[Dict[str, Any]], task_type: str) -> List[Dict[str, Any]]:
        def relevance(row: Dict[str, Any]) -> float:
            return float(row.get("similarity") or 0) + float(row.get("rrf_score") or 0)

        def performance(row: Dict[str, Any]) -> float:
            return (
                float(row.get("saves_count") or 0) * 3
                + float(row.get("comments_count") or 0) * 2
                + float(row.get("likes_count") or 0)
                + float(row.get("views_count") or 0) / 100
            )

        def freshness(row: Dict[str, Any]) -> str:
            return str(row.get("published_at") or "")

        if task_type == "experience":
            return sorted(
                rows,
                key=lambda row: (
                    row.get("source_type") == "team_post",
                    relevance(row),
                    freshness(row),
                    performance(row),
                ),
                reverse=True,
            )
        if task_type == "material":
            return sorted(
                rows,
                key=lambda row: (
                    relevance(row),
                    performance(row),
                    freshness(row),
                ),
                reverse=True,
            )
        if task_type == "image_reference":
            return sorted(
                rows,
                key=lambda row: (
                    relevance(row),
                    performance(row),
                    row.get("source_type") in ("viral_post", "benchmark_post", "team_post"),
                ),
                reverse=True,
            )

        material = [
            row for row in rows
            if row.get("source_type") in ("viral_post", "benchmark_post", "topic", "title")
        ]
        history = [
            row for row in rows
            if row.get("source_type") in ("team_post", "account", "benchmark_account")
        ]
        other = [row for row in rows if row not in material and row not in history]

        material = sorted(material, key=lambda row: (relevance(row), performance(row)), reverse=True)
        history = sorted(history, key=lambda row: (row.get("source_type") == "team_post", relevance(row)), reverse=True)
        interleaved: List[Dict[str, Any]] = []
        while material or history:
            if material:
                interleaved.append(material.pop(0))
            if history:
                interleaved.append(history.pop(0))
        return interleaved + sorted(other, key=relevance, reverse=True)

    async def analyze_image(self, image_url: str) -> ImageAnalysis:
        if self.openai:
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string"},
                    "scene": {"type": "string"},
                    "mood": {"type": "string"},
                    "visual_style": {"type": "string"},
                    "content_direction": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                },
                "required": [
                    "subject",
                    "scene",
                    "mood",
                    "visual_style",
                    "content_direction",
                    "keywords",
                    "description",
                ],
            }

            def _call():
                return self.openai.responses.create(
                    model=OPENAI_VISION_MODEL,
                    input=[{
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "请分析这张小红书配图，输出可用于留学内容选题检索的结构化 JSON。"},
                            {"type": "input_image", "image_url": image_url, "detail": "auto"},
                        ],
                    }],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "image_analysis",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )

            resp = await asyncio.to_thread(_call)
            return ImageAnalysis(**json.loads(resp.output_text))

        return ImageAnalysis(
            subject="",
            scene="",
            mood="",
            visual_style="",
            content_direction="",
            keywords=[],
            description=f"图片已上传：{image_url}",
        )

    async def generate_answer(
        self,
        question: str,
        task_type: str,
        rows: List[Dict[str, Any]],
        sparse: bool,
        image_analysis: Optional[ImageAnalysis],
    ) -> Dict[str, Any]:
        if not self.openai or not rows:
            return self.generate_fallback_answer(question, task_type, rows, sparse, image_analysis)

        source_context = [
            {
                "id": str(row["id"]),
                "source_type": row.get("source_type"),
                "title": row.get("title"),
                "content": (row.get("content") or "")[:800],
                "likes_count": row.get("likes_count"),
                "saves_count": row.get("saves_count"),
            }
            for row in rows[:12]
        ]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "conclusion": {"type": "string"},
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "text": {"type": "string"},
                            "source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["text", "source_ids"],
                    },
                },
                "material_references": {"type": "array", "items": {"type": "string"}},
                "team_history_references": {"type": "array", "items": {"type": "string"}},
                "image_analysis": {"type": ["object", "null"]},
                "general_advice": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "text": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["text", "reason"],
                    },
                },
            },
            "required": [
                "conclusion",
                "recommendations",
                "material_references",
                "team_history_references",
                "image_analysis",
                "general_advice",
            ],
        }
        prompt = {
            "question": question,
            "task_type": task_type,
            "sparse": sparse,
            "image_analysis": model_to_dict(image_analysis) if image_analysis else None,
            "allowed_sources": source_context,
            "rules": [
                "只能引用 allowed_sources 中存在的 id；source_ids 数组里每个 id 必须严格匹配 allowed_sources 的 id。",
                "conclusion 中不得提到 allowed_sources 之外的素材标题、账号或团队历史；如果没有内部证据，conclusion 要直接说明匹配较少。",
                "每条由内部资料支持的 recommendation 必须带至少一个 source_ids。",
                "没有内部证据的建议必须放进 general_advice，并写明 reason。",
                "回答要面向小红书留学内容运营，中文输出。",
            ],
        }

        def _call():
            return self.openai.responses.create(
                model=OPENAI_TEXT_MODEL,
                instructions="你是小红书留学内容团队的 AI 素材研究员。你必须输出符合 schema 的 JSON，且不得编造 allowed_sources 之外的素材。",
                input=json.dumps(prompt, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "research_answer",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )

        resp = await asyncio.to_thread(_call)
        return json.loads(resp.output_text)

    def generate_fallback_answer(
        self,
        question: str,
        task_type: str,
        rows: List[Dict[str, Any]],
        sparse: bool,
        image_analysis: Optional[ImageAnalysis],
    ) -> Dict[str, Any]:
        if not rows:
            return {
                "conclusion": "知识库中没有匹配内容。",
                "recommendations": [],
                "material_references": [],
                "team_history_references": [],
                "image_analysis": model_to_dict(image_analysis) if image_analysis else None,
                "general_advice": [],
            }

        top = rows[:3]
        recommendations = [
            {"text": f"优先参考《{row.get('title') or '无标题'}》的内容角度。", "source_ids": [str(row["id"])]}
            for row in top
        ]
        return {
            "conclusion": "根据当前知识库，下面这些素材和历史内容与问题最相关。" if not sparse else "内部资料匹配较少，可以先参考少量匹配内容，再结合通用创作判断。",
            "recommendations": recommendations,
            "material_references": [
                str(row["id"])
                for row in rows
                if row.get("source_type") in ("viral_post", "benchmark_post", "topic", "title")
            ],
            "team_history_references": [
                str(row["id"])
                for row in rows
                if row.get("source_type") == "team_post"
            ],
            "image_analysis": model_to_dict(image_analysis) if image_analysis else None,
            "general_advice": [{"text": "可用情绪共鸣开头，再给出具体步骤。", "reason": "internal evidence was sparse"}] if sparse else [],
        }

    def _source_types_for_task(self, task_type: str) -> Optional[List[str]]:
        if task_type == "experience":
            return ["team_post", "account"]
        if task_type == "material":
            return ["viral_post", "benchmark_post", "topic", "title"]
        return [
            "viral_post",
            "benchmark_account",
            "benchmark_post",
            "topic",
            "title",
            "team_post",
            "account",
        ]

    def _source_shape(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "source_type": row.get("source_type") or "",
            "source_id": row.get("source_id") or "",
            "source_key": row.get("source_key") or "",
            "title": row.get("title") or "",
            "content": row.get("content") or "",
            "summary": row.get("summary"),
            "source_url": row.get("source_url"),
            "country": row.get("country"),
            "tags": row.get("tags") or [],
            "image_urls": row.get("image_urls") or [],
            "likes_count": row.get("likes_count"),
            "saves_count": row.get("saves_count"),
            "comments_count": row.get("comments_count"),
            "views_count": row.get("views_count"),
            "similarity": row.get("similarity"),
            "rrf_score": row.get("rrf_score"),
        }
