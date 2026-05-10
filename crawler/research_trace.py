from __future__ import annotations

import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def write_research_trace(supabase_client, payload: Dict[str, Any]) -> Optional[str]:
    """Best-effort trace insert. Retrieval should never fail because tracing fails."""
    if not supabase_client:
        return None

    trace_id = str(uuid.uuid4())
    row = {
        "id": trace_id,
        "user_question": str(payload.get("user_question") or ""),
        "intent": str(payload.get("intent") or ""),
        "retrieval_profile": str(payload.get("retrieval_profile") or ""),
        "parser_payload": _json_safe(payload.get("parser_payload") or {}),
        "route_counts": _json_safe(payload.get("route_counts") or {}),
        "top_candidates": _json_safe(payload.get("top_candidates") or []),
        "selected_evidence_ids": [str(item_id) for item_id in payload.get("selected_evidence_ids") or []],
        "dropped_counts": _json_safe(payload.get("dropped_counts") or {}),
        "evidence_quality": str(payload.get("evidence_quality") or "empty"),
        "generation_allowed": bool(payload.get("generation_allowed")),
        "answer_payload": _json_safe(payload.get("answer_payload") or {}),
    }

    try:
        supabase_client.table("research_traces").insert(row).execute()
        return trace_id
    except Exception:
        return None
