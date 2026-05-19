#!/usr/bin/env python3
"""
XHS Dashboard AI API 服务

功能：
  - 爆款帖子语义检索（POST /ai/search-viral）
  - 后台 worker 自动给新爆款做 embedding（lifespan task）
  - 健康检查 / 调试端点

启动：
  cd crawler
  python ai_api.py
  # 或
  uvicorn ai_api:app --host 127.0.0.1 --port 8001 --reload

后续 Phase 2/3 在本文件继续添加端点（看图写文案 / 发布前 QA）。
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Literal

# ── 路径配置（让 from config import 能找到 crawler/config.py）──
CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CRAWLER_DIR)

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client
import voyageai
from agent import AgentEventBus, AgentOrchestrator, AgentRunStore, ContentResearchSkill, PlanEngine, ToolInvoker
from agent.conversation_store import ConversationStore
from clarification_service import ClarificationService
from discovery import derive_search_queries, derive_search_queries_from_brief
from discovery_service import DiscoveryNotFoundError, DiscoveryService
from research_models import ResearchRequest
from research_service import ResearchService

import config as app_config  # noqa: E402

SUPABASE_URL = app_config.SUPABASE_URL
SUPABASE_KEY = app_config.SUPABASE_KEY
VOYAGE_API_KEY = getattr(app_config, "VOYAGE_API_KEY", os.getenv("VOYAGE_API_KEY", ""))
AI_API_KEY = getattr(app_config, "AI_API_KEY", os.getenv("AI_API_KEY", ""))
AI_API_HOST = getattr(app_config, "AI_API_HOST", os.getenv("AI_API_HOST", "127.0.0.1"))
AI_API_PORT = getattr(app_config, "AI_API_PORT", int(os.getenv("AI_API_PORT", "8001")))
AI_API_CORS_ORIGINS = getattr(app_config, "AI_API_CORS_ORIGINS", [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
])
AGENT_RUNTIME_ENABLED = str(
    getattr(app_config, "AGENT_RUNTIME_ENABLED", os.getenv("AGENT_RUNTIME_ENABLED", "true"))
).lower() not in ("0", "false", "no")

# ── 日志 ─────────────────────────────────────────────────────────
os.makedirs(os.path.join(CRAWLER_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ai-api] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(CRAWLER_DIR, "logs", "ai_api.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────
EMBED_MODEL = "voyage-3-lite"
EMBED_DIM = 512                # 启动时会校验，对不上会报错
EMBED_BATCH_SIZE = 32          # voyage 每批最多
WORKER_INTERVAL_SEC = 30       # worker 轮询间隔
MAX_EMBED_RETRY = 3            # 同一条最多重试次数
KNOWLEDGE_EMBED_BATCH_SIZE = 16
KNOWLEDGE_WORKER_INTERVAL_SEC = 30

# ── 客户端 ───────────────────────────────────────────────────────
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
vo: Optional[voyageai.Client] = None


def get_voyage_client() -> voyageai.Client:
    global vo
    if vo is None:
        if not VOYAGE_API_KEY:
            raise RuntimeError("未配置 VOYAGE_API_KEY，请在 crawler/config.py 或环境变量中设置。")
        vo = voyageai.Client(api_key=VOYAGE_API_KEY)
    return vo


# ────────────────────────────────────────────────────────────────
# Embedding 工具
# ────────────────────────────────────────────────────────────────

def build_embed_text(row: Dict[str, Any]) -> str:
    """把一行 viral_post 拼成单条 embedding 文本。"""
    parts: List[str] = []
    title = (row.get("title") or "").strip()
    caption = (row.get("caption") or "").strip()
    if title:
        parts.append(title)
    if caption:
        parts.append(caption)
    tags = row.get("tags") or []
    if tags:
        parts.append("标签：" + " ".join(t for t in tags if t))
    return "\n".join(parts).strip()


async def embed_texts(texts: List[str], input_type: str = "document") -> List[List[float]]:
    """异步包装 voyage SDK（SDK 是同步的，跑在线程池里避免阻塞事件循环）。

    input_type: "document" 用于入库，"query" 用于检索查询，效果更好。
    """
    def _call():
        client = get_voyage_client()
        return client.embed(texts, model=EMBED_MODEL, input_type=input_type).embeddings

    return await asyncio.to_thread(_call)


# ────────────────────────────────────────────────────────────────
# 后台 worker：批量给 pending 的 viral_posts 做 embedding
# ────────────────────────────────────────────────────────────────

async def embed_pending_batch() -> int:
    """处理一批 pending 记录，返回处理条数。"""
    res = (
        sb.table("viral_posts")
        .select("id, title, caption, tags, embed_retry_count")
        .eq("embed_status", "pending")
        .eq("fetch_status", "done")
        .lt("embed_retry_count", MAX_EMBED_RETRY)
        .limit(EMBED_BATCH_SIZE)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return 0

    log.info(f"准备处理 {len(rows)} 条 pending 记录")

    # 构造文本，过滤空内容
    valid_pairs: List[tuple] = []  # (row, text)
    for r in rows:
        text = build_embed_text(r)
        if text:
            valid_pairs.append((r, text))
        else:
            # 空内容，置 error
            sb.table("viral_posts").update({
                "embed_status": "error",
            }).eq("id", r["id"]).execute()
            log.warning(f"  ⚠️ id={r['id']} 内容为空，置 error")

    if not valid_pairs:
        return 0

    texts = [t for _, t in valid_pairs]

    try:
        embeddings = await embed_texts(texts, input_type="document")
    except Exception as e:
        # 整批失败，每条 retry +1
        log.error(f"voyage embed 整批失败: {e}")
        for r, _ in valid_pairs:
            new_count = (r.get("embed_retry_count") or 0) + 1
            update: Dict[str, Any] = {"embed_retry_count": new_count}
            if new_count >= MAX_EMBED_RETRY:
                update["embed_status"] = "error"
            sb.table("viral_posts").update(update).eq("id", r["id"]).execute()
        return 0

    # 写回成功结果
    for (r, _), emb in zip(valid_pairs, embeddings):
        sb.table("viral_posts").update({
            "embedding": emb,
            "embed_status": "done",
        }).eq("id", r["id"]).execute()

    log.info(f"  ✅ {len(valid_pairs)} 条 embedding 完成")
    return len(valid_pairs)


async def embed_worker_loop():
    """后台循环：定期处理 pending 队列。"""
    log.info(f"embedding worker 启动，每 {WORKER_INTERVAL_SEC}s 轮询")
    while True:
        try:
            await embed_pending_batch()
        except Exception as e:
            log.error(f"embed_pending_batch 出错: {e}")
        await asyncio.sleep(WORKER_INTERVAL_SEC)


def _build_knowledge_embed_text(row: Dict[str, Any]) -> str:
    parts = [(row.get("title") or "").strip(), (row.get("content") or "").strip()]
    return "\n".join(part for part in parts if part).strip()


async def embed_knowledge_pending_batch() -> int:
    res = (
        sb.table("knowledge_items")
        .select("id, title, content, retry_count")
        .eq("embed_status", "pending")
        .lt("retry_count", MAX_EMBED_RETRY)
        .limit(KNOWLEDGE_EMBED_BATCH_SIZE)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return 0

    valid_pairs: List[tuple] = []
    for row in rows:
        text = _build_knowledge_embed_text(row)
        if not text:
            sb.table("knowledge_items").update({
                "embed_status": "failed",
                "embed_error": "empty content",
            }).eq("id", row["id"]).execute()
            continue
        valid_pairs.append((row, text))

    if not valid_pairs:
        return 0

    for row, _ in valid_pairs:
        sb.table("knowledge_items").update({"embed_status": "processing"}).eq("id", row["id"]).execute()

    texts = [text for _, text in valid_pairs]
    try:
        embeddings = await embed_texts(texts, input_type="document")
    except Exception as e:
        log.error(f"knowledge embed 整批失败: {e}")
        for row, _ in valid_pairs:
            new_count = (row.get("retry_count") or 0) + 1
            update: Dict[str, Any] = {"retry_count": new_count, "embed_status": "pending"}
            if new_count >= MAX_EMBED_RETRY:
                update["embed_status"] = "failed"
                update["embed_error"] = str(e)[:500]
            sb.table("knowledge_items").update(update).eq("id", row["id"]).execute()
        return 0

    for (row, _), embedding in zip(valid_pairs, embeddings):
        sb.table("knowledge_items").update({
            "embedding": embedding,
            "embed_status": "completed",
            "embed_error": None,
        }).eq("id", row["id"]).execute()

    log.info(f"  ✅ knowledge_items {len(valid_pairs)} 条 embedding 完成")
    return len(valid_pairs)


async def knowledge_embed_worker_loop():
    log.info(f"knowledge embed worker 启动，每 {KNOWLEDGE_WORKER_INTERVAL_SEC}s 轮询")
    while True:
        try:
            await embed_knowledge_pending_batch()
        except Exception as e:
            log.error(f"embed_knowledge_pending_batch 出错: {e}")
        await asyncio.sleep(KNOWLEDGE_WORKER_INTERVAL_SEC)


# ────────────────────────────────────────────────────────────────
# FastAPI lifespan：启动校验 + 启动 worker
# ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 启动时校验 embedding 维度
    try:
        test = await embed_texts(["维度校验"], input_type="document")
    except Exception as e:
        log.error(f"voyage API 调用失败，请检查 VOYAGE_API_KEY: {e}")
        raise

    actual_dim = len(test[0])
    if actual_dim != EMBED_DIM:
        raise RuntimeError(
            f"模型 {EMBED_MODEL} 实际维度 {actual_dim} 与 EMBED_DIM={EMBED_DIM} 不匹配。"
            f"请同步修改 ai_api.py 中的 EMBED_DIM 和 ai_schema.sql 中的 vector(N)。"
        )
    log.info(f"✅ embedding 维度校验通过：{EMBED_MODEL} → {EMBED_DIM} 维")

    # 2. 启动后台 worker
    worker_task = asyncio.create_task(embed_worker_loop())
    knowledge_worker_task = asyncio.create_task(knowledge_embed_worker_loop())

    yield

    # 3. 关闭时清理
    for task in (worker_task, knowledge_worker_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("ai-api 已关闭")


# ────────────────────────────────────────────────────────────────
# FastAPI app
# ────────────────────────────────────────────────────────────────

app = FastAPI(title="XHS Dashboard AI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=AI_API_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

research_service = ResearchService(sb, embed_texts)
conversation_store = ConversationStore(sb)
clarification_service = ClarificationService(
    structured_completion=research_service._create_structured_chat_completion,
    text_model=research_service.text_model,
)
discovery_service = DiscoveryService(
    sb,
    max_queries=getattr(app_config, "EXTERNAL_DISCOVERY_MAX_QUERIES", 4),
)
agent_run_store = AgentRunStore(sb)
agent_event_bus = AgentEventBus()
agent_tool_invoker = ToolInvoker(agent_run_store)
agent_plan_engine = PlanEngine(agent_run_store)


async def run_agent_research(payload: Dict[str, Any]) -> Dict[str, Any]:
    answer = await research_service.research(ResearchRequest(
        question=payload.get("question") or "",
        image_url=payload.get("image_url"),
    ))
    if hasattr(answer, "model_dump"):
        return answer.model_dump()
    return answer.dict()


agent_orchestrator = AgentOrchestrator(
    run_store=agent_run_store,
    event_bus=agent_event_bus,
    tool_invoker=agent_tool_invoker,
    planner=agent_plan_engine,
    skills={
        ContentResearchSkill.name: ContentResearchSkill(run_agent_research),
    },
)


def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if not AI_API_KEY or x_api_key != AI_API_KEY:
        raise HTTPException(status_code=401, detail="无效的 API Key")
    return True


def normalize_reference_ids(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []

    normalized: List[str] = []
    for item in value:
        if isinstance(item, str) and item:
            normalized.append(item)
        elif isinstance(item, dict) and item.get("id"):
            normalized.append(str(item["id"]))
    return normalized


# ── 健康检查 ─────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
    }


# ── 队列状态（调试用，不需要 key）──────────────────────────────

@app.get("/ai/embed-status")
async def embed_status():
    """返回 viral_posts 的 embed 状态分布，方便观察 worker 进度。"""
    counts: Dict[str, int] = {}
    for status in ("pending", "done", "error"):
        res = (
            sb.table("viral_posts")
            .select("id", count="exact")
            .eq("embed_status", status)
            .execute()
        )
        counts[status] = res.count or 0
    return counts


@app.get("/ai/research/health", dependencies=[Depends(require_api_key)])
async def research_health():
    active = (
        sb.table("knowledge_items")
        .select("id", count="exact")
        .eq("is_active", True)
        .execute()
    )
    embedded = (
        sb.table("knowledge_items")
        .select("id", count="exact")
        .eq("is_active", True)
        .eq("embed_status", "completed")
        .execute()
    )
    pending = (
        sb.table("knowledge_items")
        .select("id", count="exact")
        .eq("embed_status", "pending")
        .execute()
    )
    return {
        "ok": True,
        "active_knowledge_items": active.count or 0,
        "embedded_knowledge_items": embedded.count or 0,
        "pending_embeddings": pending.count or 0,
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
    }


# ── Phase 1：爆款语义检索 ────────────────────────────────────────

class SearchViralReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)


class CreateDiscoveryJobReq(BaseModel):
    user_question: str = Field(..., min_length=1, max_length=1000)
    task_type: Literal["material", "experience", "image_reference", "mixed"] = Field(default="mixed")
    trigger_reason: Literal["sparse_recall", "zero_recall", "user_requested"] = Field(default="user_requested")
    internal_answer_payload: Dict[str, Any] = Field(default_factory=dict)
    search_queries: Optional[List[str]] = None
    benchmark_account_ids: List[str] = Field(default_factory=list)
    created_by_member_id: Optional[str] = None
    crawler_brief: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[str] = None


class ReviewCandidateReq(BaseModel):
    reason: Optional[Literal["不相关", "低质量", "疑似广告", "重复素材", "不适合团队调性", "数据异常"]] = None


class CreateConversationReq(BaseModel):
    title: str = "新对话"
    member_id: Optional[str] = None


class ClarifyConversationReq(BaseModel):
    message: str = Field(..., min_length=1)


class BuildCrawlerBriefReq(BaseModel):
    original_request: str = Field(..., min_length=1)
    selections: Dict[str, List[str]] = Field(default_factory=dict)
    free_text: str = ""


class CreateAgentRunReq(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    image_url: Optional[str] = None
    member_id: Optional[str] = None


class CreateAgentReviewActionReq(BaseModel):
    run_id: str = Field(..., min_length=1)
    action_type: Literal["approve_candidate", "save_note", "add_calendar_item", "save_draft", "mark_template"]
    payload: Dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = Field(default=None, max_length=1000)
    evidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    duplicate_warning: Optional[str] = Field(default=None, max_length=500)


class ReviewAgentActionReq(BaseModel):
    reason: Optional[Literal["不相关", "低质量", "疑似广告", "重复素材", "不适合团队调性", "数据异常", "已入库"]] = None
    member_id: Optional[str] = None


@app.post("/ai/search-viral", dependencies=[Depends(require_api_key)])
async def search_viral(req: SearchViralReq):
    """对爆款帖子做语义检索，返回相似度排序后的列表。"""
    try:
        embeds = await embed_texts([req.query], input_type="query")
    except Exception as e:
        log.error(f"query embed 失败: {e}")
        raise HTTPException(500, "embedding 服务暂时不可用")

    qemb = embeds[0]

    try:
        res = sb.rpc("search_viral_posts", {
            "query_embedding": qemb,
            "top_k": req.top_k,
        }).execute()
    except Exception as e:
        log.error(f"pgvector RPC 失败: {e}")
        raise HTTPException(500, "检索失败")

    return {"query": req.query, "items": res.data or []}


@app.post("/ai/research", dependencies=[Depends(require_api_key)])
async def research(req: ResearchRequest):
    try:
        result = await research_service.research(req)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"research 失败: {e}")
        raise HTTPException(500, "AI 服务暂时不可用，请稍后再试。")
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result.dict()


@app.get("/ai/conversations", dependencies=[Depends(require_api_key)])
async def list_ai_conversations():
    rows = await conversation_store.list_conversations()
    return {"ok": True, "conversations": rows}


@app.post("/ai/conversations", dependencies=[Depends(require_api_key)])
async def create_ai_conversation(req: CreateConversationReq):
    conversation = await conversation_store.create_conversation(
        title=req.title,
        member_id=req.member_id,
    )
    return {"ok": True, "conversation": conversation}


@app.get("/ai/conversations/{conversation_id}", dependencies=[Depends(require_api_key)])
async def get_ai_conversation(conversation_id: str):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    return {"ok": True, **snapshot}


@app.post("/ai/conversations/{conversation_id}/clarify", dependencies=[Depends(require_api_key)])
async def clarify_ai_conversation(conversation_id: str, req: ClarifyConversationReq):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    await conversation_store.add_message(conversation_id, "user", "text", req.message)
    clarification = await clarification_service.clarify_request(
        req.message,
        messages=snapshot.get("messages") or [],
    )
    await conversation_store.add_message(
        conversation_id,
        "assistant",
        "clarification" if clarification.get("needs_clarification") else "crawler_brief",
        clarification.get("question") or clarification.get("crawler_brief", {}).get("goal") or "",
        clarification,
    )
    crawler_brief = clarification.get("crawler_brief")
    if not clarification.get("needs_clarification") and isinstance(crawler_brief, dict):
        await conversation_store.update_context(
            conversation_id,
            latest_crawler_brief=crawler_brief,
        )
    return {"ok": True, "clarification": clarification}


@app.post("/ai/conversations/{conversation_id}/crawler-brief", dependencies=[Depends(require_api_key)])
async def build_ai_conversation_crawler_brief(conversation_id: str, req: BuildCrawlerBriefReq):
    snapshot = await conversation_store.get_conversation_snapshot(conversation_id)
    if not snapshot:
        raise HTTPException(404, "对话不存在")
    brief_result = await clarification_service.build_crawler_brief(
        original_request=req.original_request,
        selections=req.selections,
        free_text=req.free_text,
    )
    crawler_brief = brief_result["crawler_brief"]
    await conversation_store.add_message(
        conversation_id,
        "assistant",
        "crawler_brief",
        crawler_brief.get("goal") or "已生成爬虫 brief",
        brief_result,
    )
    await conversation_store.update_context(
        conversation_id,
        latest_crawler_brief=crawler_brief,
    )
    return {"ok": True, "brief": brief_result}


@app.post("/agent/runs", dependencies=[Depends(require_api_key)])
async def create_agent_run(req: CreateAgentRunReq):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    run = await agent_orchestrator.create_run(
        user_message=req.message,
        user_image_url=req.image_url,
        member_id=req.member_id,
    )
    return {"ok": True, "run": run, "steps": []}


@app.get("/agent/runs/{run_id}", dependencies=[Depends(require_api_key)])
async def get_agent_run(run_id: str):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    snapshot = await agent_run_store.get_run_snapshot(run_id)
    if not snapshot:
        raise HTTPException(404, "运营助手任务不存在")
    return snapshot


@app.get("/agent/runs/{run_id}/events", dependencies=[Depends(require_api_key)])
async def stream_agent_run_events(run_id: str):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    snapshot = await agent_run_store.get_run_snapshot(run_id)
    if not snapshot:
        raise HTTPException(404, "运营助手任务不存在")

    return StreamingResponse(
        agent_event_bus.stream_sse(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/agent/review-actions", dependencies=[Depends(require_api_key)])
async def create_agent_review_action(req: CreateAgentReviewActionReq):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    try:
        action = await agent_run_store.create_review_action(
            run_id=req.run_id,
            action_type=req.action_type,
            payload=req.payload,
            rationale=req.rationale,
            evidence_score=req.evidence_score,
            duplicate_warning=req.duplicate_warning,
        )
    except KeyError:
        raise HTTPException(404, "运营助手任务不存在")
    except Exception as e:
        log.error(f"创建 Agent 待确认动作失败: {e}")
        raise HTTPException(500, "创建待确认动作失败，请稍后重试。")
    return {"ok": True, "action": action}


@app.get("/agent/review-actions", dependencies=[Depends(require_api_key)])
async def list_agent_review_actions(
    status: Optional[Literal["pending", "approved", "rejected", "cancelled"]] = None,
    run_id: Optional[str] = None,
):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    try:
        actions = await agent_run_store.list_review_actions(status=status, run_id=run_id)
    except Exception as e:
        log.error(f"读取 Agent 待确认动作失败: {e}")
        raise HTTPException(500, "读取待确认队列失败，请稍后重试。")
    return {"ok": True, "actions": actions}


@app.post("/agent/review-actions/{action_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_agent_review_action(action_id: str, req: ReviewAgentActionReq):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    try:
        action = await agent_run_store.review_action(
            action_id,
            status="approved",
            review_reason=req.reason,
            reviewed_by_member_id=req.member_id,
        )
    except KeyError:
        raise HTTPException(404, "待确认动作不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"通过 Agent 待确认动作失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")
    return {"ok": True, "action": action}


@app.post("/agent/review-actions/{action_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_agent_review_action(action_id: str, req: ReviewAgentActionReq):
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(404, "运营助手暂未开启")

    try:
        action = await agent_run_store.review_action(
            action_id,
            status="rejected",
            review_reason=req.reason or "不相关",
            reviewed_by_member_id=req.member_id,
        )
    except KeyError:
        raise HTTPException(404, "待确认动作不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"拒绝 Agent 待确认动作失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")
    return {"ok": True, "action": action}


@app.post("/ai/research-notes", dependencies=[Depends(require_api_key)])
async def save_research_note(payload: Dict[str, Any]):
    try:
        normalized_payload = dict(payload)
        normalized_payload["material_references"] = normalize_reference_ids(payload.get("material_references"))
        normalized_payload["team_history_references"] = normalize_reference_ids(payload.get("team_history_references"))
        res = sb.table("ai_research_notes").insert([normalized_payload]).execute()
    except Exception as e:
        log.error(f"保存 research note 失败: {e}")
        raise HTTPException(500, "保存失败，请稍后重试。")
    rows = res.data or []
    return {"ok": True, "note": rows[0] if rows else None}


@app.post("/ai/discovery-jobs", dependencies=[Depends(require_api_key)])
async def create_discovery_job(req: CreateDiscoveryJobReq):
    enabled = getattr(app_config, "EXTERNAL_DISCOVERY_ENABLED", False)
    if not enabled:
        raise HTTPException(400, "外部发现功能尚未开启")
    try:
        queries = req.search_queries
        if not queries and req.crawler_brief:
            queries = derive_search_queries_from_brief(req.user_question, req.crawler_brief, max_queries=4)
        if not queries:
            queries = derive_search_queries(req.user_question, max_queries=4)
        job = discovery_service.create_job(
            user_question=req.user_question,
            task_type=req.task_type,
            trigger_reason=req.trigger_reason,
            internal_answer_payload=req.internal_answer_payload,
            search_queries=queries,
            benchmark_account_ids=req.benchmark_account_ids,
            created_by_member_id=req.created_by_member_id,
            crawler_brief=req.crawler_brief,
            quality_targets=req.crawler_brief.get("quality_targets") or [],
            exclusions=req.crawler_brief.get("exclusions") or [],
            candidate_scoring_hint=req.crawler_brief.get("candidate_scoring_hint"),
            conversation_id=req.conversation_id,
        )
        if req.conversation_id:
            try:
                await conversation_store.update_context(
                    req.conversation_id,
                    active_discovery_job_id=job.get("id"),
                    latest_crawler_brief=req.crawler_brief or {},
                )
            except Exception as context_error:
                log.warning(f"更新对话外部发现上下文失败: {context_error}")
        return {"ok": True, "job": job}
    except Exception as e:
        log.error(f"创建外部发现任务失败: {e}")
        raise HTTPException(500, "创建外部发现任务失败，请稍后重试。")


@app.get("/ai/discovery-jobs/{job_id}", dependencies=[Depends(require_api_key)])
async def get_discovery_job(job_id: str):
    try:
        return discovery_service.get_job_with_candidates(job_id)
    except DiscoveryNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"读取外部发现任务失败: {e}")
        raise HTTPException(500, "读取外部发现任务失败，请稍后重试。")


@app.post("/ai/discovery-jobs/{job_id}/supplement", dependencies=[Depends(require_api_key)])
async def create_discovery_supplement(job_id: str):
    try:
        payload = discovery_service.get_job_with_candidates(job_id)
        job = payload["job"]
        candidates = [
            row for row in payload["candidates"]
            if row.get("review_status") in ("pending", "approved")
        ]
        result = await research_service.generate_external_supplement(
            job_id=job_id,
            question=job.get("user_question") or "",
            candidates=candidates,
        )
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result.dict()
    except DiscoveryNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"生成外部补充回答失败: {e}")
        raise HTTPException(500, "生成外部补充回答失败，请稍后重试。")


@app.post("/ai/discovery-candidates/{candidate_id}/ignore", dependencies=[Depends(require_api_key)])
async def ignore_discovery_candidate(candidate_id: str):
    try:
        candidate = discovery_service.mark_candidate_review(candidate_id, "ignored")
        return {"ok": True, "candidate": candidate}
    except DiscoveryNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"忽略候选素材失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")


@app.post("/ai/discovery-candidates/{candidate_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_discovery_candidate(candidate_id: str):
    try:
        candidate = discovery_service.approve_candidate(candidate_id)
        return {"ok": True, "candidate": candidate}
    except DiscoveryNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"通过候选素材并入库失败: {e}")
        raise HTTPException(500, "通过并入库失败，请稍后重试。")


@app.post("/ai/discovery-candidates/{candidate_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_discovery_candidate(candidate_id: str, req: ReviewCandidateReq):
    try:
        candidate = discovery_service.mark_candidate_review(candidate_id, "rejected", req.reason or "不相关")
        return {"ok": True, "candidate": candidate}
    except DiscoveryNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"拒绝候选素材失败: {e}")
        raise HTTPException(500, "操作失败，请稍后重试。")


# ────────────────────────────────────────────────────────────────
# 入口
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "ai_api:app",
        host=AI_API_HOST,
        port=AI_API_PORT,
        reload=False,
    )
