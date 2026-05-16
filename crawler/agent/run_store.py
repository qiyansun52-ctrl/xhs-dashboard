from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class AgentRunStore:
    def __init__(self, supabase_client=None):
        self.sb = supabase_client
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._steps: Dict[str, List[Dict[str, Any]]] = {}
        self._tool_invocations: Dict[str, Dict[str, Any]] = {}
        self._question_cache: Dict[tuple, Dict[str, Any]] = {}
        self._review_actions: Dict[str, Dict[str, Any]] = {}
        self._db_persistence_disabled = False

    async def create_run(self, user_message: str, user_image_url: Optional[str] = None, member_id: Optional[str] = None) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        row = {
            "id": run_id,
            "user_message": user_message,
            "user_image_url": user_image_url,
            "member_id": member_id,
            "status": "planning",
            "plan": None,
            "final_answer": None,
            "error_message": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "completed_at": None,
        }
        self._runs[run_id] = row
        self._steps.setdefault(run_id, [])
        if self._can_persist():
            self._execute_persist(self.sb.table("agent_runs").insert([json_safe(row)]))
        return copy.deepcopy(row)

    async def update_run(self, run_id: str, **fields) -> Dict[str, Any]:
        run = self._runs.get(run_id)
        if not run and self._can_persist():
            run = await self._load_run_from_db(run_id)
        if not run:
            raise KeyError(f"run not found: {run_id}")

        payload = dict(fields)
        payload["updated_at"] = now_iso()
        run.update(json_safe(payload))

        if self._can_persist():
            self._execute_persist(self.sb.table("agent_runs").update(json_safe(payload)).eq("id", run_id))
        return copy.deepcopy(run)

    async def create_step(
        self,
        run_id: str,
        step_type: str,
        status: str = "pending",
        tool_name: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        output_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        step_id = str(uuid.uuid4())
        step_index = len(self._steps.setdefault(run_id, [])) + 1
        row = {
            "id": step_id,
            "run_id": run_id,
            "step_index": step_index,
            "step_type": step_type,
            "tool_name": tool_name,
            "status": status,
            "input_payload": json_safe(input_payload or {}),
            "output_payload": json_safe(output_payload or {}),
            "error_message": None,
            "created_at": now_iso(),
            "completed_at": None,
        }
        self._steps[run_id].append(row)
        if self._can_persist():
            self._execute_persist(self.sb.table("agent_steps").insert([json_safe(row)]))
        return copy.deepcopy(row)

    async def complete_step(
        self,
        run_id: str,
        step_id: str,
        status: str = "completed",
        output_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        step = self._find_step(run_id, step_id)
        if not step:
            raise KeyError(f"step not found: {step_id}")

        payload = {
            "status": status,
            "output_payload": json_safe(output_payload or {}),
            "error_message": error_message,
            "completed_at": now_iso(),
        }
        step.update(payload)
        if self._can_persist():
            self._execute_persist(self.sb.table("agent_steps").update(json_safe(payload)).eq("id", step_id))
        return copy.deepcopy(step)

    async def get_run_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self._runs.get(run_id)
        steps = self._steps.get(run_id)

        if (not run or steps is None) and self._can_persist():
            if not run:
                run = await self._load_run_from_db(run_id)
            if steps is None:
                steps = await self._load_steps_from_db(run_id)

        if not run:
            return None

        return {
            "run": copy.deepcopy(run),
            "steps": copy.deepcopy(steps or []),
        }

    async def create_review_action(
        self,
        run_id: str,
        action_type: str,
        payload: Dict[str, Any],
        rationale: Optional[str] = None,
        evidence_score: Optional[float] = None,
        duplicate_warning: Optional[str] = None,
    ) -> Dict[str, Any]:
        run = self._runs.get(run_id)
        if not run and self._can_persist():
            run = await self._load_run_from_db(run_id)
        if not run:
            raise KeyError(f"run not found: {run_id}")

        action_id = str(uuid.uuid4())
        row = {
            "id": action_id,
            "run_id": run_id,
            "action_type": action_type,
            "status": "pending",
            "payload": json_safe(payload or {}),
            "rationale": rationale,
            "evidence_score": evidence_score,
            "duplicate_warning": duplicate_warning,
            "review_reason": None,
            "reviewed_by_member_id": None,
            "created_at": now_iso(),
            "reviewed_at": None,
        }
        self._review_actions[action_id] = row
        if self._can_persist():
            self._execute_persist(self.sb.table("agent_review_actions").insert([json_safe(row)]))
        return copy.deepcopy(row)

    async def list_review_actions(
        self,
        status: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        if self._can_persist():
            try:
                query = self.sb.table("agent_review_actions").select("*")
                if status:
                    query = query.eq("status", status)
                if run_id:
                    query = query.eq("run_id", run_id)
                res = query.order("created_at", desc=True).limit(limit).execute()
                for row in res.data or []:
                    self._review_actions[row["id"]] = dict(row)
                return copy.deepcopy(list(res.data or []))
            except Exception as exc:
                if self._is_missing_agent_schema_error(exc):
                    self._db_persistence_disabled = True
                    log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                else:
                    raise

        rows = list(self._review_actions.values())
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if run_id:
            rows = [row for row in rows if row.get("run_id") == run_id]
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return copy.deepcopy(rows[:limit])

    async def review_action(
        self,
        action_id: str,
        status: str,
        review_reason: Optional[str] = None,
        reviewed_by_member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if status not in {"approved", "rejected", "cancelled"}:
            raise ValueError("review action status must be approved, rejected, or cancelled")

        action = self._review_actions.get(action_id)
        if not action and self._can_persist():
            action = await self._load_review_action_from_db(action_id)
        if not action:
            raise KeyError(f"review action not found: {action_id}")
        if action.get("status") != "pending":
            raise ValueError("review action is not pending")

        payload = {
            "status": status,
            "review_reason": review_reason,
            "reviewed_by_member_id": reviewed_by_member_id,
            "reviewed_at": now_iso(),
        }
        action.update(json_safe(payload))
        if self._can_persist():
            self._execute_persist(self.sb.table("agent_review_actions").update(json_safe(payload)).eq("id", action_id))
        return copy.deepcopy(action)

    async def get_tool_invocation(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        record = self._tool_invocations.get(idempotency_key)
        if record:
            return copy.deepcopy(record)

        if self._can_persist():
            try:
                res = (
                    self.sb.table("tool_invocations")
                    .select("*")
                    .eq("idempotency_key", idempotency_key)
                    .maybe_single()
                    .execute()
                )
            except Exception as exc:
                if self._is_missing_agent_schema_error(exc):
                    self._db_persistence_disabled = True
                    log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                    return None
                raise
            if res.data:
                self._tool_invocations[idempotency_key] = dict(res.data)
                return copy.deepcopy(res.data)

        return None

    async def create_tool_invocation(self, idempotency_key: str, tool_name: str, input_hash: str) -> Dict[str, Any]:
        record = {
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "input_hash": input_hash,
            "output_payload": None,
            "status": "pending",
            "created_at": now_iso(),
            "completed_at": None,
        }
        self._tool_invocations[idempotency_key] = record
        if self._can_persist():
            self._execute_persist(self.sb.table("tool_invocations").insert([json_safe(record)]))
        return copy.deepcopy(record)

    async def complete_tool_invocation(self, idempotency_key: str, output_payload: Dict[str, Any], status: str = "completed") -> Dict[str, Any]:
        record = self._tool_invocations.get(idempotency_key)
        if not record:
            raise KeyError(f"tool invocation not found: {idempotency_key}")

        payload = {
            "status": status,
            "output_payload": json_safe(output_payload),
            "completed_at": now_iso(),
        }
        record.update(payload)
        if self._can_persist():
            self._execute_persist(self.sb.table("tool_invocations").update(json_safe(payload)).eq("idempotency_key", idempotency_key))
        return copy.deepcopy(record)

    async def get_question_cache(self, question_hash: str, member_id: Optional[str]) -> Optional[Dict[str, Any]]:
        member_key = member_id or "anonymous"
        record = self._question_cache.get((question_hash, member_key))
        if record:
            return copy.deepcopy(record)

        if self._can_persist():
            try:
                res = (
                    self.sb.table("agent_question_cache")
                    .select("*")
                    .eq("question_hash", question_hash)
                    .eq("member_key", member_key)
                    .maybe_single()
                    .execute()
                )
                if res.data:
                    self._question_cache[(question_hash, member_key)] = dict(res.data)
                    return copy.deepcopy(res.data)
            except Exception:
                return None

        return None

    async def upsert_question_cache(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        question_hash = str(payload["question_hash"])
        member_key = str(payload.get("member_key") or "anonymous")
        record = {
            "question_hash": question_hash,
            "member_key": member_key,
            "last_run_id": payload.get("last_run_id"),
            "last_intent": payload.get("last_intent") or {},
            "last_evidence_quality": payload.get("last_evidence_quality"),
            "declined_external": bool(payload.get("declined_external", False)),
            "hit_count": int(payload.get("hit_count", 1)),
            "last_hit_at": now_iso(),
        }
        self._question_cache[(question_hash, member_key)] = record

        if self._can_persist():
            try:
                self.sb.table("agent_question_cache").upsert(
                    json_safe(record),
                    on_conflict="question_hash,member_key",
                ).execute()
            except Exception:
                pass

        return copy.deepcopy(record)

    async def increment_question_cache_hit(self, question_hash: str, member_id: Optional[str]) -> None:
        member_key = member_id or "anonymous"
        record = self._question_cache.get((question_hash, member_key))
        if not record:
            return
        record["hit_count"] = int(record.get("hit_count") or 0) + 1
        record["last_hit_at"] = now_iso()
        if self._can_persist():
            try:
                self.sb.table("agent_question_cache").update({
                    "hit_count": record["hit_count"],
                    "last_hit_at": record["last_hit_at"],
                }).eq("question_hash", question_hash).eq("member_key", member_key).execute()
            except Exception:
                pass

    def question_hash(self, question: str) -> str:
        normalized = " ".join(str(question or "").strip().split()).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _find_step(self, run_id: str, step_id: str) -> Optional[Dict[str, Any]]:
        for step in self._steps.get(run_id, []):
            if step["id"] == step_id:
                return step
        return None

    def _can_persist(self) -> bool:
        return bool(self.sb) and not self._db_persistence_disabled

    def _execute_persist(self, builder) -> None:
        if not self._can_persist():
            return
        try:
            builder.execute()
        except Exception as exc:
            if self._is_missing_agent_schema_error(exc):
                self._db_persistence_disabled = True
                log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                return
            raise

    def _is_missing_agent_schema_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "pgrst205" in text or ("schema cache" in text and "could not find the table" in text)

    async def _load_run_from_db(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            res = self.sb.table("agent_runs").select("*").eq("id", run_id).maybe_single().execute()
        except Exception as exc:
            if self._is_missing_agent_schema_error(exc):
                self._db_persistence_disabled = True
                log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                return None
            raise
        if not res.data:
            return None
        self._runs[run_id] = dict(res.data)
        return self._runs[run_id]

    async def _load_steps_from_db(self, run_id: str) -> List[Dict[str, Any]]:
        try:
            res = self.sb.table("agent_steps").select("*").eq("run_id", run_id).order("step_index").execute()
        except Exception as exc:
            if self._is_missing_agent_schema_error(exc):
                self._db_persistence_disabled = True
                log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                return []
            raise
        self._steps[run_id] = list(res.data or [])
        return self._steps[run_id]

    async def _load_review_action_from_db(self, action_id: str) -> Optional[Dict[str, Any]]:
        try:
            res = self.sb.table("agent_review_actions").select("*").eq("id", action_id).maybe_single().execute()
        except Exception as exc:
            if self._is_missing_agent_schema_error(exc):
                self._db_persistence_disabled = True
                log.warning("Agent 持久化表未迁移，当前进程降级为内存态运行: %s", exc)
                return None
            raise
        if not res.data:
            return None
        self._review_actions[action_id] = dict(res.data)
        return self._review_actions[action_id]
