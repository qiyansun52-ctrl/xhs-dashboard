-- ================================================================
-- XHS 管理台 · 爬虫数据表结构
-- 在 Supabase SQL Editor 中完整执行一次
-- ================================================================

-- 1. accounts 表新增 XHS 用户 ID（用于关联爬虫数据）
--    从小红书主页 URL 获取：xiaohongshu.com/user/profile/{xhs_user_id}
alter table accounts add column if not exists xhs_user_id text unique;

-- 2. posts 表新增 XHS 笔记 ID（用于关联爬虫数据）
--    从笔记 URL 获取：xiaohongshu.com/explore/{xhs_note_id}
alter table posts add column if not exists xhs_note_id text unique;

-- 3. post_stats 扩展（存最新一次的数据，供首页快速读取）
alter table post_stats add column if not exists shares     integer default 0;
alter table post_stats add column if not exists updated_at timestamp with time zone default now();

-- 4. 帖子数据历史快照（每次爬取存一行，用于画趋势图）
create table if not exists post_stats_history (
  id           uuid    primary key default gen_random_uuid(),
  post_id      uuid    references posts(id) on delete cascade,
  xhs_note_id  text,                        -- 冗余存一份，方便查询
  likes        integer default 0,
  saves        integer default 0,
  comments     integer default 0,
  views        integer default 0,
  shares       integer default 0,
  collected_at timestamp with time zone default now()
);
create index if not exists idx_psh_post_id      on post_stats_history(post_id);
create index if not exists idx_psh_collected_at on post_stats_history(collected_at);
create index if not exists idx_psh_note_id      on post_stats_history(xhs_note_id);
alter table post_stats_history enable row level security;
create policy "team_access" on post_stats_history for all using (true) with check (true);

-- 5. 账号数据历史快照（每次爬取存一行）
create table if not exists account_stats_history (
  id           uuid    primary key default gen_random_uuid(),
  account_id   integer not null,
  xhs_user_id  text,
  date         date,
  followers    integer default 0,
  likes        integer default 0,
  views        integer default 0,
  saves        integer default 0,
  following    integer default 0,
  notes_count  integer default 0,
  collected_at timestamp with time zone default now()
);
alter table account_stats_history add column if not exists date date;
alter table account_stats_history add column if not exists likes integer default 0;
alter table account_stats_history add column if not exists views integer default 0;
alter table account_stats_history add column if not exists saves integer default 0;
create index if not exists idx_ash_account_id   on account_stats_history(account_id);
create index if not exists idx_ash_collected_at on account_stats_history(collected_at);
create unique index if not exists idx_ash_account_date_unique on account_stats_history(account_id, date);
alter table account_stats_history enable row level security;
create policy "team_access" on account_stats_history for all using (true) with check (true);

-- 6. 对标账号粉丝历史快照（每天一条）
create table if not exists benchmark_stats_history (
  id           uuid    primary key default gen_random_uuid(),
  benchmark_id uuid    not null,
  date         date    not null,
  followers    integer default 0,
  collected_at timestamp with time zone default now()
);
create index if not exists idx_bsh_benchmark_id   on benchmark_stats_history(benchmark_id);
create index if not exists idx_bsh_collected_at   on benchmark_stats_history(collected_at);
create unique index if not exists idx_bsh_benchmark_date_unique on benchmark_stats_history(benchmark_id, date);
alter table benchmark_stats_history enable row level security;
create policy "team_access" on benchmark_stats_history for all using (true) with check (true);

-- 6. 爬取日志（记录每次运行结果，方便排查问题）
create table if not exists crawl_logs (
  id           uuid primary key default gen_random_uuid(),
  account_id   integer,
  xhs_user_id  text,
  status       text check (status in ('success', 'failed', 'partial')) default 'success',
  notes_found  integer default 0,
  notes_updated integer default 0,
  error_msg    text,
  started_at   timestamp with time zone default now(),
  finished_at  timestamp with time zone
);
alter table crawl_logs enable row level security;
create policy "team_access" on crawl_logs for all using (true) with check (true);
