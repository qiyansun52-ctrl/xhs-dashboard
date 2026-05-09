#!/usr/bin/env python3
# ================================================================
# MediaCrawler → Supabase 数据导入脚本
#
# 用法：
#   python import_stats.py                   # 自动扫描 MediaCrawler 输出目录
#   python import_stats.py --file data.json  # 指定单个 JSON 文件
#   python import_stats.py --dry-run         # 只打印，不写入数据库
# ================================================================

import argparse
import json
import os
import sys
import glob
from datetime import datetime, timezone

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY, ACCOUNT_MAP, MEDIACRAWLER_DATA_DIR
from parser import parse_note, parse_user


# ── 初始化 Supabase 客户端 ─────────────────────────────────────
def get_client() -> Client:
    if not SUPABASE_URL or "xxxxxxxxxxxx" in SUPABASE_URL:
        print("❌ 请先在 config.py 中填写 SUPABASE_URL 和 SUPABASE_KEY")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── 反向映射：xhs_user_id → account_id ───────────────────────
XHS_TO_ACCOUNT = {v: k for k, v in {}}  # 动态构建，见 main()


# ── 工具函数 ───────────────────────────────────────────────────

def log(msg: str, level: str = "info"):
    icons = {"info": "ℹ️ ", "ok": "✅", "warn": "⚠️ ", "error": "❌", "skip": "⏭️ "}
    print(f"{icons.get(level, '  ')} {msg}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 帖子导入 ──────────────────────────────────────────────────

def upsert_post_stats(sb: Client, post_id: str, note: dict, dry_run: bool) -> bool:
    """更新 post_stats（最新值）并插入 post_stats_history（历史快照）"""
    stats_payload = {
        "post_id":    post_id,
        "likes":      note["likes"],
        "saves":      note["saves"],
        "comments":   note["comments"],
        "views":      note["views"],
        "shares":     note["shares"],
        "updated_at": now_iso(),
    }
    history_payload = {
        "post_id":      post_id,
        "xhs_note_id":  note["xhs_note_id"],
        "likes":        note["likes"],
        "saves":        note["saves"],
        "comments":     note["comments"],
        "views":        note["views"],
        "shares":       note["shares"],
        "collected_at": now_iso(),
    }

    if dry_run:
        log(f"[dry-run] 会写入 post_stats: likes={note['likes']} saves={note['saves']} comments={note['comments']}", "info")
        return True

    # 更新最新值
    sb.table("post_stats").upsert(stats_payload, on_conflict="post_id").execute()
    # 插入历史快照
    sb.table("post_stats_history").insert(history_payload).execute()
    return True


def import_note(sb: Client, note: dict, account_id: int, dry_run: bool) -> str:
    """
    导入一条笔记：
    1. 按 xhs_note_id 查找已有帖子
    2. 找到 → 更新数据
    3. 未找到 → 创建新帖子 + 数据
    返回: "updated" | "created" | "skipped"
    """
    xhs_note_id = note["xhs_note_id"]
    if not xhs_note_id:
        return "skipped"

    # 查找已有帖子
    result = sb.table("posts").select("id, title").eq("xhs_note_id", xhs_note_id).execute()

    if result.data:
        # 帖子已存在 → 只更新数据
        post_id = result.data[0]["id"]
        upsert_post_stats(sb, post_id, note, dry_run)
        log(f"更新数据  「{note['title'][:25]}」  👍{note['likes']} ❤️{note['saves']} 💬{note['comments']}", "ok")
        return "updated"

    # 帖子不存在 → 创建
    if not note["title"]:
        log(f"跳过无标题笔记 {xhs_note_id}", "skip")
        return "skipped"

    if not dry_run:
        import uuid
        new_id = str(uuid.uuid4())
        sb.table("posts").insert({
            "id":          new_id,
            "account_id":  account_id,
            "xhs_note_id": xhs_note_id,
            "title":       note["title"],
            "caption":     note["caption"],
            "tags":        note["tags"],
            "images":      note["images"],
            "status":      "published",
            "img_count":   len(note["images"]),
        }).execute()
        upsert_post_stats(sb, new_id, note, dry_run)
        log(f"新建帖子  「{note['title'][:25]}」  👍{note['likes']} ❤️{note['saves']} 💬{note['comments']}", "ok")
    else:
        log(f"[dry-run] 会新建帖子: 「{note['title'][:25]}」", "info")
    return "created"


# ── 账号导入 ──────────────────────────────────────────────────

def import_account_stats(sb: Client, user: dict, account_id: int, dry_run: bool):
    """更新 accounts 表的粉丝数，并插入历史快照"""
    if dry_run:
        log(f"[dry-run] 会更新账号 {account_id} 粉丝数: {user['followers']}", "info")
        return

    snapshot_date = now_iso().split("T")[0]

    # 更新最新粉丝数
    sb.table("accounts").update({
        "followers":    user["followers"],
        "xhs_user_id":  user["xhs_user_id"],
    }).eq("id", account_id).execute()

    # 插入历史快照
    sb.table("account_stats_history").upsert({
        "account_id":  account_id,
        "xhs_user_id": user["xhs_user_id"],
        "date":        snapshot_date,
        "followers":   user["followers"],
        "following":   user["following"],
        "notes_count": user["notes_count"],
        "collected_at": now_iso(),
    }, on_conflict="account_id,date").execute()

    log(f"账号 {account_id} 粉丝数更新 → {user['followers']:,}", "ok")


# ── 读取 JSON 文件 ────────────────────────────────────────────

def load_json_files(directory: str) -> list[dict]:
    """扫描目录，读取所有 JSON 文件"""
    files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
    if not files:
        log(f"在 {directory} 下未找到 JSON 文件", "warn")
        return []

    all_data = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    all_data.extend(data)
                elif isinstance(data, dict):
                    all_data.append(data)
            log(f"读取文件: {os.path.basename(f)} ({len(data) if isinstance(data, list) else 1} 条)", "info")
        except json.JSONDecodeError as e:
            log(f"JSON 解析失败: {f} — {e}", "error")
    return all_data


# ── 记录日志 ──────────────────────────────────────────────────

def write_crawl_log(sb: Client, account_id: int, xhs_user_id: str,
                    status: str, notes_found: int, notes_updated: int,
                    error_msg: str, started_at: str):
    try:
        sb.table("crawl_logs").insert({
            "account_id":    account_id,
            "xhs_user_id":   xhs_user_id,
            "status":        status,
            "notes_found":   notes_found,
            "notes_updated": notes_updated,
            "error_msg":     error_msg,
            "started_at":    started_at,
            "finished_at":   now_iso(),
        }).execute()
    except Exception:
        pass  # 日志写入失败不影响主流程


# ── 主流程 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MediaCrawler → Supabase 数据同步")
    parser.add_argument("--file",    help="指定单个 JSON 文件路径")
    parser.add_argument("--dir",     help="指定 JSON 目录（覆盖 config 中的设置）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入数据库")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        log("=== DRY RUN 模式，不会写入数据库 ===", "warn")

    sb = get_client()

    # 读取数据
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        if isinstance(raw_data, dict):
            raw_data = [raw_data]
    else:
        data_dir = args.dir or MEDIACRAWLER_DATA_DIR
        raw_data = load_json_files(data_dir)

    if not raw_data:
        log("没有数据可导入", "warn")
        return

    log(f"共读取 {len(raw_data)} 条原始记录", "info")
    print()

    # 按 xhs_user_id 分组
    groups: dict[str, list] = {}
    for item in raw_data:
        uid = item.get("user_id") or item.get("author_id", "unknown")
        groups.setdefault(uid, []).append(item)

    total_updated = 0
    total_created = 0

    for xhs_user_id, items in groups.items():
        account_id = ACCOUNT_MAP.get(xhs_user_id)
        if not account_id:
            log(f"未映射的 XHS 用户 ID: {xhs_user_id}，跳过 {len(items)} 条", "skip")
            continue

        print(f"\n── 账号 {account_id} ({xhs_user_id}) ── {len(items)} 条笔记")
        started_at = now_iso()
        updated = created = 0
        error_msg = None

        try:
            for item in items:
                note = parse_note(item)
                result = import_note(sb, note, account_id, dry_run)
                if result == "updated":
                    updated += 1
                elif result == "created":
                    created += 1

            # 如果数据里包含用户信息，更新账号粉丝数
            if items and ("fans" in items[0] or "followers" in items[0]):
                user = parse_user(items[0])
                import_account_stats(sb, user, account_id, dry_run)

            total_updated += updated
            total_created += created

        except Exception as e:
            error_msg = str(e)
            log(f"账号 {account_id} 处理出错: {e}", "error")

        if not dry_run:
            write_crawl_log(sb, account_id, xhs_user_id,
                            "success" if not error_msg else "partial",
                            len(items), updated + created, error_msg, started_at)

    print()
    print("=" * 40)
    log(f"完成！更新 {total_updated} 条 · 新建 {total_created} 条", "ok")


if __name__ == "__main__":
    main()
