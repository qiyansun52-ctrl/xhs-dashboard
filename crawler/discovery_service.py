from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from discovery import derive_search_queries
from knowledge_indexer import build_viral_post_item, upsert_knowledge_item


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryNotFoundError(Exception):
    pass


class DiscoveryService:
    def __init__(self, supabase_client, max_queries: int = 4):
        self.sb = supabase_client
        self.max_queries = max_queries

    def create_job(
        self,
        user_question: str,
        task_type: str,
        trigger_reason: str,
        internal_answer_payload: Dict[str, Any],
        search_queries: Optional[List[str]] = None,
        benchmark_account_ids: Optional[List[str]] = None,
        created_by_member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        queries = (
            derive_search_queries(user_question, max_queries=self.max_queries)
            if search_queries is None
            else search_queries
        )
        payload = {
            "user_question": user_question,
            "task_type": task_type,
            "trigger_reason": trigger_reason,
            "internal_answer_payload": internal_answer_payload or {},
            "search_queries": queries[:self.max_queries],
            "benchmark_account_ids": benchmark_account_ids or [],
            "status": "pending",
            "created_by_member_id": created_by_member_id,
        }
        res = self.sb.table("external_discovery_jobs").insert([payload]).execute()
        rows = res.data or []
        return rows[0] if rows else payload

    def get_job_with_candidates(self, job_id: str) -> Dict[str, Any]:
        job_res = (
            self.sb.table("external_discovery_jobs")
            .select("*")
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
        if not job_res.data:
            raise DiscoveryNotFoundError("外部发现任务不存在")
        candidate_res = (
            self.sb.table("external_discovery_candidates")
            .select("*")
            .eq("job_id", job_id)
            .order("candidate_score", desc=True)
            .execute()
        )
        return {
            "job": job_res.data,
            "candidates": candidate_res.data or [],
        }

    def mark_candidate_review(
        self,
        candidate_id: str,
        review_status: str,
        review_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "review_status": review_status,
            "review_reason": review_reason,
            "reviewed_at": now_iso(),
        }
        res = (
            self.sb.table("external_discovery_candidates")
            .update(payload)
            .eq("id", candidate_id)
            .eq("review_status", "pending")
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise DiscoveryNotFoundError("候选素材不存在或已审核")
        return rows[0]

    def _find_existing_viral_post(self, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        xhs_note_id = (candidate.get("xhs_note_id") or "").strip()
        if xhs_note_id:
            res = (
                self.sb.table("viral_posts")
                .select("*")
                .eq("xhs_note_id", xhs_note_id)
                .maybe_single()
                .execute()
            )
            return res.data

        url = (candidate.get("url") or "").strip()
        if not url:
            return None
        res = (
            self.sb.table("viral_posts")
            .select("*")
            .eq("url", url)
            .maybe_single()
            .execute()
        )
        return res.data

    def _viral_payload_from_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        note_parts = ["来源：AI 外部发现"]
        if candidate.get("ai_reason"):
            note_parts.append(str(candidate["ai_reason"]))
        return {
            "source_origin": "ai_external_discovery",
            "discovery_candidate_id": candidate["id"],
            "fetch_status": "done",
            "fetched_at": now_iso(),
            "url": candidate.get("url"),
            "xhs_note_id": candidate.get("xhs_note_id"),
            "title": candidate.get("title") or "",
            "caption": candidate.get("caption") or "",
            "cover_image": candidate.get("cover_image"),
            "images": candidate.get("images") or [],
            "tags": candidate.get("tags") or [],
            "author_name": candidate.get("author_name"),
            "likes": candidate.get("likes") or 0,
            "saves": candidate.get("saves") or 0,
            "comments": candidate.get("comments") or 0,
            "views": candidate.get("views") or 0,
            "country": None,
            "note": "\n".join(note_parts),
        }

    def approve_candidate(self, candidate_id: str) -> Dict[str, Any]:
        candidate_res = (
            self.sb.table("external_discovery_candidates")
            .select("*")
            .eq("id", candidate_id)
            .eq("review_status", "pending")
            .maybe_single()
            .execute()
        )
        candidate = candidate_res.data
        if not candidate or candidate.get("review_status") != "pending":
            raise DiscoveryNotFoundError("候选素材不存在或已审核")

        payload = self._viral_payload_from_candidate(candidate)
        existing = self._find_existing_viral_post(candidate)
        if existing:
            viral_res = (
                self.sb.table("viral_posts")
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
            viral_rows = viral_res.data or []
            viral_post = {**existing, **payload, **(viral_rows[0] if viral_rows else {}), "id": existing["id"]}
        else:
            viral_res = self.sb.table("viral_posts").insert([payload]).execute()
            viral_rows = viral_res.data or []
            viral_post = viral_rows[0] if viral_rows else payload

        if not viral_post.get("id"):
            raise RuntimeError("入库素材缺少 ID，无法建立知识索引")

        candidate_update = {
            "review_status": "approved",
            "review_reason": None,
            "reviewed_at": now_iso(),
            "approved_viral_post_id": viral_post["id"],
        }
        candidate_update_res = (
            self.sb.table("external_discovery_candidates")
            .update(candidate_update)
            .eq("id", candidate_id)
            .eq("review_status", "pending")
            .execute()
        )
        candidate_rows = candidate_update_res.data or []
        if not candidate_rows:
            raise DiscoveryNotFoundError("候选素材不存在或已审核")

        upsert_knowledge_item(self.sb, build_viral_post_item(viral_post))
        return candidate_rows[0]
