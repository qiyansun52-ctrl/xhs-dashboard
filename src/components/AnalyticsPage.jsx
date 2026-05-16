import { useState, useEffect } from "react";
import { Users, Heart, Bookmark, MessageCircle, TrendingUp } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts";
import { supabase } from "../supabase.js";
import { Card, CountUpNumber, EmptyState, createGlassCardStyle, designTokens, useIsMobile } from "./shared.jsx";

const VIRAL_POST_COLUMNS = [
  "id",
  "title",
  "caption",
  "cover_image",
  "images",
  "country",
  "likes",
  "saves",
  "comments",
  "views",
  "fetch_status",
  "created_at",
].join(", ");

function fmt(n) {
  if (!n) return "0";
  if (n >= 10000) return (n / 10000).toFixed(1) + "w";
  if (n >= 1000)  return (n / 1000).toFixed(1)  + "k";
  return String(n);
}

const PALETTE = ["#FF2442", "#54A0FF", "#26DE81", "#FF9F43", "#A29BFE", "#FF7A7A", "#00CFCF"];
const COUNTRY_COLOR = {
  "英国": "#FF7A7A", "美国": "#A29BFE", "澳洲": "#FF9F43",
  "加拿大": "#54A0FF", "新加坡": "#26DE81", "香港": "#FF2442",
};

function fmtDate(s) {
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function StatCard({ label, value, rawValue, color = "#e0e0e0", sub }) {
  return (
    <Card style={{ padding: "14px 16px", borderRadius: 10 }}>
      <div style={{ fontSize: 11, color: "#444", marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {rawValue == null ? value : <CountUpNumber value={rawValue} />}
      </div>
      {sub && <div style={{ fontSize: 11, color: "#333", marginTop: 4 }}>{sub}</div>}
    </Card>
  );
}

const chartTooltipStyle = {
  contentStyle: { background: "#111", border: "1px solid #2a2a2a", borderRadius: 8, fontSize: 12 },
};

/* ─────────────────────────────────
   Tab 1: 自有账号
───────────────────────────────── */
function OwnAccountsTab({ accounts, rangeDays }) {
  const isMobile = useIsMobile();
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase
      .from("account_stats_history")
      .select("*")
      .order("date", { ascending: true })
      .then(({ data }) => { if (data) setHistory(data); setLoading(false); });
  }, []);

  // Merge history rows into chart format: [{ date, "账号A": 1000, "账号B": 2000 }, ...]
  const chartData = (() => {
    const map = {};
    history.forEach(row => {
      if (!map[row.date]) map[row.date] = { date: row.date };
      const acc = accounts.find(a => a.id === row.account_id);
      if (acc) map[row.date][acc.name] = row.followers;
    });
    const points = Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
    // If no history yet, show current values as single dot so chart isn't blank
    if (points.length === 0) {
      const today = new Date().toISOString().split("T")[0];
      const pt = { date: today };
      accounts.forEach(a => { pt[a.name] = a.followers || 0; });
      return [pt];
    }
    return points.slice(-rangeDays);
  })();

  const totals = {
    followers: accounts.reduce((s, a) => s + (a.followers || 0), 0),
    likes:     accounts.reduce((s, a) => s + (a.likes     || 0), 0),
    views:     accounts.reduce((s, a) => s + (a.views     || 0), 0),
    saves:     accounts.reduce((s, a) => s + (a.saves     || 0), 0),
  };

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  if (accounts.length === 0) return <EmptyState title="暂无账号数据" description="添加账号后，这里会展示粉丝增长和互动趋势。" />;

  return (
    <div>
      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${isMobile ? 2 : 4},1fr)`, gap: 12, marginBottom: 24 }}>
        <StatCard label="总粉丝" rawValue={totals.followers} color="#FF2442" />
        <StatCard label="总点赞" rawValue={totals.likes}     color="#FF7A7A" />
        <StatCard label="总浏览" rawValue={totals.views}     color="#54A0FF" />
        <StatCard label="总收藏" rawValue={totals.saves}     color="#A29BFE" />
      </div>

      {/* Followers trend */}
      <Card style={{ padding: "20px 20px 12px", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#666" }}>粉丝增长趋势</span>
          {history.length <= 1 && (
            <span style={{ fontSize: 11, color: "#333" }}>数据积累中，每天自动记录快照</span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "#444" }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={v => fmt(v)} tick={{ fontSize: 10, fill: "#444" }} axisLine={false} tickLine={false} width={42} />
            <Tooltip {...chartTooltipStyle} labelFormatter={fmtDate} formatter={(v, name) => [fmt(v), name]} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#555", paddingTop: 8 }} />
            {accounts.map((a, i) => (
              <Line key={a.id} type="monotone" dataKey={a.name}
                stroke={a.color || PALETTE[i % PALETTE.length]}
                strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </Card>

      {/* Per-account cards */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2,1fr)", gap: 12 }}>
        {accounts.map((acc, i) => (
          <Card key={acc.id} style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
              <div style={{
                width: 36, height: 36, borderRadius: "50%",
                background: acc.color || PALETTE[i % PALETTE.length],
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 15, fontWeight: 700, color: "#fff", flexShrink: 0,
              }}>{acc.name?.[0] || "?"}</div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0" }}>{acc.name}</div>
                {acc.country && <div style={{ fontSize: 11, color: "#555", marginTop: 1 }}>{acc.country}</div>}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
              {[
                { label: "粉丝", value: acc.followers, color: "#FF2442" },
                { label: "点赞", value: acc.likes,     color: "#FF7A7A" },
                { label: "浏览", value: acc.views,     color: "#54A0FF" },
                { label: "收藏", value: acc.saves,     color: "#A29BFE" },
              ].map(s => (
                <div key={s.label} style={{ background: "#161616", borderRadius: 8, padding: "10px 0", textAlign: "center" }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: s.color, fontVariantNumeric: "tabular-nums" }}>{fmt(s.value)}</div>
                  <div style={{ fontSize: 10, color: "#444", marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────
   Tab 2: 对标账号
───────────────────────────────── */
function BenchmarkTrendTab({ rangeDays }) {
  const isMobile = useIsMobile();
  const [benchmarks, setBenchmarks] = useState([]);
  const [history, setHistory]       = useState([]);
  const [loading, setLoading]       = useState(true);

  useEffect(() => {
    Promise.all([
      supabase.from("benchmark_accounts")
        .select("id, name, followers, avatar_url, destination")
        .eq("fetch_status", "done")
        .order("followers", { ascending: false }),
      supabase.from("benchmark_stats_history")
        .select("*")
        .order("date", { ascending: true }),
    ]).then(([{ data: b }, { data: h }]) => {
      if (b) setBenchmarks(b);
      if (h) setHistory(h);
      setLoading(false);
    });
  }, []);

  const chartData = (() => {
    const map = {};
    history.forEach(row => {
      if (!map[row.date]) map[row.date] = { date: row.date };
      const b = benchmarks.find(x => x.id === row.benchmark_id);
      if (b) map[row.date][b.name] = row.followers;
    });
    const points = Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
    if (points.length === 0) {
      const today = new Date().toISOString().split("T")[0];
      const pt = { date: today };
      benchmarks.forEach(b => { pt[b.name] = b.followers || 0; });
      return [pt];
    }
    return points.slice(-rangeDays);
  })();

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  if (benchmarks.length === 0) return (
    <EmptyState title="暂无对标账号数据" description="前往素材库添加对标账号后，这里会展示增长对比。" />
  );

  return (
    <div>
      {/* Trend chart */}
      <Card style={{ padding: "20px 20px 12px", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#666" }}>粉丝增长对比</span>
          {history.length <= 1 && <span style={{ fontSize: 11, color: "#333" }}>数据积累中，每天自动记录</span>}
        </div>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "#444" }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={v => fmt(v)} tick={{ fontSize: 10, fill: "#444" }} axisLine={false} tickLine={false} width={42} />
            <Tooltip {...chartTooltipStyle} labelFormatter={fmtDate} formatter={(v, name) => [fmt(v), name]} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#555", paddingTop: 8 }} />
            {benchmarks.slice(0, 6).map((b, i) => (
              <Line key={b.id} type="monotone" dataKey={b.name}
                stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </Card>

      {/* Ranking */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #1a1a1a", fontSize: 12, fontWeight: 600, color: "#666" }}>
          粉丝排行
        </div>
        {benchmarks.map((b, i) => (
          <div key={b.id} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "12px 18px", borderBottom: "1px solid #111",
          }}>
            <span style={{ width: 20, fontSize: 12, fontWeight: 700, color: i < 3 ? "#FF9F43" : "#333", textAlign: "center" }}>
              {i + 1}
            </span>
            {b.avatar_url
              ? <img src={b.avatar_url} alt="" style={{ width: 34, height: 34, borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} />
              : <div style={{ width: 34, height: 34, borderRadius: "50%", background: "#222", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "#444", flexShrink: 0 }}>{b.name?.[0]}</div>
            }
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: "#e0e0e0" }}>{b.name}</div>
              {b.destination && <div style={{ fontSize: 11, color: "#555" }}>{b.destination}</div>}
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#e0e0e0", fontVariantNumeric: "tabular-nums" }}>
              {fmt(b.followers)}
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

/* ─────────────────────────────────
   Tab 3: 爆款分析
───────────────────────────────── */
function ViralAnalyticsTab() {
  const isMobile = useIsMobile();
  const [posts, setPosts]   = useState([]);
  const [sortBy, setSortBy] = useState("likes");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.from("viral_posts").select(VIRAL_POST_COLUMNS).eq("fetch_status", "done")
      .then(({ data }) => { if (data) setPosts(data); setLoading(false); });
  }, []);

  const sorted = [...posts].sort((a, b) => (b[sortBy] || 0) - (a[sortBy] || 0));

  const avg = key => posts.length > 0
    ? Math.round(posts.reduce((s, p) => s + (p[key] || 0), 0) / posts.length)
    : 0;

  // Country breakdown
  const countryMap = {};
  posts.forEach(p => { if (p.country) countryMap[p.country] = (countryMap[p.country] || 0) + 1; });
  const countryData = Object.entries(countryMap)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  if (posts.length === 0) return (
    <EmptyState title="暂无爆款帖子数据" description="前往素材库添加爆款收藏后，这里会展示地区分布和 TOP 帖子。" />
  );

  return (
    <div>
      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${isMobile ? 2 : 4},1fr)`, gap: 12, marginBottom: 24 }}>
        <StatCard label="收录帖子" rawValue={posts.length}       color="#e0e0e0" />
        <StatCard label="平均点赞" rawValue={avg("likes")}  color="#FF7A7A" />
        <StatCard label="平均收藏" rawValue={avg("saves")}  color="#A29BFE" />
        <StatCard label="平均评论" rawValue={avg("comments")} color="#54A0FF" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "260px 1fr", gap: 16 }}>
        {/* Country breakdown */}
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#666", marginBottom: 14 }}>地区分布</div>
          {countryData.length === 0
            ? <div style={{ fontSize: 12, color: "#333" }}>暂无地区数据</div>
            : countryData.map(c => {
                const color = COUNTRY_COLOR[c.name] || "#888";
                const pct = Math.round(c.count / posts.length * 100);
                return (
                  <div key={c.name} style={{ marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                      <span style={{ fontSize: 12, color: "#888" }}>{c.name}</span>
                      <span style={{ fontSize: 11, color: "#555", fontVariantNumeric: "tabular-nums" }}>{c.count}篇 · {pct}%</span>
                    </div>
                    <div style={{ height: 4, borderRadius: 2, background: "#1a1a1a" }}>
                      <div style={{ height: "100%", borderRadius: 2, background: color, width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })
          }
        </Card>

        {/* Top posts */}
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "12px 18px", borderBottom: "1px solid #1a1a1a", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#666" }}>TOP 帖子</span>
            <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
              {[["likes","点赞"],["saves","收藏"],["comments","评论"]].map(([k, label]) => (
                <button key={k} onClick={() => setSortBy(k)} style={{
                  fontSize: 11, padding: "3px 10px", borderRadius: 20, cursor: "pointer",
                  border: `1px solid ${sortBy === k ? "#FF2442" : "#2a2a2a"}`,
                  background: sortBy === k ? "rgba(255,36,66,0.1)" : "transparent",
                  color: sortBy === k ? "#FF2442" : "#555",
                }}>{label}</button>
              ))}
            </div>
          </div>
          <div style={{ overflow: "auto", maxHeight: isMobile ? "none" : 420 }}>
            {sorted.slice(0, 15).map((p, i) => (
              <div key={p.id} style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 18px", borderBottom: "1px solid #0d0d0d",
              }}>
                <span style={{ width: 18, fontSize: 11, fontWeight: 700, color: i < 3 ? "#FF9F43" : "#333", textAlign: "center", flexShrink: 0 }}>
                  {i + 1}
                </span>
                {p.cover_image && (
                  <img src={p.cover_image} alt="" style={{ width: 34, height: 46, borderRadius: 6, objectFit: "cover", background: "#1a1a1a", flexShrink: 0 }} />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "#ccc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.title || "无标题"}
                  </div>
                  <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
                    <span style={{ fontSize: 11, color: "#FF7A7A" }}>❤ {fmt(p.likes)}</span>
                    <span style={{ fontSize: 11, color: "#A29BFE" }}>⭐ {fmt(p.saves)}</span>
                    {p.comments > 0 && <span style={{ fontSize: 11, color: "#54A0FF" }}>💬 {fmt(p.comments)}</span>}
                  </div>
                </div>
                {p.country && (
                  <span style={{
                    fontSize: 10, padding: "2px 7px", borderRadius: 8, flexShrink: 0,
                    background: `${COUNTRY_COLOR[p.country] || "#888"}22`,
                    color: COUNTRY_COLOR[p.country] || "#888",
                  }}>{p.country}</span>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ─────────────────────────────────
   Main
───────────────────────────────── */
export default function AnalyticsPage({ accounts }) {
  const isMobile = useIsMobile();
  const [tab, setTab] = useState("own");
  const [rangeDays, setRangeDays] = useState(30);

  const tabs = [
    { key: "own",       label: "自有账号" },
    { key: "benchmark", label: "对标账号" },
    { key: "viral",     label: "爆款分析" },
  ];

  return (
    <div style={{ padding: isMobile ? "16px" : "24px 32px" }}>
      <div style={{ marginBottom: 22 }}>
        <h1 style={{ ...designTokens.type.pageTitle, margin: "0 0 4px" }}>数据监控</h1>
        <p style={{ fontSize: 12, color: "#444", margin: 0 }}>账号增长趋势 · 对标动态 · 爆款内容分析</p>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,0.025)", padding: 4, borderRadius: 10, border: `1px solid ${designTokens.color.cardBorder}` }}>
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              padding: "7px 20px", borderRadius: 7, border: "none", cursor: "pointer",
              background: tab === t.key ? "rgba(255,36,66,0.12)" : "transparent",
              color: tab === t.key ? "#FF2442" : "#555",
              fontSize: 13, fontWeight: tab === t.key ? 600 : 400,
            }}>{t.label}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,0.025)", padding: 4, borderRadius: 10, border: `1px solid ${designTokens.color.cardBorder}` }}>
          {[7, 30, 90].map(days => (
            <button key={days} onClick={() => setRangeDays(days)} style={{
              padding: "7px 12px",
              borderRadius: 7,
              border: "none",
              background: rangeDays === days ? "rgba(255,255,255,0.09)" : "transparent",
              color: rangeDays === days ? "#fff" : designTokens.color.textMuted,
              cursor: "pointer",
              fontSize: 12,
              fontWeight: rangeDays === days ? 700 : 500,
            }}>{days}d</button>
          ))}
        </div>
      </div>

      {tab === "own"       && <OwnAccountsTab accounts={accounts} rangeDays={rangeDays} />}
      {tab === "benchmark" && <BenchmarkTrendTab rangeDays={rangeDays} />}
      {tab === "viral"     && <ViralAnalyticsTab />}
    </div>
  );
}
