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
AGENT_RUNTIME_ENABLED = True

# 允许跨域的前端来源（开发 + 生产，按需增减）
AI_API_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# ── AI 搜索中心：生成与图片理解 ─────────────────────────────────
# LLM_PROVIDER 可选：gemini / openai / auto。模型供应商密钥只放后端，不放前端 .env。
# 不配置任何模型供应商 key 时，/ai/research 会返回基于检索结果的保守 fallback 答案。
LLM_PROVIDER = "auto"

# Gemini 3（Google AI Studio API key）
GEMINI_API_KEY = ""
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_TEXT_MODEL = "gemini-3-pro-preview"
GEMINI_VISION_MODEL = "gemini-3-pro-preview"

# OpenAI 备用配置
OPENAI_API_KEY = ""
OPENAI_TEXT_MODEL = "gpt-4.1-mini"
OPENAI_VISION_MODEL = "gpt-4.1-mini"

# 检索阈值，可根据 golden set 调整。
# AI_RESEARCH_MIN_SIMILARITY 用 voyage-3-lite 余弦相似度衡量；
# RRF 分数与之不可比，is_sparse_result 内部已分开判定。
AI_RESEARCH_MIN_RESULTS = 3
AI_RESEARCH_MIN_SIMILARITY = 0.55

# ── AI 外部发现闭环 ─────────────────────────────────────────────
# 默认关闭。确认 schema、AI API、爬虫搜索能力都可用后再打开。
EXTERNAL_DISCOVERY_ENABLED = False

# ask_first: AI 先给内部回答，用户点击后才创建发现任务。
# auto_after_sparse: 内部匹配不足时自动创建发现任务，但候选仍需人工审核才能入库。
EXTERNAL_DISCOVERY_TRIGGER_MODE = "ask_first"

# 每个发现任务的爬取上限。先保守，避免影响小红书登录态和风控。
EXTERNAL_DISCOVERY_MAX_QUERIES = 4
EXTERNAL_DISCOVERY_MAX_KEYWORD_RESULTS = 20
EXTERNAL_DISCOVERY_MAX_BENCHMARK_ACCOUNTS = 3
EXTERNAL_DISCOVERY_MAX_POSTS_PER_BENCHMARK = 10
EXTERNAL_DISCOVERY_MAX_CANDIDATES = 30
EXTERNAL_DISCOVERY_REQUEST_DELAY_SECONDS = 2

# 24 小时内相似搜索复用已有 job，减少重复爬取。
EXTERNAL_DISCOVERY_REUSE_WINDOW_HOURS = 24
