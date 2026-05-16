import { useState, useEffect, useRef } from "react";
import { Plus, X, Trash2, ExternalLink, RefreshCw, Heart, Bookmark, MessageCircle, Eye, Search, Copy, Check } from "lucide-react";
import { supabase } from "../supabase.js";
import {
  inputStyle, useIsMobile, Card, EmptyState, Skeleton, useToast,
  createGlassCardStyle, createPrimaryButtonStyle, designTokens,
} from "./shared.jsx";
import ViralPostDrawer from "./ViralPostDrawer.jsx";

const VIRAL_POST_COLUMNS = [
  "id",
  "url",
  "note",
  "country",
  "fetch_status",
  "created_at",
  "fetched_at",
  "xhs_note_id",
  "title",
  "caption",
  "cover_image",
  "images",
  "tags",
  "author_name",
  "likes",
  "saves",
  "comments",
  "views",
].join(", ");

const TOPIC_TAGS = ["申请时间线", "选校避坑", "语言备考", "offer晒单", "被拒复盘", "申请焦虑", "海外日常"];
const TAG_COLOR = {
  "申请时间线": "#54A0FF", "选校避坑": "#FF9F43", "语言备考": "#A29BFE",
  "offer晒单": "#26DE81", "被拒复盘": "#FF7A7A", "申请焦虑": "#FF2442", "海外日常": "#00CFCF",
};
const COUNTRIES = ["英国", "美国", "澳洲", "加拿大", "新加坡", "香港"];
const COUNTRY_COLOR = {
  "英国": "#FF7A7A", "美国": "#A29BFE", "澳洲": "#FF9F43",
  "加拿大": "#54A0FF", "新加坡": "#26DE81", "香港": "#FF2442",
};

function fmt(n) {
  if (!n) return "0";
  if (n >= 10000) return (n / 10000).toFixed(1) + "w";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function Empty({ text }) {
  return <EmptyState title={text} description="添加内容后，这里会自动更新为团队可复用素材。" />;
}

function LibrarySearch({ value, onChange, placeholder = "搜索素材…" }) {
  return (
    <div style={{ position: "relative", marginBottom: 14 }}>
      <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: designTokens.color.textFaint }} />
      <input
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
        style={{ ...inputStyle, paddingLeft: 34 }}
      />
    </div>
  );
}

/* ── 状态标签 ── */
function FetchBadge({ status }) {
  const map = {
    pending: { label: "等待中", color: "#FF9F43" },
    loading: { label: "抓取中", color: "#54A0FF" },
    done:    { label: "已同步", color: "#26DE81" },
    error:   { label: "抓取失败", color: "#FF4444" },
    idle:    null,
  };
  const s = map[status];
  if (!s) return null;
  return (
    <span style={{
      fontSize: 10, padding: "2px 8px", borderRadius: 10,
      background: `${s.color}22`, color: s.color, border: `1px solid ${s.color}44`,
      display: "inline-flex", alignItems: "center", gap: 4,
    }}>
      {status === "loading" && <RefreshCw size={9} style={{ animation: "spin 1s linear infinite" }} />}
      {s.label}
    </span>
  );
}

/* ── Stat chip ── */
function Stat({ icon, value, color = "#666" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 12, color }}>
      {icon}{fmt(value)}
    </div>
  );
}

/* ─────────────────────────────────
   Tab 1: 对标账号库
───────────────────────────────── */
function BenchmarkTab() {
  const isMobile = useIsMobile();
  const [rows, setRows]         = useState([]);
  const [loading, setLoading]   = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm]         = useState({ xhs_url: "", destination: "", content_type: "", note_direction: "", consumer_words: "" });
  const [saving, setSaving]     = useState(false);
  const [expandedAll, setExpandedAll] = useState({}); // accountId → bool (show all 10 posts)
  const [selectedPost, setSelectedPost] = useState(null); // benchmark post for drawer
  const [search, setSearch] = useState("");

  useEffect(() => {
    load();
    // Realtime 订阅：自动更新抓取结果
    const sub = supabase
      .channel("benchmark_accounts_changes")
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "benchmark_accounts" }, payload => {
        setRows(prev => prev.map(r => r.id === payload.new.id ? { ...r, ...payload.new } : r));
      })
      .subscribe();
    return () => supabase.removeChannel(sub);
  }, []);

  const load = async () => {
    const { data } = await supabase.from("benchmark_accounts").select("*").order("created_at", { ascending: false });
    if (data) setRows(data);
    setLoading(false);
  };

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const handleAdd = async () => {
    const url = form.xhs_url.trim();
    if (!url) { alert("请填写小红书账号链接"); return; }
    setSaving(true);
    const payload = {
      xhs_url:       url,
      destination:   form.destination.trim() || null,
      content_type:  form.content_type.trim() || null,
      note_direction: form.note_direction.trim() || null,
      consumer_words: form.consumer_words.trim() || null,
      name:          "加载中…",
      fetch_status:  "pending",
    };
    const { data, error } = await supabase.from("benchmark_accounts").insert([payload]).select().single();
    setSaving(false);
    if (error) { alert("添加失败：" + error.message); return; }
    setRows(p => [data, ...p]);
    setForm({ xhs_url: "", destination: "", content_type: "", note_direction: "", consumer_words: "" });
    setShowForm(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("确定删除这条记录？")) return;
    const { error } = await supabase.from("benchmark_accounts").delete().eq("id", id);
    if (error) { alert("删除失败：" + error.message); return; }
    setRows(p => p.filter(r => r.id !== id));
  };

  const handleRetry = async (row) => {
    await supabase.from("benchmark_accounts").update({ fetch_status: "pending" }).eq("id", row.id);
    setRows(p => p.map(r => r.id === row.id ? { ...r, fetch_status: "pending" } : r));
  };

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  const filteredRows = rows.filter(row => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return [row.name, row.destination, row.content_type, row.note_direction, row.consumer_words]
      .filter(Boolean)
      .some(value => String(value).toLowerCase().includes(q));
  });

  return (
    <div>
      {/* CSS spin animation */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: "#444" }}>
          粘贴账号链接，爬虫自动抓取账号信息和最近10条帖子
        </span>
        <button onClick={() => setShowForm(p => !p)} style={{
          display: "flex", alignItems: "center", gap: 7,
          padding: "8px 16px", background: showForm ? "#333" : "#FF2442",
          color: "#fff", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          <Plus size={14} /> 添加账号
        </button>
      </div>
      <LibrarySearch value={search} onChange={setSearch} placeholder="搜索账号、目的地、内容类型…" />

      {/* 添加表单 */}
      {showForm && (
        <div style={{ background: "#0d0d0d", border: "1px solid #2a2a2a", borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>小红书账号主页链接 *</label>
            <input
              value={form.xhs_url}
              onChange={e => f("xhs_url", e.target.value)}
              placeholder="https://www.xiaohongshu.com/user/profile/xxx?xsec_token=…（需带 xsec_token）"
              style={inputStyle}
            />
            <div style={{ fontSize: 10, color: "#444", marginTop: 4 }}>
              在 PC 端登录小红书，打开账号主页，复制地址栏完整链接
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 10, marginBottom: 12 }}>
            {[
              { key: "destination",   label: "目的地方向（可选）",   placeholder: "英国 / 美国 / 澳洲…" },
              { key: "content_type",  label: "主要内容类型（可选）", placeholder: "申请日记 / 海外日常…" },
              { key: "note_direction",label: "好的笔记方向（可选）", placeholder: "选校攻略 / 语言备考…" },
              { key: "consumer_words",label: "评论区消费词（可选）", placeholder: "求问 / 同款…" },
            ].map(c => (
              <div key={c.key}>
                <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>{c.label}</label>
                <input value={form[c.key]} onChange={e => f(c.key, e.target.value)}
                  placeholder={c.placeholder} style={{ ...inputStyle, padding: "7px 10px" }} />
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={() => { setShowForm(false); setForm({ xhs_url: "", destination: "", content_type: "", note_direction: "", consumer_words: "" }); }} style={{
              padding: "8px 16px", background: "transparent", border: "1px solid #2a2a2a",
              borderRadius: 7, color: "#666", fontSize: 13, cursor: "pointer",
            }}>取消</button>
            <button onClick={handleAdd} disabled={saving} style={{
              padding: "8px 16px", background: saving ? "#555" : "#FF2442",
              border: "none", borderRadius: 7, color: "#fff", fontSize: 13,
              fontWeight: 600, cursor: saving ? "not-allowed" : "pointer",
            }}>{saving ? "添加中…" : "添加"}</button>
          </div>
        </div>
      )}

      {/* 帖子详情抽屉 */}
      {selectedPost && <ViralPostDrawer post={selectedPost} onClose={() => setSelectedPost(null)} />}

      {/* 账号卡片列表 */}
      {filteredRows.length === 0 ? <Empty text={rows.length === 0 ? "暂无对标账号，点击「添加账号」并粘贴小红书链接" : "没有符合条件的对标账号"} /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {filteredRows.map(row => {
            const isExpandedAll = !!expandedAll[row.id];
            const recentPosts = Array.isArray(row.recent_posts) ? row.recent_posts : [];
            const visiblePosts = isExpandedAll ? recentPosts : recentPosts.slice(0, 5);

            return (
              <div key={row.id} style={{ ...createGlassCardStyle({ padding: 0 }), overflow: "hidden" }}>
                {/* 账号头部 */}
                <div style={{ padding: "16px 18px", display: "flex", alignItems: "flex-start", gap: 14 }}>
                  {/* 头像 */}
                  <div style={{ flexShrink: 0 }}>
                    {row.avatar_url ? (
                      <img src={row.avatar_url} alt="" style={{ width: 48, height: 48, borderRadius: "50%", objectFit: "cover", background: "#222" }} />
                    ) : (
                      <div style={{ width: 48, height: 48, borderRadius: "50%", background: "#222", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "#444" }}>
                        {row.name?.[0] || "?"}
                      </div>
                    )}
                  </div>

                  {/* 账号信息 */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                      <span style={{ fontSize: 15, fontWeight: 600, color: "#e0e0e0" }}>{row.name}</span>
                      <FetchBadge status={row.fetch_status} />
                    </div>
                    {row.followers > 0 && (
                      <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                        {fmt(row.followers)} 粉丝
                      </div>
                    )}
                    {row.bio && (
                      <div style={{ fontSize: 12, color: "#555", lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                        {row.bio}
                      </div>
                    )}
                    {/* 人工标注字段 */}
                    {(row.destination || row.content_type) && (
                      <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                        {row.destination && <span style={{ fontSize: 11, color: "#54A0FF", background: "#54A0FF18", padding: "2px 8px", borderRadius: 10, border: "1px solid #54A0FF33" }}>{row.destination}</span>}
                        {row.content_type && <span style={{ fontSize: 11, color: "#FF9F43", background: "#FF9F4318", padding: "2px 8px", borderRadius: 10, border: "1px solid #FF9F4333" }}>{row.content_type}</span>}
                      </div>
                    )}
                    {row.fetch_status === "error" && (
                      <button onClick={() => handleRetry(row)} style={{ marginTop: 6, fontSize: 11, color: "#FF9F43", background: "none", border: "1px solid #FF9F4344", borderRadius: 6, padding: "3px 10px", cursor: "pointer" }}>
                        重试抓取
                      </button>
                    )}
                    {row.fetch_status === "done" && (
                      <button onClick={() => handleRetry(row)} style={{ marginTop: 6, fontSize: 11, color: "#555", background: "none", border: "1px solid #2a2a2a", borderRadius: 6, padding: "3px 10px", cursor: "pointer" }}
                        onMouseEnter={e => e.currentTarget.style.color = "#aaa"}
                        onMouseLeave={e => e.currentTarget.style.color = "#555"}
                      >
                        刷新数据
                      </button>
                    )}
                  </div>

                  {/* 操作 */}
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0 }}>
                    {row.xhs_url && (
                      <a
                        href={row.xhs_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="打开对标账号主页"
                        title="打开对标账号主页"
                        style={{ color: "#555", display: "flex", alignItems: "center" }}
                      >
                        <ExternalLink size={13} />
                      </a>
                    )}
                    <button
                      onClick={() => handleDelete(row.id)}
                      aria-label="删除对标账号"
                      title="删除对标账号"
                      style={{ background: "none", border: "none", color: "#333", cursor: "pointer", padding: 2 }}
                      onMouseEnter={e => e.currentTarget.style.color = "#FF4444"}
                      onMouseLeave={e => e.currentTarget.style.color = "#333"}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {/* 最近帖子网格 — 默认显示5条，可展开全部 */}
                {row.fetch_status === "done" && recentPosts.length > 0 && (
                  <div style={{ borderTop: "1px solid #1a1a1a", padding: "12px 18px" }}>
                    <div style={{ fontSize: 11, color: "#444", marginBottom: 10, fontWeight: 500 }}>最近帖子</div>
                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(3, 1fr)" : "repeat(5, 1fr)", gap: 8 }}>
                      {visiblePosts.map((p, i) => (
                        <div
                          key={i}
                          onClick={() => setSelectedPost({
                            images: Array.isArray(p.images) && p.images.length > 0 ? p.images : (p.cover_image ? [p.cover_image] : []),
                            cover_image: p.cover_image,
                            title: p.title,
                            likes: p.likes,
                            saves: p.saves,
                            comments: p.comments,
                            views: p.views,
                            url: p.note_id ? `https://www.xiaohongshu.com/explore/${p.note_id}` : null,
                            xhs_note_id: p.note_id,
                            author_name: row.name,
                            tags: p.tags || [],
                            caption: p.caption || "",
                          })}
                          style={{ display: "block", cursor: "pointer" }}
                        >
                          <div style={{ aspectRatio: "3/4", borderRadius: 8, overflow: "hidden", background: "#1a1a1a", position: "relative" }}>
                            {p.cover_image ? (
                              <img src={p.cover_image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                            ) : (
                              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#2a2a2a", fontSize: 20 }}>📝</div>
                            )}
                            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to bottom, transparent 50%, rgba(0,0,0,0.85) 100%)" }} />
                            <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "6px 8px" }}>
                              <div style={{ fontSize: 10, color: "#fff", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", lineHeight: 1.4, marginBottom: 3 }}>
                                {p.title || "无标题"}
                              </div>
                              {p.likes > 0 && (
                                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.6)", display: "flex", alignItems: "center", gap: 3 }}>
                                  <Heart size={8} /> {fmt(p.likes)}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    {recentPosts.length > 5 && (
                      <button
                        onClick={() => setExpandedAll(p => ({ ...p, [row.id]: !p[row.id] }))}
                        style={{ marginTop: 10, width: "100%", padding: "8px 0", background: "transparent", border: "1px solid #2a2a2a", borderRadius: 8, color: "#555", fontSize: 12, cursor: "pointer" }}
                        onMouseEnter={e => e.currentTarget.style.color = "#aaa"}
                        onMouseLeave={e => e.currentTarget.style.color = "#555"}
                      >
                        {isExpandedAll ? "收起" : `查看全部 ${recentPosts.length} 条帖子`}
                      </button>
                    )}
                  </div>
                )}

                {/* Loading skeleton for recent posts */}
                {(row.fetch_status === "pending" || row.fetch_status === "loading") && (
                  <div style={{ borderTop: "1px solid #1a1a1a", padding: "12px 18px" }}>
                    <div style={{ fontSize: 11, color: "#444", marginBottom: 10 }}>正在抓取最近帖子…</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} style={{ aspectRatio: "3/4", borderRadius: 8, background: "#1a1a1a", animation: "pulse 1.5s ease-in-out infinite" }} />
                      ))}
                    </div>
                    <style>{`@keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:.7} }`}</style>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────
   Tab 2: 选题库
───────────────────────────────── */
function TopicsTab() {
  const isMobile = useIsMobile();
  const [items, setItems]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState("全部");
  const [search, setSearch]     = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm]         = useState({ description: "", tag: TOPIC_TAGS[0], reference_url: "" });
  const [saving, setSaving]     = useState(false);

  useEffect(() => {
    load();
    const sub = supabase
      .channel("topics_changes")
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "topics" }, payload => {
        setItems(prev => prev.map(i => i.id === payload.new.id ? { ...i, ...payload.new } : i));
      })
      .subscribe();
    return () => supabase.removeChannel(sub);
  }, []);

  const load = async () => {
    const { data } = await supabase.from("topics").select("*").order("created_at", { ascending: false });
    if (data) setItems(data);
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!form.description.trim()) { alert("请填写选题描述"); return; }
    setSaving(true);
    const refUrl = form.reference_url.trim() || null;
    const { data, error } = await supabase.from("topics").insert([{
      description: form.description.trim(),
      tag: form.tag,
      reference_url: refUrl,
      fetch_status: refUrl && refUrl.includes("xiaohongshu.com") ? "pending" : "idle",
    }]).select().single();
    setSaving(false);
    if (error) { alert("添加失败：" + error.message); return; }
    setItems(p => [data, ...p]);
    setForm({ description: "", tag: TOPIC_TAGS[0], reference_url: "" });
    setShowForm(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("确定删除？")) return;
    const { error } = await supabase.from("topics").delete().eq("id", id);
    if (error) { alert("删除失败：" + error.message); return; }
    setItems(p => p.filter(i => i.id !== id));
  };

  const filtered = (filter === "全部" ? items : items.filter(i => i.tag === filter))
    .filter(item => !search.trim() || [item.description, item.tag].filter(Boolean).some(value => String(value).toLowerCase().includes(search.trim().toLowerCase())));

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {["全部", ...TOPIC_TAGS].map(t => {
            const color = TAG_COLOR[t];
            const active = filter === t;
            return (
              <button key={t} onClick={() => setFilter(t)} style={{
                padding: "5px 12px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                border: `1px solid ${active ? (color || "#FF2442") : "#2a2a2a"}`,
                background: active ? (color ? `${color}22` : "rgba(255,36,66,0.1)") : "transparent",
                color: active ? (color || "#FF2442") : "#555",
                fontWeight: active ? 600 : 400,
              }}>{t}</button>
            );
          })}
        </div>
        <button onClick={() => setShowForm(p => !p)} style={{
          display: "flex", alignItems: "center", gap: 7, flexShrink: 0,
          padding: "8px 16px", background: showForm ? "#333" : "#FF2442",
          color: "#fff", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          <Plus size={14} /> 新增选题
        </button>
      </div>
      <LibrarySearch value={search} onChange={setSearch} placeholder="搜索选题描述或标签…" />

      {showForm && (
        <div style={{ background: "#0d0d0d", border: "1px solid #2a2a2a", borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ marginBottom: 10 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>选题方向描述 *</label>
            <textarea rows={2} value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="描述这个选题方向的核心内容…" style={{ ...inputStyle, resize: "vertical" }} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>参考帖子链接（可选，自动监控数据）</label>
            <input value={form.reference_url} onChange={e => setForm(p => ({ ...p, reference_url: e.target.value }))}
              placeholder="https://www.xiaohongshu.com/explore/…?xsec_token=…" style={inputStyle} />
            <div style={{ fontSize: 10, color: "#444", marginTop: 3 }}>填写小红书帖子链接，爬虫自动抓取点赞/收藏/浏览数据</div>
          </div>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 7 }}>类型标签</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {TOPIC_TAGS.map(t => {
                const color = TAG_COLOR[t];
                const active = form.tag === t;
                return (
                  <button key={t} onClick={() => setForm(p => ({ ...p, tag: t }))} style={{
                    padding: "5px 12px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                    border: `1px solid ${active ? color : "#2a2a2a"}`,
                    background: active ? `${color}22` : "transparent",
                    color: active ? color : "#555",
                  }}>{t}</button>
                );
              })}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={() => setShowForm(false)} style={{
              padding: "8px 16px", background: "transparent", border: "1px solid #2a2a2a",
              borderRadius: 7, color: "#666", fontSize: 13, cursor: "pointer",
            }}>取消</button>
            <button onClick={handleAdd} disabled={saving} style={{
              padding: "8px 16px", background: saving ? "#555" : "#FF2442",
              border: "none", borderRadius: 7, color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: saving ? "not-allowed" : "pointer",
            }}>{saving ? "保存中…" : "保存"}</button>
          </div>
        </div>
      )}

      {filtered.length === 0 ? <Empty text="暂无选题记录" /> : (
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 10 }}>
          {filtered.map(item => {
            const color = TAG_COLOR[item.tag] || "#555";
            const hasStats = item.ref_likes > 0 || item.ref_saves > 0 || item.ref_views > 0;
            return (
              <div key={item.id} style={{
                ...createGlassCardStyle({ padding: "14px 16px", radius: 10 }),
                borderLeft: `3px solid ${color}`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                  <p style={{ fontSize: 13, color: "#ddd", lineHeight: 1.65, margin: 0, flex: 1 }}>{item.description}</p>
                  <button
                    onClick={() => handleDelete(item.id)}
                    aria-label="删除选题"
                    title="删除选题"
                    style={{ background: "none", border: "none", color: "#333", cursor: "pointer", padding: 2, flexShrink: 0 }}
                    onMouseEnter={e => e.currentTarget.style.color = "#FF4444"}
                    onMouseLeave={e => e.currentTarget.style.color = "#333"}>
                    <Trash2 size={14} />
                  </button>
                </div>

                {/* 参考帖子数据 */}
                {item.reference_url && (
                  <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <a href={item.reference_url} target="_blank" rel="noopener noreferrer" style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      fontSize: 11, color: "#FF2442", textDecoration: "none",
                    }}>
                      <ExternalLink size={10} /> 参考帖子
                    </a>
                    {hasStats && (
                      <div style={{ display: "flex", gap: 10 }}>
                        <Stat icon={<Heart size={10} />} value={item.ref_likes} color="#FF7A7A" />
                        <Stat icon={<Bookmark size={10} />} value={item.ref_saves} color="#A29BFE" />
                        <Stat icon={<Eye size={10} />} value={item.ref_views} color="#888" />
                      </div>
                    )}
                    {item.fetch_status === "pending" || item.fetch_status === "loading" ? (
                      <FetchBadge status={item.fetch_status} />
                    ) : null}
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
                  <span style={{
                    fontSize: 11, padding: "2px 10px", borderRadius: 20,
                    background: `${color}18`, color: color, border: `1px solid ${color}44`,
                  }}>{item.tag}</span>
                  <span style={{ fontSize: 11, color: "#333" }}>
                    {new Date(item.created_at).toLocaleDateString("zh-CN")}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────
   Tab 3: 标题库
───────────────────────────────── */
function TitlesTab() {
  const [items, setItems]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [input, setInput]     = useState("");
  const [saving, setSaving]   = useState(false);
  const [search, setSearch]   = useState("");
  const [copiedId, setCopiedId] = useState(null);
  const toast = useToast();

  useEffect(() => { load(); }, []);

  const load = async () => {
    const { data } = await supabase.from("titles").select("*").order("created_at", { ascending: false });
    if (data) setItems(data);
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!input.trim()) return;
    setSaving(true);
    const { data, error } = await supabase.from("titles").insert([{ title: input.trim() }]).select().single();
    setSaving(false);
    if (error) { alert("添加失败：" + error.message); return; }
    setItems(p => [data, ...p]);
    setInput("");
  };

  const handleDelete = async (id) => {
    if (!window.confirm("确定删除？")) return;
    const { error } = await supabase.from("titles").delete().eq("id", id);
    if (error) { alert("删除失败：" + error.message); return; }
    setItems(p => p.filter(i => i.id !== id));
  };
  const handleCopy = async item => {
    try {
      await navigator.clipboard.writeText(item.title);
      setCopiedId(item.id);
      toast("标题已复制");
      window.setTimeout(() => setCopiedId(null), 1200);
    } catch {
      alert("复制失败，请手动选择标题后复制。");
    }
  };

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  const filteredItems = items.filter(item => !search.trim() || item.title.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div>
      <LibrarySearch value={search} onChange={setSearch} placeholder="搜索标题关键词…" />
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAdd()}
          placeholder="输入标题，按 Enter 或点击添加…"
          style={{ ...inputStyle, flex: 1 }}
        />
        <button onClick={handleAdd} disabled={saving || !input.trim()} style={{
          padding: "0 18px", background: input.trim() ? "#FF2442" : "#222",
          border: "none", borderRadius: 8, color: input.trim() ? "#fff" : "#444",
          fontSize: 13, fontWeight: 600, cursor: input.trim() ? "pointer" : "not-allowed",
          flexShrink: 0,
        }}>添加</button>
      </div>

      {filteredItems.length === 0 ? <Empty text={items.length === 0 ? "暂无标题记录" : "没有符合条件的标题"} /> : (
        <div style={{ ...createGlassCardStyle({ padding: 0, radius: 10 }), overflow: "hidden" }}>
          {filteredItems.map((item, i) => (
            <div key={item.id} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "13px 16px",
              background: i % 2 === 0 ? "rgba(255,255,255,0.018)" : "rgba(255,255,255,0.032)",
              borderBottom: i < filteredItems.length - 1 ? "1px solid rgba(255,255,255,0.045)" : "none",
            }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.055)"}
              onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? "rgba(255,255,255,0.018)" : "rgba(255,255,255,0.032)"}
            >
              <span style={{ flex: 1, fontSize: 13, color: "#ddd", lineHeight: 1.5 }}>{item.title}</span>
              <span style={{ fontSize: 11, color: "#333", flexShrink: 0 }}>{new Date(item.created_at).toLocaleDateString("zh-CN")}</span>
              <button
                onClick={() => handleCopy(item)}
                aria-label="复制标题"
                title="复制标题"
                style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${designTokens.color.cardBorder}`, borderRadius: 8, color: copiedId === item.id ? "#26DE81" : "#888", cursor: "pointer", padding: 6, flexShrink: 0, display: "flex" }}
              >
                {copiedId === item.id ? <Check size={13} /> : <Copy size={13} />}
              </button>
              <button
                onClick={() => handleDelete(item.id)}
                aria-label="删除标题"
                title="删除标题"
                style={{ background: "none", border: "none", color: "#333", cursor: "pointer", padding: 4, flexShrink: 0 }}
                onMouseEnter={e => e.currentTarget.style.color = "#FF4444"}
                onMouseLeave={e => e.currentTarget.style.color = "#333"}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 10, fontSize: 11, color: "#333", textAlign: "right" }}>{filteredItems.length} / {items.length} 条标题</div>
    </div>
  );
}

/* ─────────────────────────────────
   Tab 4: 违禁词记录
───────────────────────────────── */
function BannedWordsTab() {
  const [items, setItems]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [input, setInput]     = useState("");
  const [saving, setSaving]   = useState(false);
  const [search, setSearch]   = useState("");

  useEffect(() => { load(); }, []);

  const load = async () => {
    const { data } = await supabase.from("banned_words").select("*").order("created_at", { ascending: false });
    if (data) setItems(data);
    setLoading(false);
  };

  const handleAdd = async () => {
    const word = input.trim();
    if (!word) return;
    if (items.some(i => i.word === word)) { alert("该词已存在"); return; }
    setSaving(true);
    const { data, error } = await supabase.from("banned_words").insert([{ word }]).select().single();
    setSaving(false);
    if (error) { alert("添加失败：" + error.message); return; }
    setItems(p => [data, ...p]);
    setInput("");
  };

  const handleDelete = async (id) => {
    if (!window.confirm("确定删除这个违禁词？")) return;
    const { error } = await supabase.from("banned_words").delete().eq("id", id);
    if (error) { alert("删除失败：" + error.message); return; }
    setItems(p => p.filter(i => i.id !== id));
  };

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;
  const filteredItems = items.filter(item => !search.trim() || item.word.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div>
      <LibrarySearch value={search} onChange={setSearch} placeholder="搜索违禁词…" />
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAdd()}
          placeholder="输入违禁词，按 Enter 添加…"
          style={{ ...inputStyle, flex: 1 }}
        />
        <button onClick={handleAdd} disabled={saving || !input.trim()} style={{
          padding: "0 18px", background: input.trim() ? "#FF2442" : "#222",
          border: "none", borderRadius: 8, color: input.trim() ? "#fff" : "#444",
          fontSize: 13, fontWeight: 600, cursor: input.trim() ? "pointer" : "not-allowed",
          flexShrink: 0,
        }}>添加</button>
      </div>

      {filteredItems.length === 0 ? <Empty text={items.length === 0 ? "暂无违禁词记录" : "没有符合条件的违禁词"} /> : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {filteredItems.map(item => (
              <div key={item.id} style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "6px 12px", borderRadius: 20,
                background: "rgba(255,36,66,0.1)", border: "1px solid rgba(255,36,66,0.25)",
              }}>
                <span style={{ fontSize: 13, color: "#FF2442", fontWeight: 500 }}>{item.word}</span>
                <button
                  onClick={() => handleDelete(item.id)}
                  aria-label="删除违禁词"
                  title="删除违禁词"
                  style={{
                  background: "none", border: "none", color: "rgba(255,36,66,0.5)",
                  cursor: "pointer", padding: 0, display: "flex", alignItems: "center",
                }}
                  onMouseEnter={e => e.currentTarget.style.color = "#FF2442"}
                  onMouseLeave={e => e.currentTarget.style.color = "rgba(255,36,66,0.5)"}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 14, fontSize: 11, color: "#333" }}>{filteredItems.length} / {items.length} 个违禁词</div>
        </>
      )}
    </div>
  );
}

/* ─────────────────────────────────
   Tab 5: 爆款收藏
───────────────────────────────── */
function ViralPostsTab() {
  const isMobile = useIsMobile();
  const [items, setItems]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState("全部");
  const [search, setSearch]     = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm]         = useState({ url: "", note: "", country: COUNTRIES[0] });
  const [saving, setSaving]     = useState(false);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    load();
    // Realtime 订阅：爬虫更新数据时自动刷新卡片
    const sub = supabase
      .channel("viral_posts_changes")
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "viral_posts" }, payload => {
        const { embedding, ...next } = payload.new;
        setItems(prev => prev.map(i => i.id === next.id ? { ...i, ...next } : i));
      })
      .subscribe();
    return () => supabase.removeChannel(sub);
  }, []);

  const load = async () => {
    const { data } = await supabase.from("viral_posts").select(VIRAL_POST_COLUMNS).order("created_at", { ascending: false });
    if (data) setItems(data);
    setLoading(false);
  };

  const handleAdd = async () => {
    const url = form.url.trim();
    if (!url) { alert("请填写帖子链接"); return; }
    setSaving(true);
    const { data, error } = await supabase.from("viral_posts").insert([{
      url,
      note: form.note.trim() || null,
      country: form.country,
      fetch_status: "pending",  // 触发爬虫
    }]).select().single();
    setSaving(false);
    if (error) { alert("添加失败：" + error.message); return; }
    setItems(p => [data, ...p]);
    setForm({ url: "", note: "", country: COUNTRIES[0] });
    setShowForm(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("确定删除？")) return;
    const { error } = await supabase.from("viral_posts").delete().eq("id", id);
    if (error) { alert("删除失败：" + error.message); return; }
    setItems(p => p.filter(i => i.id !== id));
  };

  const handleRetry = async (id) => {
    await supabase.from("viral_posts").update({ fetch_status: "pending" }).eq("id", id);
    setItems(p => p.map(i => i.id === id ? { ...i, fetch_status: "pending" } : i));
  };

  const filtered = (filter === "全部" ? items : items.filter(i => i.country === filter))
    .filter(item => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return [item.title, item.caption, item.note, item.author_name, item.country]
        .filter(Boolean)
        .some(value => String(value).toLowerCase().includes(q));
    });

  if (loading) return <div style={{ color: "#444", padding: 24 }}>加载中…</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {["全部", ...COUNTRIES].map(c => {
            const color = COUNTRY_COLOR[c];
            const active = filter === c;
            return (
              <button key={c} onClick={() => setFilter(c)} style={{
                padding: "5px 12px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                border: `1px solid ${active ? (color || "#FF2442") : "#2a2a2a"}`,
                background: active ? (color ? `${color}22` : "rgba(255,36,66,0.1)") : "transparent",
                color: active ? (color || "#FF2442") : "#555",
                fontWeight: active ? 600 : 400,
              }}>{c}</button>
            );
          })}
        </div>
        <button onClick={() => setShowForm(p => !p)} style={{
          display: "flex", alignItems: "center", gap: 7, flexShrink: 0,
          padding: "8px 16px", background: showForm ? "#333" : "#FF2442",
          color: "#fff", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          <Plus size={14} /> 添加收藏
        </button>
      </div>
      <LibrarySearch value={search} onChange={setSearch} placeholder="搜索标题、作者、备注…" />

      {/* 添加表单 */}
      {showForm && (
        <div style={{ background: "#0d0d0d", border: "1px solid #2a2a2a", borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ marginBottom: 10 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>帖子链接 *</label>
            <input value={form.url} onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
              placeholder="小红书帖子链接（短链或完整链接均可）" style={inputStyle} />
            <div style={{ fontSize: 10, color: "#444", marginTop: 3 }}>支持 xhslink.com 短链，爬虫自动抓取标题、封面图、数据</div>
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 5 }}>备注说明（可选）</label>
            <input value={form.note} onChange={e => setForm(p => ({ ...p, note: e.target.value }))}
              placeholder="为什么觉得这条不错？" style={inputStyle} />
          </div>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 11, color: "#555", marginBottom: 7 }}>目的地标签</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {COUNTRIES.map(c => {
                const color = COUNTRY_COLOR[c];
                const active = form.country === c;
                return (
                  <button key={c} onClick={() => setForm(p => ({ ...p, country: c }))} style={{
                    padding: "5px 12px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                    border: `1px solid ${active ? color : "#2a2a2a"}`,
                    background: active ? `${color}22` : "transparent",
                    color: active ? color : "#555",
                  }}>{c}</button>
                );
              })}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={() => setShowForm(false)} style={{
              padding: "8px 16px", background: "transparent", border: "1px solid #2a2a2a",
              borderRadius: 7, color: "#666", fontSize: 13, cursor: "pointer",
            }}>取消</button>
            <button onClick={handleAdd} disabled={saving} style={{
              padding: "8px 16px", background: saving ? "#555" : "#FF2442",
              border: "none", borderRadius: 7, color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: saving ? "not-allowed" : "pointer",
            }}>{saving ? "保存中…" : "保存"}</button>
          </div>
        </div>
      )}

      {/* 帖子卡片网格 */}
      {selected && <ViralPostDrawer post={selected} onClose={() => setSelected(null)} />}

      {filtered.length === 0 ? <Empty text="暂无收藏帖子" /> : (
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(3, 1fr)", gap: 12 }}>
          {filtered.map(item => {
            const color = COUNTRY_COLOR[item.country] || "#555";
            const isLoading = item.fetch_status === "pending" || item.fetch_status === "loading";
            const isDone = item.fetch_status === "done";
            const isError = item.fetch_status === "error";

            return (
              <div key={item.id} style={{ ...createGlassCardStyle({ padding: 0 }), overflow: "hidden" }}>
                {/* 封面图 — 点击打开详情 */}
                <div onClick={() => item.fetch_status === "done" && setSelected(item)}
                  style={{ aspectRatio: "3/4", position: "relative", background: "#1a1a1a", cursor: item.fetch_status === "done" ? "pointer" : "default" }}>
                  {item.cover_image ? (
                    <img src={item.cover_image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  ) : isLoading ? (
                    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
                      <RefreshCw size={20} color="#333" style={{ animation: "spin 1s linear infinite" }} />
                      <span style={{ fontSize: 11, color: "#444" }}>正在抓取…</span>
                    </div>
                  ) : (
                    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 28 }}>📌</span>
                    </div>
                  )}

                  {/* 渐变遮罩 + 底部信息 */}
                  {(item.title || isDone) && (
                    <>
                      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to bottom, transparent 40%, rgba(0,0,0,0.9) 100%)" }} />
                      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "10px 12px" }}>
                        {item.title && (
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#fff", lineHeight: 1.4, marginBottom: 6, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                            {item.title}
                          </div>
                        )}
                        {isDone && (item.likes > 0 || item.saves > 0) && (
                          <div style={{ display: "flex", gap: 10 }}>
                            <Stat icon={<Heart size={10} />} value={item.likes} color="rgba(255,255,255,0.7)" />
                            <Stat icon={<Bookmark size={10} />} value={item.saves} color="rgba(255,255,255,0.7)" />
                            <Stat icon={<MessageCircle size={10} />} value={item.comments} color="rgba(255,255,255,0.7)" />
                            {item.views > 0 && <Stat icon={<Eye size={10} />} value={item.views} color="rgba(255,255,255,0.7)" />}
                          </div>
                        )}
                      </div>
                    </>
                  )}

                  {/* 国家标签 */}
                  <div style={{ position: "absolute", top: 8, left: 8 }}>
                    <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: `${color}cc`, color: "#fff", fontWeight: 600 }}>{item.country}</span>
                  </div>

                  {/* 删除按钮 */}
                  <button
                    onClick={event => {
                      event.stopPropagation();
                      handleDelete(item.id);
                    }}
                    aria-label="删除收藏帖子"
                    title="删除收藏帖子"
                    style={{
                    position: "absolute", top: 6, right: 6,
                    background: "rgba(0,0,0,0.6)", border: "none", borderRadius: "50%",
                    width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
                    color: "#aaa", cursor: "pointer",
                  }}
                    onMouseEnter={e => e.currentTarget.style.color = "#FF4444"}
                    onMouseLeave={e => e.currentTarget.style.color = "#aaa"}
                  >
                    <X size={12} />
                  </button>
                </div>

                {/* 卡片底部 */}
                <div style={{ padding: "10px 12px" }}>
                  {item.author_name && (
                    <div style={{ fontSize: 11, color: "#555", marginBottom: 4 }}>@{item.author_name}</div>
                  )}
                  {item.note && (
                    <div style={{ fontSize: 11, color: "#888", lineHeight: 1.5, marginBottom: 6 }}>{item.note}</div>
                  )}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <FetchBadge status={isError ? "error" : isLoading ? item.fetch_status : null} />
                      {isError && (
                        <button onClick={() => handleRetry(item.id)} style={{ fontSize: 10, color: "#FF9F43", background: "none", border: "1px solid #FF9F4344", borderRadius: 6, padding: "2px 8px", cursor: "pointer" }}>
                          重试
                        </button>
                      )}
                    </div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="打开原帖"
                        title="打开原帖"
                        style={{ color: "#444", display: "flex" }}
                      >
                        <ExternalLink size={12} />
                      </a>
                      <span style={{ fontSize: 10, color: "#333" }}>{new Date(item.created_at).toLocaleDateString("zh-CN")}</span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────
   主组件
───────────────────────────────── */
const TABS = ["对标账号库", "选题库", "标题库", "违禁词记录", "爆款收藏"];

export default function MaterialPage() {
  const isMobile = useIsMobile();
  const [tab, setTab] = useState(0);

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1100 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ ...designTokens.type.pageTitle, margin: 0 }}>素材库</h1>
        <p style={{ color: "#555", fontSize: 13, margin: "5px 0 0" }}>
          对标账号、选题方向、标题灵感、违禁词、爆款收藏 · 粘贴小红书链接自动抓取数据
        </p>
      </div>

      <div style={{
        display: "flex", gap: 18, marginBottom: 24,
        borderBottom: `1px solid ${designTokens.color.cardBorder}`,
        overflowX: "auto",
      }}>
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setTab(i)} style={{
            flex: isMobile ? "0 0 auto" : 1,
            position: "relative",
            padding: isMobile ? "10px 4px 12px" : "10px 0 12px",
            borderRadius: 0, border: "none", cursor: "pointer",
            background: "transparent",
            color: tab === i ? "#fff" : designTokens.color.textMuted,
            fontSize: 13, fontWeight: tab === i ? 600 : 400,
            whiteSpace: "nowrap", transition: "all 0.1s",
          }}>
            {t}
            <span style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: -1,
              height: 2,
              borderRadius: 2,
              background: tab === i ? designTokens.color.brandGradient : "transparent",
              boxShadow: tab === i ? designTokens.color.brandGlow : "none",
              transition: "background 200ms ease",
            }} />
          </button>
        ))}
      </div>

      {tab === 0 && <BenchmarkTab />}
      {tab === 1 && <TopicsTab />}
      {tab === 2 && <TitlesTab />}
      {tab === 3 && <BannedWordsTab />}
      {tab === 4 && <ViralPostsTab />}
    </div>
  );
}
