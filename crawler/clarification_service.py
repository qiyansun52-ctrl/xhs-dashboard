from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional


COUNTRIES = ("英国", "新加坡", "澳洲", "美国", "加拿大", "香港")

CONTENT_SCENE_OPTIONS = [
    {"id": "life", "label": "生活类"},
    {"id": "application", "label": "申请类"},
    {"id": "academic", "label": "作业论文考试类"},
    {"id": "housing", "label": "住宿租房"},
    {"id": "campus", "label": "校园日常"},
    {"id": "career", "label": "就业实习"},
    {"id": "saving", "label": "省钱攻略"},
    {"id": "safety", "label": "安全避坑"},
]

EXPRESSION_TYPE_OPTIONS = [
    {"id": "experience", "label": "经验型"},
    {"id": "complaint", "label": "吐槽型"},
    {"id": "guide", "label": "干货攻略"},
    {"id": "warning", "label": "避坑警示"},
    {"id": "emotion", "label": "情绪共鸣"},
    {"id": "contrast", "label": "对比反差"},
    {"id": "story", "label": "故事叙事"},
]

QUALITY_OPTIONS = [
    {"id": "high_save", "label": "高收藏"},
    {"id": "high_comment", "label": "高评论"},
    {"id": "real_person", "label": "真人经历"},
    {"id": "strong_hook", "label": "标题强钩子"},
    {"id": "comment_pain", "label": "评论区有痛点"},
]

EXCLUSION_OPTIONS = [
    {"id": "agency_ads", "label": "机构广告"},
    {"id": "low_quality", "label": "低质搬运"},
    {"id": "marketing", "label": "纯营销"},
    {"id": "no_real_story", "label": "无真人经验"},
    {"id": "generic_tags", "label": "太泛 hashtag"},
    {"id": "duplicates", "label": "重复旧素材"},
]


class ClarificationService:
    def __init__(
        self,
        structured_completion: Optional[Callable[..., Dict[str, Any]]] = None,
        text_model: Optional[str] = None,
    ):
        self.structured_completion = structured_completion
        self.text_model = (text_model or "").strip()
        if self.structured_completion and not self.text_model:
            raise ValueError("text_model is required when structured_completion is configured")

    async def clarify_request(self, question: str, messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if self.structured_completion:
            try:
                payload = await asyncio.to_thread(self._call_clarification_llm, question, messages or [])
                if self._valid_clarification_payload(payload):
                    return payload
            except Exception:
                pass
        return self._fallback_clarification(question)

    async def build_crawler_brief(
        self,
        original_request: str,
        selections: Dict[str, List[str]],
        free_text: str = "",
    ) -> Dict[str, Any]:
        country = self._detect_country(original_request)
        content_scenes = self._labels_for(selections.get("content_scene") or [], CONTENT_SCENE_OPTIONS)
        expression_types = self._labels_for(selections.get("expression_type") or [], EXPRESSION_TYPE_OPTIONS)
        quality_targets = (
            self._labels_for(selections.get("quality_target") or [], QUALITY_OPTIONS)
            or ["高收藏", "真人经历", "评论区有痛点"]
        )
        exclusions = self._labels_for(selections.get("exclusion") or [], EXCLUSION_OPTIONS)
        if "机构广告" not in exclusions and ("不要机构" in free_text or "机构广告" in free_text):
            exclusions.append("机构广告")
        if "低质搬运" not in exclusions and "搬运" in free_text:
            exclusions.append("低质搬运")
        if not content_scenes:
            content_scenes = ["生活类"]
        if not expression_types:
            expression_types = ["经验型"]
        search_queries = self._build_queries(country, content_scenes, expression_types, free_text)
        return {
            "needs_clarification": False,
            "crawler_brief": {
                "goal": f"寻找{country}留学{content_scenes[0]}素材，偏{'、'.join(expression_types)}",
                "country": country,
                "audiences": self._infer_audiences(free_text),
                "content_scenes": content_scenes,
                "expression_types": expression_types,
                "quality_targets": quality_targets,
                "exclusions": exclusions or ["机构广告", "低质搬运", "重复旧素材"],
                "search_queries": search_queries,
                "candidate_scoring_hint": "优先高收藏/高评论/真人叙事，降低机构口吻、空标题、泛 hashtag 和重复素材分数",
                "free_text": free_text,
            },
        }

    def _call_clarification_llm(self, question: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        schema = self._clarification_schema()
        prompt = {
            "question": question,
            "recent_messages": messages[-8:],
            "rules": [
                "如果请求很泛，返回 needs_clarification=true 和 2 到 4 个 option_groups。",
                "如果请求已经足够具体，返回 needs_clarification=false，并填写 crawler_brief。",
                "只询问能提高小红书爬虫精准度的信息。",
                "选项必须来自内容场景、表达类型、质量目标、排除项。",
                "needs_clarification=true 时 crawler_brief 必须为 null。",
                "中文输出。",
            ],
        }
        return self.structured_completion(
            model=self.text_model,
            system_message="你是小红书留学素材爬虫的 brief 规划员。",
            user_content=json.dumps(prompt, ensure_ascii=False),
            schema_name="crawler_clarification",
            schema=schema,
        )

    def _fallback_clarification(self, question: str) -> Dict[str, Any]:
        country = self._detect_country(question)
        return {
            "needs_clarification": True,
            "detected_country": country,
            "question": f"你想优先找{country}留学的哪个方向？",
            "option_groups": [
                {"id": "content_scene", "label": "内容场景", "max_select": 2, "options": CONTENT_SCENE_OPTIONS[:6]},
                {"id": "expression_type", "label": "表达类型", "max_select": 2, "options": EXPRESSION_TYPE_OPTIONS[:5]},
                {"id": "quality_target", "label": "质量目标", "max_select": 3, "options": QUALITY_OPTIONS},
                {"id": "exclusion", "label": "排除项", "max_select": 3, "options": EXCLUSION_OPTIONS},
            ],
            "free_text_prompt": "你也可以补充：不要什么、偏什么风格、给哪个账号用。",
        }

    def _detect_country(self, text: str) -> str:
        for country in COUNTRIES:
            if country in text:
                return country
        return "英国"

    def _labels_for(self, ids: List[str], options: List[Dict[str, str]]) -> List[str]:
        labels = {item["id"]: item["label"] for item in options}
        return [labels[item_id] for item_id in ids if item_id in labels]

    def _infer_audiences(self, free_text: str) -> List[str]:
        audiences = []
        for label in ("高中生", "本科", "研究生", "家长", "工作后留学", "新留子"):
            if label in free_text:
                audiences.append(label)
        return audiences or ["本科", "研究生", "新留子"]

    def _build_queries(self, country: str, scenes: List[str], expression_types: List[str], free_text: str) -> List[str]:
        scene_terms = {
            "生活类": "生活",
            "申请类": "申请",
            "作业论文考试类": "论文 考试",
            "住宿租房": "租房",
            "校园日常": "校园 日常",
            "就业实习": "就业 实习",
        }
        expression_terms = {
            "经验型": "真实经验",
            "吐槽型": "吐槽",
            "干货攻略": "攻略",
            "避坑警示": "避坑",
            "情绪共鸣": "日常",
        }
        primary_scene = scene_terms.get(scenes[0], scenes[0])
        primary_expression = expression_terms.get(expression_types[0], expression_types[0])
        queries = [
            f"{country}留学 {primary_scene} {primary_expression}",
            f"{country}留学生 {primary_scene} 小红书",
            f"{country}留学 {primary_scene} 避坑",
        ]
        for scene in scenes[1:]:
            scene_term = scene_terms.get(scene, scene)
            query = f"{country}留学 {scene_term} {primary_expression}"
            if query not in queries:
                queries.append(query)
        if len(expression_types) > 1:
            queries.append(f"{country}留学生 {expression_terms.get(expression_types[1], expression_types[1])}")
        if "租房" in free_text and f"{country}留学 租房 经验" not in queries:
            queries.append(f"{country}留学 租房 经验")
        return queries[:4]

    def _valid_clarification_payload(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict) or not isinstance(payload.get("needs_clarification"), bool):
            return False
        if payload.get("needs_clarification"):
            return isinstance(payload.get("option_groups"), list)
        return self._valid_crawler_brief(payload.get("crawler_brief"))

    def _valid_crawler_brief(self, crawler_brief: Any) -> bool:
        return (
            isinstance(crawler_brief, dict)
            and isinstance(crawler_brief.get("goal"), str)
            and isinstance(crawler_brief.get("country"), str)
            and isinstance(crawler_brief.get("search_queries"), list)
            and any(str(query).strip() for query in crawler_brief.get("search_queries") or [])
        )

    def _clarification_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "needs_clarification": {"type": "boolean"},
                "detected_country": {"type": "string"},
                "question": {"type": "string"},
                "option_groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "max_select": {"type": "integer"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "id": {"type": "string"},
                                        "label": {"type": "string"},
                                    },
                                    "required": ["id", "label"],
                                },
                            },
                        },
                        "required": ["id", "label", "max_select", "options"],
                    },
                },
                "free_text_prompt": {"type": "string"},
                "crawler_brief": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "goal": {"type": "string"},
                        "country": {"type": "string"},
                        "audiences": {"type": "array", "items": {"type": "string"}},
                        "content_scenes": {"type": "array", "items": {"type": "string"}},
                        "expression_types": {"type": "array", "items": {"type": "string"}},
                        "quality_targets": {"type": "array", "items": {"type": "string"}},
                        "exclusions": {"type": "array", "items": {"type": "string"}},
                        "search_queries": {"type": "array", "items": {"type": "string"}},
                        "candidate_scoring_hint": {"type": "string"},
                    },
                    "required": [
                        "goal",
                        "country",
                        "audiences",
                        "content_scenes",
                        "expression_types",
                        "quality_targets",
                        "exclusions",
                        "search_queries",
                        "candidate_scoring_hint",
                    ],
                },
            },
            "required": [
                "needs_clarification",
                "detected_country",
                "question",
                "option_groups",
                "free_text_prompt",
                "crawler_brief",
            ],
        }
