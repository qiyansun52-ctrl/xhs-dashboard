from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TaskType = Literal["material", "experience", "image_reference", "mixed"]
EvidenceQuality = Literal["empty", "weak", "strong"]


class ImageAnalysis(BaseModel):
    subject: str = ""
    scene: str = ""
    mood: str = ""
    visual_style: str = ""
    content_direction: str = ""
    keywords: List[str] = Field(default_factory=list)
    description: str = ""


class KnowledgeSource(BaseModel):
    id: str
    source_type: str
    source_id: str
    source_key: str
    title: str = ""
    content: str = ""
    summary: Optional[str] = None
    source_url: Optional[str] = None
    country: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    image_urls: List[str] = Field(default_factory=list)
    likes_count: Optional[int] = None
    saves_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    similarity: Optional[float] = None
    rrf_score: Optional[float] = None


class Recommendation(BaseModel):
    text: str
    source_ids: List[str] = Field(default_factory=list)


class GeneralAdvice(BaseModel):
    text: str
    reason: str


class ExternalRecommendation(BaseModel):
    text: str
    candidate_ids: List[str] = Field(default_factory=list)


class ExternalSupplementAnswer(BaseModel):
    job_id: str
    conclusion: str
    recommendations: List[ExternalRecommendation] = Field(default_factory=list)
    candidate_references: List[str] = Field(default_factory=list)
    general_advice: List[GeneralAdvice] = Field(default_factory=list)
    warning: str = "以下内容来自待审核外部素材，尚未进入团队知识库。"


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    image_url: Optional[str] = None
    previous_answer_summary: Optional[str] = None
    previous_citation_ids: List[str] = Field(default_factory=list)


class ResearchAnswer(BaseModel):
    question: str
    task_type: TaskType
    conclusion: str
    recommendations: List[Recommendation] = Field(default_factory=list)
    material_references: List[str] = Field(default_factory=list)
    team_history_references: List[str] = Field(default_factory=list)
    related_sources: List[KnowledgeSource] = Field(default_factory=list)
    cited_sources: List[KnowledgeSource] = Field(default_factory=list)
    image_analysis: Optional[ImageAnalysis] = None
    general_advice: List[GeneralAdvice] = Field(default_factory=list)
    sparse: bool = False
    can_external_discover: bool = False
    discovery_trigger_reason: Optional[str] = None
    suggested_search_queries: List[str] = Field(default_factory=list)
    discovery_trigger_mode: Optional[str] = None
    discovery_job_id: Optional[str] = None
    evidence_quality: EvidenceQuality = "strong"
    trace_id: Optional[str] = None
    retrieval_debug: Optional[Dict] = None
    message: Optional[str] = None
