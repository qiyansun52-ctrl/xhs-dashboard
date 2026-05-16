from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from research_models import ExternalSupplementAnswer, ImageAnalysis, KnowledgeSource, ResearchAnswer, ResearchRequest
from discovery import derive_search_queries, validate_external_candidate_ids
from retrieval import (
    detect_task_type,
    rrf_merge,
    tokenize_query,
    validate_citations,
)
from retrieval_pipeline import (
    classify_sparse,
    filter_candidates,
    parse_query_fallback,
    profile_for_intent,
    select_evidence,
)
from research_trace import write_research_trace

try:
    import config as app_config
except Exception:
    app_config = None


def _config_value(name: str, default: Any) -> Any:
    return getattr(app_config, name, default) if app_config else default


OPENAI_API_KEY = _config_value("OPENAI_API_KEY", "")
OPENAI_TEXT_MODEL = _config_value("OPENAI_TEXT_MODEL", "gpt-4.1-mini")
OPENAI_VISION_MODEL = _config_value("OPENAI_VISION_MODEL", "gpt-4.1-mini")
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"
AI_RESEARCH_MIN_RESULTS = _config_value("AI_RESEARCH_MIN_RESULTS", 3)
AI_RESEARCH_MIN_SIMILARITY = _config_value("AI_RESEARCH_MIN_SIMILARITY", 0.55)
EXTERNAL_DISCOVERY_ENABLED = _config_value("EXTERNAL_DISCOVERY_ENABLED", False)
EXTERNAL_DISCOVERY_TRIGGER_MODE = _config_value("EXTERNAL_DISCOVERY_TRIGGER_MODE", "ask_first")
EXTERNAL_DISCOVERY_MAX_QUERIES = _config_value("EXTERNAL_DISCOVERY_MAX_QUERIES", 4)

GENERIC_QUERY_TOKENS = {
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

GENERIC_QUERY_PHRASES = (
    "帮我找一下",
    "帮我",
    "找一下",
    "有关于",
    "有没有",
    "有关",
    "关于",
    "标题素材",
    "标题",
    "素材",
    "内容",
    "方向",
    "参考",
    "相关",
    "一下",
    "的",
)

COUNTRY_QUERY_TOKENS = (
    "英国",
    "美国",
    "澳洲",
    "澳大利亚",
    "加拿大",
    "新加坡",
    "香港",
)

EVIDENCE_TOKEN_SYNONYMS = {
    "春天": ("春天", "春日", "春季", "spring", "樱花", "花瓣"),
    "夏天": ("夏天", "夏日", "夏季", "summer"),
    "秋天": ("秋天", "秋日", "秋季", "autumn", "fall"),
    "冬天": ("冬天", "冬日", "冬季", "winter"),
}


def model_to_dict(model) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    api_key: str
    base_url: Optional[str]
    text_model: str
    vision_model: str


def _read_config_or_env(config_obj: Any, env: Dict[str, str], name: str, default: str = "") -> str:
    value = getattr(config_obj, name, None) if config_obj else None
    if value is None or str(value).strip() == "":
        value = env.get(name, default)
    return str(value or "").strip()


def resolve_llm_settings(config_obj: Any = None, env: Optional[Dict[str, str]] = None) -> LlmSettings:
    config_obj = app_config if config_obj is None else config_obj
    env = os.environ if env is None else env

    provider = _read_config_or_env(config_obj, env, "LLM_PROVIDER", "auto").lower() or "auto"
    gemini_key = _read_config_or_env(config_obj, env, "GEMINI_API_KEY")
    openai_key = _read_config_or_env(config_obj, env, "OPENAI_API_KEY", OPENAI_API_KEY)

    if provider == "auto":
        provider = "gemini" if gemini_key else "openai"
    if provider not in ("gemini", "openai"):
        provider = "openai"

    if provider == "gemini":
        return LlmSettings(
            provider="gemini",
            api_key=gemini_key,
            base_url=_read_config_or_env(config_obj, env, "GEMINI_BASE_URL", DEFAULT_GEMINI_BASE_URL) or DEFAULT_GEMINI_BASE_URL,
            text_model=_read_config_or_env(config_obj, env, "GEMINI_TEXT_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL,
            vision_model=_read_config_or_env(config_obj, env, "GEMINI_VISION_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL,
        )

    return LlmSettings(
        provider="openai",
        api_key=openai_key,
        base_url=_read_config_or_env(config_obj, env, "OPENAI_BASE_URL") or None,
        text_model=_read_config_or_env(config_obj, env, "OPENAI_TEXT_MODEL", OPENAI_TEXT_MODEL) or OPENAI_TEXT_MODEL,
        vision_model=_read_config_or_env(config_obj, env, "OPENAI_VISION_MODEL", OPENAI_VISION_MODEL) or OPENAI_VISION_MODEL,
    )


class ResearchService:
    def __init__(self, supabase_client, embed_texts):
        self.sb = supabase_client
        self.embed_texts = embed_texts
        self.llm_settings = resolve_llm_settings()
        self.llm_provider = self.llm_settings.provider
        self.text_model = self.llm_settings.text_model
        self.vision_model = self.llm_settings.vision_model
        self.openai_key = self.llm_settings.api_key
        self.openai = self._create_openai_compatible_client()

    def _create_openai_compatible_client(self):
        if not self.openai_key or not OpenAI:
            return None
        kwargs = {"api_key": self.openai_key}
        if self.llm_settings.base_url:
            kwargs["base_url"] = self.llm_settings.base_url
        return OpenAI(**kwargs)

    def _chat_json_response_format(self, name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": schema,
            },
        }

    def _extract_chat_content(self, resp: Any) -> str:
        message = resp.choices[0].message
        content = getattr(message, "content", "")
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content or "{}"

    def _create_structured_chat_completion(
        self,
        *,
        model: str,
        system_message: Optional[str],
        user_content: Any,
        schema_name: str,
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": user_content})
        resp = self.openai.chat.completions.create(
            model=model,
            messages=messages,
            response_format=self._chat_json_response_format(schema_name, schema),
        )
        return json.loads(self._extract_chat_content(resp))

    async def research(self, req: ResearchRequest) -> ResearchAnswer:
        task_type = detect_task_type(req.question, has_image=bool(req.image_url))
        intent_payload = parse_query_fallback(req.question, has_image=bool(req.image_url))
        profile = profile_for_intent(intent_payload.intent)
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
        retrieved_rows = await self._retrieve_for_research(
            query=query,
            task_type=task_type,
            intent_payload=intent_payload,
        )
        filtered = filter_candidates([retrieved_rows], profile)
        selected = select_evidence(filtered.rows, profile)
        evidence_quality = classify_sparse(selected.rows, profile)
        sparse = evidence_quality != "strong"

        if evidence_quality == "empty":
            messages.append("知识库没有匹配内容，建议先创建外部发现任务或补充素材入库。")
            answer_payload = self.generate_fallback_answer(
                req.question,
                task_type,
                selected.rows,
                True,
                image_analysis,
            )
        else:
            if evidence_quality == "weak":
                messages.append("内部资料匹配较少，仅基于筛选后的少量证据回答，建议继续外部发现补充。")

            try:
                answer_payload = await self.generate_answer(
                    question=req.question,
                    task_type=task_type,
                    rows=selected.rows,
                    sparse=sparse,
                    image_analysis=image_analysis,
                )
            except Exception:
                answer_payload = self.generate_fallback_answer(
                    req.question,
                    task_type,
                    selected.rows,
                    sparse,
                    image_analysis,
                )

        selected_ids = {str(row["id"]) for row in selected.rows}
        validated = validate_citations(answer_payload, retrieved_ids=selected_ids)
        sources = [KnowledgeSource(**self._source_shape(row)) for row in selected.rows]
        recommended_ids: List[str] = []
        for recommendation in validated.get("recommendations", []) or []:
            for source_id in recommendation.get("source_ids") or []:
                source_id = str(source_id)
                if source_id not in recommended_ids:
                    recommended_ids.append(source_id)

        if recommended_ids:
            cited_ids = set(recommended_ids)
            material_references = self._reference_ids_for_types(
                retrieved_rows,
                cited_ids,
                {"viral_post", "benchmark_post", "topic", "title"},
            )
            team_history_references = self._reference_ids_for_types(
                retrieved_rows,
                cited_ids,
                {"team_post"},
            )
        else:
            material_references = validated.get("material_references", []) or []
            team_history_references = validated.get("team_history_references", []) or []
            cited_ids = set(material_references + team_history_references)

        cited_sources = [source for source in sources if source.id in cited_ids]
        related_sources = [
            KnowledgeSource(**self._source_shape(row))
            for row in self._related_source_rows(req.question, filtered.rows, cited_ids)
        ]
        weak_titles = [
            str(row.get("title") or "")
            for row in (selected.rows or filtered.rows or retrieved_rows)[:5]
            if row.get("title")
        ]
        can_external_discover = bool(sparse and EXTERNAL_DISCOVERY_ENABLED)
        suggested_search_queries = derive_search_queries(
            req.question,
            image_keywords=image_analysis.keywords if image_analysis else [],
            weak_titles=weak_titles,
            max_queries=EXTERNAL_DISCOVERY_MAX_QUERIES,
        ) if can_external_discover else []
        discovery_trigger_reason = (
            ("zero_recall" if evidence_quality == "empty" else "sparse_recall")
            if can_external_discover
            else None
        )
        trace_payload = {
            "user_question": req.question,
            "intent": intent_payload.intent,
            "retrieval_profile": profile.name,
            "parser_payload": asdict(intent_payload),
            "route_counts": {
                "retrieved": len(retrieved_rows),
                "filtered": len(filtered.rows),
                "selected": len(selected.rows),
            },
            "top_candidates": [
                {
                    "id": str(row.get("id")),
                    "source_type": row.get("source_type"),
                    "title": row.get("title"),
                    "similarity": row.get("similarity"),
                    "rrf_score": row.get("rrf_score"),
                }
                for row in filtered.rows[:10]
            ],
            "selected_evidence_ids": [str(row["id"]) for row in selected.rows],
            "dropped_counts": filtered.dropped_counts,
            "evidence_quality": evidence_quality,
            "generation_allowed": evidence_quality != "empty",
            "answer_payload": validated,
        }
        trace_id = write_research_trace(self.sb, trace_payload)

        return ResearchAnswer(
            question=req.question,
            task_type=task_type,
            conclusion=validated["conclusion"],
            recommendations=validated.get("recommendations", []),
            material_references=material_references,
            team_history_references=team_history_references,
            related_sources=related_sources,
            cited_sources=cited_sources,
            image_analysis=image_analysis,
            general_advice=validated.get("general_advice", []),
            sparse=sparse,
            can_external_discover=can_external_discover,
            discovery_trigger_reason=discovery_trigger_reason,
            suggested_search_queries=suggested_search_queries,
            discovery_trigger_mode=EXTERNAL_DISCOVERY_TRIGGER_MODE if can_external_discover else None,
            discovery_job_id=None,
            evidence_quality=evidence_quality,
            trace_id=trace_id,
            selected_source_ids=[str(row["id"]) for row in selected.rows],
            retrieval_debug={
                "intent": intent_payload.intent,
                "profile": profile.name,
                "candidate_count": filtered.candidate_count,
                "filtered_count": filtered.filtered_count,
                "selected_count": len(selected.rows),
                "dropped_counts": filtered.dropped_counts,
                "top_similarity": filtered.top_similarity,
                "overflow_ids": selected.overflow_ids,
            },
            message=" ".join(messages) if messages else None,
        )

    async def _retrieve_for_research(
        self,
        query: str,
        task_type: str,
        intent_payload=None,
    ) -> List[Dict[str, Any]]:
        try:
            return await self.retrieve(query=query, task_type=task_type, intent_payload=intent_payload)
        except TypeError as exc:
            if "intent_payload" in str(exc) or "unexpected keyword" in str(exc):
                return await self.retrieve(query=query, task_type=task_type)
            raise

    async def retrieve(self, query: str, task_type: str, intent_payload=None) -> List[Dict[str, Any]]:
        if intent_payload is None:
            intent_payload = parse_query_fallback(query, has_image=task_type == "image_reference")
        profile = profile_for_intent(intent_payload.intent)
        embeds = await self.embed_texts([query], input_type="query")
        source_types = intent_payload.filters.source_type_preference or self._source_types_for_task(task_type)
        rpc_params = {
            "query_embedding": embeds[0],
            "match_count": profile.vector_match_count,
            "source_types": source_types,
            "country_filter": intent_payload.filters.country,
            "min_similarity": profile.absolute_floor,
        }
        try:
            vector_res = self.sb.rpc("match_knowledge_items", rpc_params).execute()
        except Exception as exc:
            if not self._should_retry_without_min_similarity(exc):
                raise
            fallback_params = dict(rpc_params)
            fallback_params.pop("min_similarity", None)
            vector_res = self.sb.rpc("match_knowledge_items", fallback_params).execute()
        vector_rows = vector_res.data or []

        keyword_rows = self.keyword_candidates(query, source_types=source_types)
        merged = self._rerank_for_task(rrf_merge([vector_rows, keyword_rows]), task_type)
        filtered = filter_candidates([merged], profile)
        return filtered.rows[:20]

    def _should_retry_without_min_similarity(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "min_similarity" in message
            or ("match_knowledge_items" in message and "does not exist" in message)
            or ("schema cache" in message and "match_knowledge_items" in message)
        )

    def keyword_candidates(self, query: str, source_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        tokens = self._keyword_tokens(query)
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

    def _keyword_tokens(self, query: str) -> List[str]:
        cleaned = str(query or "")
        for phrase in GENERIC_QUERY_PHRASES:
            cleaned = cleaned.replace(phrase, " ")

        tokens = []
        for token in tokenize_query(cleaned):
            if token in GENERIC_QUERY_TOKENS or len(token) < 2:
                continue
            if token not in tokens:
                tokens.append(token)
        return tokens

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
                return self._create_structured_chat_completion(
                    model=self.vision_model,
                    system_message=None,
                    user_content=[
                        {"type": "text", "text": "请分析这张小红书配图，输出可用于留学内容选题检索的结构化 JSON。"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                    schema_name="image_analysis",
                    schema=schema,
                )

            payload = await asyncio.to_thread(_call)
            return ImageAnalysis(**payload)

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
            return self._create_structured_chat_completion(
                model=self.text_model,
                system_message="你是小红书留学内容团队的 AI 素材研究员。你必须输出符合 schema 的 JSON，且不得编造 allowed_sources 之外的素材。",
                user_content=json.dumps(prompt, ensure_ascii=False),
                schema_name="research_answer",
                schema=schema,
            )

        return await asyncio.to_thread(_call)

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

        top = self._top_evidence_rows(question, rows, max_count=3)
        recommendations = [
            {"text": f"优先参考《{row.get('title') or '无标题'}》的内容角度。", "source_ids": [str(row["id"])]}
            for row in top
        ]
        return {
            "conclusion": "根据当前知识库，下面这些素材和历史内容与问题最相关。" if not sparse else "内部资料匹配较少，可以先参考少量匹配内容，再结合通用创作判断。",
            "recommendations": recommendations,
            "material_references": [
                str(row["id"])
                for row in top
                if row.get("source_type") in ("viral_post", "benchmark_post", "topic", "title")
            ],
            "team_history_references": [
                str(row["id"])
                for row in top
                if row.get("source_type") == "team_post"
            ],
            "image_analysis": model_to_dict(image_analysis) if image_analysis else None,
            "general_advice": [{"text": "可用情绪共鸣开头，再给出具体步骤。", "reason": "internal evidence was sparse"}] if sparse else [],
        }

    async def generate_external_supplement(
        self,
        job_id: str,
        question: str,
        candidates: List[Dict[str, Any]],
    ) -> ExternalSupplementAnswer:
        allowed_ids = {str(candidate.get("id")) for candidate in candidates if candidate.get("id")}
        if not candidates:
            return ExternalSupplementAnswer(
                job_id=job_id,
                conclusion="本次外部发现没有找到可用候选素材。",
            )

        if not self.openai:
            top = candidates[:3]
            recommendations = [
                {
                    "text": f"外部候选《{candidate.get('title') or candidate.get('account_name') or '未命名素材'}》可作为补充参考，建议人工审核后再纳入团队知识库。",
                    "candidate_ids": [str(candidate["id"])],
                }
                for candidate in top
                if candidate.get("id")
            ]
            candidate_references = [str(candidate["id"]) for candidate in top if candidate.get("id")]
            return ExternalSupplementAnswer(
                job_id=job_id,
                conclusion="根据本次外部发现，以下待审核候选素材可作为内部回答的补充参考。",
                recommendations=recommendations,
                candidate_references=candidate_references,
            )

        source_context = [
            {
                "id": str(candidate.get("id")),
                "title": candidate.get("title") or candidate.get("account_name") or "",
                "caption": (candidate.get("caption") or candidate.get("ai_reason") or "")[:800],
                "author_name": candidate.get("author_name"),
                "platform": candidate.get("platform"),
                "url": candidate.get("url"),
                "likes": candidate.get("likes"),
                "saves": candidate.get("saves"),
                "comments": candidate.get("comments"),
                "candidate_score": candidate.get("candidate_score"),
            }
            for candidate in candidates[:12]
            if candidate.get("id")
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
                            "candidate_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["text", "candidate_ids"],
                    },
                },
                "candidate_references": {"type": "array", "items": {"type": "string"}},
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
            "required": ["conclusion", "recommendations", "candidate_references", "general_advice"],
        }
        prompt = {
            "job_id": job_id,
            "question": question,
            "allowed_candidates": source_context,
            "rules": [
                "只能引用 allowed_candidates 中存在的 id；candidate_ids 和 candidate_references 必须严格匹配 allowed_candidates 的 id。",
                "所有基于外部素材的 recommendation 都必须带至少一个 candidate_ids。",
                "没有候选素材支持的建议必须放进 general_advice，并写明 reason。",
                "明确提醒这些内容来自待审核外部素材，尚未进入团队知识库。",
                "回答要面向小红书留学内容运营，中文输出。",
            ],
        }

        def _call():
            return self._create_structured_chat_completion(
                model=self.text_model,
                system_message="你是小红书留学内容团队的 AI 外部素材研究员。你必须输出符合 schema 的 JSON，且不得编造 allowed_candidates 之外的素材。",
                user_content=json.dumps(prompt, ensure_ascii=False),
                schema_name="external_supplement_answer",
                schema=schema,
            )

        payload = await asyncio.to_thread(_call)
        validated = validate_external_candidate_ids(payload, allowed_candidate_ids=allowed_ids)
        return ExternalSupplementAnswer(
            job_id=job_id,
            conclusion=validated.get("conclusion") or "外部候选素材已整理完成，请先人工审核后再使用。",
            recommendations=validated.get("recommendations", []),
            candidate_references=validated.get("candidate_references", []),
            general_advice=validated.get("general_advice", []),
        )

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

    def _reference_ids_for_types(
        self,
        rows: List[Dict[str, Any]],
        cited_ids: set,
        source_types: set,
    ) -> List[str]:
        return [
            str(row["id"])
            for row in rows
            if str(row.get("id")) in cited_ids and row.get("source_type") in source_types
        ]

    def _top_evidence_rows(
        self,
        question: str,
        rows: List[Dict[str, Any]],
        max_count: int = 3,
    ) -> List[Dict[str, Any]]:
        evidence_tokens = self._evidence_tokens(question)
        if not evidence_tokens:
            return rows[:max_count]

        scored = self._score_evidence_rows(evidence_tokens, rows)
        if not scored:
            return rows[:max_count]

        return [row for _, _, row in scored[:max_count]]

    def _related_source_rows(
        self,
        question: str,
        rows: List[Dict[str, Any]],
        cited_ids: set,
        max_count: int = 4,
    ) -> List[Dict[str, Any]]:
        remaining = [
            row for row in rows
            if str(row.get("id")) not in cited_ids
        ]
        evidence_tokens = self._evidence_tokens(question)
        if not evidence_tokens:
            return remaining[:max_count]

        return [row for _, _, row in self._score_evidence_rows(evidence_tokens, remaining)[:max_count]]

    def _score_evidence_rows(
        self,
        evidence_tokens: List[str],
        rows: List[Dict[str, Any]],
    ) -> List[tuple]:
        scored = []
        for index, row in enumerate(rows):
            title = str(row.get("title") or "").lower()
            content = str(row.get("content") or "").lower()
            score = 0
            for token in evidence_tokens:
                variants = EVIDENCE_TOKEN_SYNONYMS.get(token, (token,))
                for variant in variants:
                    normalized = variant.lower()
                    if normalized in title:
                        score += 3
                    elif normalized in content:
                        score += 1
            if score:
                scored.append((score, index, row))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored

    def _evidence_tokens(self, question: str) -> List[str]:
        cleaned = str(question or "").lower()
        for phrase in GENERIC_QUERY_PHRASES:
            cleaned = cleaned.replace(phrase, " ")

        country_tokens = [token for token in COUNTRY_QUERY_TOKENS if token in cleaned]
        topic_text = cleaned
        for token in country_tokens:
            topic_text = topic_text.replace(token, " ")

        topic_tokens = self._clean_evidence_tokens(tokenize_query(topic_text, max_tokens=16))
        if topic_tokens:
            return topic_tokens
        if country_tokens:
            return country_tokens
        return self._clean_evidence_tokens(tokenize_query(cleaned, max_tokens=16))

    def _clean_evidence_tokens(self, tokens: List[str]) -> List[str]:
        cleaned: List[str] = []
        for token in tokens:
            if token in GENERIC_QUERY_TOKENS or len(token) < 2:
                continue
            if token not in cleaned:
                cleaned.append(token)
        return cleaned

    def _source_shape(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "source_type": row.get("source_type") or "",
            "source_id": row.get("source_id") or "",
            "source_key": row.get("source_key") or "",
            "title": row.get("title") or "",
            "content": row.get("content") or "",
            "summary": row.get("summary"),
            "source_url": self._normalize_source_url(row),
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

    def _normalize_source_url(self, row: Dict[str, Any]) -> Optional[str]:
        raw_url = str(row.get("source_url") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        source_type = row.get("source_type")

        if not raw_url and source_type in ("viral_post", "benchmark_post") and source_id:
            return f"https://www.xiaohongshu.com/explore/{source_id}"
        if not raw_url:
            return None

        parsed = urlsplit(raw_url)
        if not parsed.scheme and raw_url.startswith("www."):
            parsed = urlsplit(f"https://{raw_url}")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None

        host = parsed.netloc.lower()
        if host.endswith("xiaohongshu.com") and parsed.path.startswith("/explore/"):
            note_id = parsed.path.split("/explore/", 1)[1].split("/", 1)[0]
            if note_id:
                return f"https://www.xiaohongshu.com/explore/{note_id}"

        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
