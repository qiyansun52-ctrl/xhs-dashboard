# ================================================================
# 爬虫配置模板 — 复制为 config.py 后填入真实值
# config.py 已在 .gitignore 中，不会提交到仓库
# ================================================================

# ── Supabase 连接 ──────────────────────────────────────────────
SUPABASE_URL = "https://<your-project-id>.supabase.co"
SUPABASE_KEY = "sb_publishable_xxxxxxxxxxxxxxxxxxxxxxxxxx"

# ── 账号映射：XHS 用户 ID → 管理台内部 account_id ──────────────
# 如何找 xhs_user_id：
#   打开小红书 PC 端，进入账号主页
#   URL 格式：xiaohongshu.com/user/profile/{xhs_user_id}
#   复制最后那段 ID
ACCOUNT_MAP = {
    # "665c45cb000000000700713c": 7,
    # "69d636e30000000026000aec": 9,
}

# ── MediaCrawler 输出目录 ─────────────────────────────────────
# MediaCrawler 默认把数据存在自己的 data/ 目录下，填绝对路径
MEDIACRAWLER_DATA_DIR = "/Users/<you>/MediaCrawler/data/xhs"

# ── 爬取设置 ──────────────────────────────────────────────────
# 每个账号最多抓取多少条笔记（避免封号，建议 ≤ 50）
MAX_NOTES_PER_ACCOUNT = 30

# 两次请求之间的间隔秒数（模拟人工，降低风控风险）
REQUEST_DELAY_SECONDS = 2

# ── AI API 服务（ai_api.py 使用）──────────────────────────────
# Voyage AI（embedding 模型，注册：https://dash.voyageai.com）
VOYAGE_API_KEY = "pa-xxxxxxxxxxxxxxxxxxxxxxxxxx"

# 前后端共享的内部 API key，前端通过 VITE_AI_API_KEY 传同一个值
# 随便生成一段长字符串即可（python -c "import secrets; print(secrets.token_urlsafe(32))"）
AI_API_KEY = "change-me-to-a-long-random-string"

# AI API 监听地址（默认本地 8001，避免与其他服务冲突）
AI_API_HOST = "127.0.0.1"
AI_API_PORT = 8001

# 允许跨域的前端来源（开发 + 生产，按需增减）
AI_API_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# ── AI 搜索中心：生成与图片理解 ─────────────────────────────────
# 不配置 OPENAI_API_KEY 时，/ai/research 会返回基于检索结果的保守 fallback 答案
OPENAI_API_KEY = ""
OPENAI_TEXT_MODEL = "gpt-4.1-mini"
OPENAI_VISION_MODEL = "gpt-4.1-mini"

# 检索阈值，可根据 golden set 调整。
# AI_RESEARCH_MIN_SIMILARITY 用 voyage-3-lite 余弦相似度衡量；
# RRF 分数与之不可比，is_sparse_result 内部已分开判定。
AI_RESEARCH_MIN_RESULTS = 3
AI_RESEARCH_MIN_SIMILARITY = 0.55
