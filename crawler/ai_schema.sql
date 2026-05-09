-- ===============================================================
-- AI 功能基础设施 schema
-- 在 Supabase Dashboard → SQL Editor 里粘贴并执行
-- ===============================================================

-- pgvector 扩展
create extension if not exists vector;

-- ── 爆款帖子 embedding 字段 ──────────────────────────────────────
-- voyage-3-lite 输出 512 维（如果换模型，记得同步修改 ai_api.py 中的 EMBED_DIM）
alter table viral_posts add column if not exists embedding vector(512);

alter table viral_posts add column if not exists embed_status text
  default 'pending'
  check (embed_status in ('pending', 'done', 'error'));

alter table viral_posts add column if not exists embed_retry_count int default 0;

-- HNSW 部分索引（只索引已 embed 的记录，未 embed 不占索引空间）
create index if not exists viral_posts_embedding_idx
  on viral_posts using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

-- 把已抓取但还没 embed 的旧数据置为 pending，worker 会自然处理
update viral_posts
set embed_status = 'pending'
where embedding is null
  and fetch_status = 'done'
  and embed_status is distinct from 'pending';

-- ── 检索 RPC 函数 ────────────────────────────────────────────────
-- Supabase 客户端通过 sb.rpc('search_viral_posts', ...) 调用
create or replace function search_viral_posts(
    query_embedding vector(512),
    top_k int default 10
)
returns table (
    id uuid,
    title text,
    caption text,
    cover_image text,
    images text[],
    tags text[],
    author_name text,
    likes int,
    saves int,
    comments int,
    views int,
    url text,
    similarity float
)
language sql stable as $$
    select
        v.id,
        v.title,
        v.caption,
        v.cover_image,
        v.images,
        v.tags,
        v.author_name,
        v.likes,
        v.saves,
        v.comments,
        v.views,
        v.url,
        (1 - (v.embedding <=> query_embedding))::float as similarity
    from viral_posts v
    where v.embedding is not null and v.fetch_status = 'done'
    order by v.embedding <=> query_embedding
    limit top_k
$$;

-- ===============================================================
-- AI 搜索中心 schema（追加）
-- 在 Supabase Dashboard -> SQL Editor 中粘贴并执行
-- ===============================================================

create table if not exists knowledge_items (
  id uuid primary key default gen_random_uuid(),
  source_type text not null check (source_type in (
    'viral_post',
    'benchmark_account',
    'benchmark_post',
    'topic',
    'title',
    'team_post',
    'account',
    'banned_word'
  )),
  source_id text not null,
  source_key text not null,
  parent_source_type text,
  parent_source_id text,
  source_url text,
  title text not null default '',
  content text not null default '',
  summary text,
  tags text[] default '{}',
  country text,
  account_id integer,
  language text not null default 'zh' check (language in ('zh', 'en', 'mixed')),
  content_type text,
  likes_count bigint,
  saves_count bigint,
  comments_count bigint,
  views_count bigint,
  metrics_extra jsonb not null default '{}'::jsonb,
  image_urls text[] default '{}',
  embedding vector(512),
  embedding_model_version text,
  embed_status text not null default 'pending' check (embed_status in ('pending', 'processing', 'completed', 'failed')),
  embed_error text,
  retry_count integer not null default 0,
  is_active boolean not null default true,
  published_at timestamptz,
  source_updated_at timestamptz,
  content_hash text,
  last_indexed_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(source_type, source_key)
);

create index if not exists knowledge_items_embedding_hnsw
  on knowledge_items using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create index if not exists idx_knowledge_items_source_active
  on knowledge_items(source_type, is_active);

create index if not exists idx_knowledge_items_country_active
  on knowledge_items(country, is_active);

create index if not exists idx_knowledge_items_account
  on knowledge_items(account_id);

create index if not exists idx_knowledge_items_tags
  on knowledge_items using gin(tags);

create index if not exists idx_knowledge_items_embed_status
  on knowledge_items(embed_status, retry_count)
  where embed_status = 'pending';

alter table knowledge_items enable row level security;
create policy "team_access" on knowledge_items for all using (true) with check (true);

create table if not exists ai_research_notes (
  id uuid primary key default gen_random_uuid(),
  user_question text not null,
  image_url text,
  conclusion text,
  recommendations jsonb not null default '[]'::jsonb,
  material_references jsonb not null default '[]'::jsonb,
  team_history_references jsonb not null default '[]'::jsonb,
  image_analysis jsonb,
  full_payload jsonb not null default '{}'::jsonb,
  user_note text,
  creator_id uuid,
  visibility text not null default 'team' check (visibility in ('team')),
  created_at timestamptz default now()
);

alter table ai_research_notes enable row level security;
create policy "team_access" on ai_research_notes for all using (true) with check (true);

create table if not exists ai_research_feedback (
  id uuid primary key default gen_random_uuid(),
  note_id uuid references ai_research_notes(id) on delete set null,
  question text not null,
  rating text not null check (rating in ('up', 'down')),
  reason text check (reason in ('结论错', '引用不支持', '不相关', '不够具体')),
  created_at timestamptz default now()
);

alter table ai_research_feedback enable row level security;
create policy "team_access" on ai_research_feedback for all using (true) with check (true);

create or replace function match_knowledge_items(
  query_embedding vector(512),
  match_count integer default 30,
  source_types text[] default null,
  country_filter text default null
)
returns table (
  id uuid,
  source_type text,
  source_id text,
  source_key text,
  parent_source_type text,
  parent_source_id text,
  source_url text,
  title text,
  content text,
  summary text,
  tags text[],
  country text,
  account_id integer,
  language text,
  content_type text,
  likes_count bigint,
  saves_count bigint,
  comments_count bigint,
  views_count bigint,
  metrics_extra jsonb,
  image_urls text[],
  published_at timestamptz,
  similarity float
)
language sql stable as $$
  select
    k.id,
    k.source_type,
    k.source_id,
    k.source_key,
    k.parent_source_type,
    k.parent_source_id,
    k.source_url,
    k.title,
    k.content,
    k.summary,
    k.tags,
    k.country,
    k.account_id,
    k.language,
    k.content_type,
    k.likes_count,
    k.saves_count,
    k.comments_count,
    k.views_count,
    k.metrics_extra,
    k.image_urls,
    k.published_at,
    (1 - (k.embedding <=> query_embedding))::float as similarity
  from knowledge_items k
  where k.is_active = true
    and k.embedding is not null
    and (source_types is null or k.source_type = any(source_types))
    and (country_filter is null or k.country = country_filter)
  order by k.embedding <=> query_embedding
  limit match_count
$$;
