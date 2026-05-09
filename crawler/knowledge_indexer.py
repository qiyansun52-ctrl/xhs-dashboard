from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


EMBED_MODEL_VERSION = "voyage-3-lite:512"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_language(text: str) -> str:
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text or ""))
    has_ascii_word = bool(re.search(r"[A-Za-z]{3,}", text or ""))
    if has_cjk and has_ascii_word:
        return "mixed"
    if has_ascii_word and not has_cjk:
        return "en"
    return "zh"


def build_content_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_tags(tags: Any) -> List[str]:
    if not tags:
        return []
    if isinstance(tags, list):
        normalized: List[str] = []
        for tag in tags:
            if tag is None:
                continue
            value = str(tag).strip()
            if value:
                normalized.append(value)
        return normalized
    value = str(tags).strip()
    return [value] if value else []


def build_text(title: str, caption: str = "", tags: Optional[List[str]] = None) -> str:
    parts = [title.strip()]
    if caption and caption.strip():
        parts.append(caption.strip())
    if tags:
        parts.append("标签：" + " ".join(tags))
    return "\n\n".join(part for part in parts if part)


def build_team_post_item(post: Dict[str, Any], stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tags = normalize_tags(post.get("tags"))
    title = post.get("title") or ""
    caption = post.get("caption") or ""
    content = build_text(title, caption, tags)
    stats = stats or {}
    return {
        "source_type": "team_post",
        "source_id": str(post["id"]),
        "source_key": str(post["id"]),
        "source_url": None,
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": None,
        "account_id": post.get("account_id"),
        "language": detect_language(content),
        "content_type": "image-heavy" if post.get("images") else "text-heavy",
        "likes_count": stats.get("likes"),
        "saves_count": stats.get("saves"),
        "comments_count": stats.get("comments"),
        "views_count": stats.get("views"),
        "metrics_extra": {"status": post.get("status"), "shares": stats.get("shares")},
        "image_urls": post.get("images") or [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": post.get("scheduled_at") or post.get("created_at"),
        "source_updated_at": post.get("updated_at") or post.get("created_at"),
        "content_hash": build_content_hash(title, caption, tags, stats),
        "last_indexed_at": now_iso(),
    }


def build_benchmark_post_item(benchmark_id: str, account_name: str, post: Dict[str, Any]) -> Dict[str, Any]:
    tags = normalize_tags(post.get("tags"))
    title = post.get("title") or ""
    caption = post.get("caption") or ""
    note_id = post.get("note_id") or post.get("id") or str(post.get("index", "0"))
    content = build_text(title, caption, tags)
    return {
        "source_type": "benchmark_post",
        "source_id": str(note_id),
        "source_key": f"{benchmark_id}:{note_id}",
        "parent_source_type": "benchmark_account",
        "parent_source_id": str(benchmark_id),
        "source_url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None,
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": post.get("country"),
        "account_id": None,
        "language": detect_language(content),
        "content_type": "image-heavy" if post.get("images") or post.get("cover_image") else "text-heavy",
        "likes_count": post.get("likes"),
        "saves_count": post.get("saves"),
        "comments_count": post.get("comments"),
        "views_count": post.get("views"),
        "metrics_extra": {"author_name": account_name},
        "image_urls": post.get("images") or ([post["cover_image"]] if post.get("cover_image") else []),
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": post.get("published_at"),
        "source_updated_at": post.get("updated_at"),
        "content_hash": build_content_hash(title, caption, tags, post.get("likes"), post.get("saves")),
        "last_indexed_at": now_iso(),
    }


def build_benchmark_account_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("name") or "对标账号"
    tags = normalize_tags([row.get("destination"), row.get("content_type"), row.get("note_direction")])
    content = build_text(
        title,
        "\n".join([
            row.get("bio") or "",
            row.get("note_direction") or "",
            row.get("consumer_words") or "",
        ]),
        tags,
    )
    return {
        "source_type": "benchmark_account",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("xhs_url"),
        "title": title,
        "content": content,
        "summary": row.get("bio"),
        "tags": tags,
        "country": row.get("destination"),
        "account_id": None,
        "language": detect_language(content),
        "content_type": "benchmark_account",
        "likes_count": None,
        "saves_count": None,
        "comments_count": None,
        "views_count": None,
        "metrics_extra": {"followers": row.get("followers"), "fetch_status": row.get("fetch_status")},
        "image_urls": [row["avatar_url"]] if str(row.get("avatar_url") or "").startswith("http") else [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": row.get("fetch_status") == "done",
        "published_at": row.get("fetched_at") or row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("fetched_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, content, row.get("followers")),
        "last_indexed_at": now_iso(),
    }


def upsert_knowledge_item(sb, item: Dict[str, Any]) -> None:
    existing = (
        sb.table("knowledge_items")
        .select("id, content_hash, embed_status")
        .eq("source_type", item["source_type"])
        .eq("source_key", item["source_key"])
        .maybe_single()
        .execute()
    )
    current = existing.data
    if current and current.get("content_hash") == item.get("content_hash"):
        if current.get("embed_status") != "failed":
            metadata = {
                key: value
                for key, value in item.items()
                if key not in ("embedding", "embed_status", "embed_error", "retry_count")
            }
            sb.table("knowledge_items").update(metadata).eq("id", current["id"]).execute()
            return
        item["embedding"] = None
        item["embed_status"] = "pending"
        item["retry_count"] = 0
        item["embed_error"] = None
    elif current:
        item["embedding"] = None
        item["embed_status"] = "pending"
        item["retry_count"] = 0
        item["embed_error"] = None

    sb.table("knowledge_items").upsert(item, on_conflict="source_type,source_key").execute()


def rebuild_team_posts(sb) -> int:
    posts = sb.table("posts").select("*").execute().data or []
    count = 0
    for post in posts:
        stats = {}
        try:
            res = sb.table("post_stats").select("*").eq("post_id", post["id"]).maybe_single().execute()
            stats = res.data or {}
        except Exception:
            stats = {}
        upsert_knowledge_item(sb, build_team_post_item(post, stats))
        count += 1
    return count


def rebuild_benchmark_posts(sb) -> int:
    rows = sb.table("benchmark_accounts").select("*").execute().data or []
    count = 0
    for row in rows:
        recent_posts = row.get("recent_posts") or []
        for index, post in enumerate(recent_posts):
            payload = dict(post)
            payload.setdefault("index", index)
            upsert_knowledge_item(
                sb,
                build_benchmark_post_item(str(row["id"]), row.get("name") or "", payload),
            )
            count += 1
    return count


def build_viral_post_item(row: Dict[str, Any]) -> Dict[str, Any]:
    tags = normalize_tags(row.get("tags"))
    title = row.get("title") or ""
    caption = row.get("caption") or row.get("note") or ""
    content = build_text(title, caption, tags)
    return {
        "source_type": "viral_post",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("url"),
        "title": title,
        "content": content,
        "summary": caption[:240] if caption else None,
        "tags": tags,
        "country": row.get("country"),
        "account_id": None,
        "language": detect_language(content),
        "content_type": "image-heavy" if row.get("images") or row.get("cover_image") else "text-heavy",
        "likes_count": row.get("likes"),
        "saves_count": row.get("saves"),
        "comments_count": row.get("comments"),
        "views_count": row.get("views"),
        "metrics_extra": {"author_name": row.get("author_name")},
        "image_urls": row.get("images") or ([row["cover_image"]] if row.get("cover_image") else []),
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": row.get("fetch_status") == "done",
        "published_at": row.get("published_at") or row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, caption, tags, row.get("likes"), row.get("saves")),
        "last_indexed_at": now_iso(),
    }


def build_topic_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("tag") or "选题"
    content = row.get("description") or ""
    return {
        "source_type": "topic",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("reference_url"),
        "title": title,
        "content": content,
        "summary": content[:240] if content else None,
        "tags": normalize_tags([row.get("tag")]),
        "country": None,
        "account_id": None,
        "language": detect_language(content),
        "content_type": "topic",
        "likes_count": row.get("ref_likes"),
        "saves_count": row.get("ref_saves"),
        "comments_count": None,
        "views_count": row.get("ref_views"),
        "metrics_extra": {"fetch_status": row.get("fetch_status")},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, content, row.get("tag")),
        "last_indexed_at": now_iso(),
    }


def build_title_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("title") or ""
    return {
        "source_type": "title",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": None,
        "title": title,
        "content": title,
        "summary": title,
        "tags": [],
        "country": None,
        "account_id": None,
        "language": detect_language(title),
        "content_type": "title",
        "likes_count": None,
        "saves_count": None,
        "comments_count": None,
        "views_count": None,
        "metrics_extra": {},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("created_at"),
        "content_hash": build_content_hash(title),
        "last_indexed_at": now_iso(),
    }


def build_account_item(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("name") or ""
    content = build_text(title, row.get("bio") or "", [row.get("flag") or ""])
    return {
        "source_type": "account",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": row.get("xhs_link"),
        "title": title,
        "content": content,
        "summary": row.get("bio"),
        "tags": normalize_tags([row.get("flag")]),
        "country": row.get("flag"),
        "account_id": row.get("id"),
        "language": detect_language(content),
        "content_type": "account",
        "likes_count": row.get("likes"),
        "saves_count": row.get("saves"),
        "comments_count": None,
        "views_count": row.get("views"),
        "metrics_extra": {"followers": row.get("followers")},
        "image_urls": [row["avatar"]] if str(row.get("avatar") or "").startswith("http") else [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at") or row.get("created_at"),
        "content_hash": build_content_hash(title, row.get("bio"), row.get("followers")),
        "last_indexed_at": now_iso(),
    }


def build_banned_word_item(row: Dict[str, Any]) -> Dict[str, Any]:
    word = row.get("word") or ""
    return {
        "source_type": "banned_word",
        "source_id": str(row["id"]),
        "source_key": str(row["id"]),
        "source_url": None,
        "title": word,
        "content": word,
        "summary": word,
        "tags": [],
        "country": None,
        "account_id": None,
        "language": detect_language(word),
        "content_type": "risk",
        "likes_count": None,
        "saves_count": None,
        "comments_count": None,
        "views_count": None,
        "metrics_extra": {},
        "image_urls": [],
        "embedding_model_version": EMBED_MODEL_VERSION,
        "embed_status": "pending",
        "is_active": True,
        "published_at": row.get("created_at"),
        "source_updated_at": row.get("created_at"),
        "content_hash": build_content_hash(word),
        "last_indexed_at": now_iso(),
    }


def rebuild_table(sb, table: str, builder) -> int:
    rows = sb.table(table).select("*").execute().data or []
    for row in rows:
        upsert_knowledge_item(sb, builder(row))
    return len(rows)


def rebuild_all(sb) -> Dict[str, int]:
    return {
        "viral_posts": rebuild_table(sb, "viral_posts", build_viral_post_item),
        "team_posts": rebuild_team_posts(sb),
        "benchmark_accounts": rebuild_table(sb, "benchmark_accounts", build_benchmark_account_item),
        "benchmark_posts": rebuild_benchmark_posts(sb),
        "topics": rebuild_table(sb, "topics", build_topic_item),
        "titles": rebuild_table(sb, "titles", build_title_item),
        "accounts": rebuild_table(sb, "accounts", build_account_item),
        "banned_words": rebuild_table(sb, "banned_words", build_banned_word_item),
    }


if __name__ == "__main__":
    from supabase import create_client
    from config import SUPABASE_KEY, SUPABASE_URL

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    result = rebuild_all(client)
    print(json.dumps(result, ensure_ascii=False, indent=2))
