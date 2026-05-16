import { useState, useEffect, useMemo } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { supabase } from "../supabase.js";
import { Avatar, Badge, Card, EmptyState, Skeleton, designTokens, useIsMobile } from "./shared.jsx";
import PostDetailDrawer from "./PostDetailDrawer.jsx";

const WEEKDAYS  = ["一", "二", "三", "四", "五", "六", "日"];
const MONTH_ZH  = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];
const STATUS_COLOR = { draft: "#555", scheduled: "#FF9F43", published: "#26DE81" };

/** "2025-04-07T10:30" → "2025-04-07" */
function toDateKey(str) {
  if (!str) return null;
  return str.replace("T", " ").slice(0, 10);
}

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

/** 生成当月日历格（6行×7列，包含前后月补位） */
function buildCalendar(year, month) {
  const first = new Date(year, month, 1);
  const last  = new Date(year, month + 1, 0);
  const startDow = (first.getDay() + 6) % 7; // 周一=0
  const days = [];

  for (let i = startDow - 1; i >= 0; i--) {
    days.push({ date: new Date(year, month, -i), cur: false });
  }
  for (let i = 1; i <= last.getDate(); i++) {
    days.push({ date: new Date(year, month, i), cur: true });
  }
  while (days.length < 42) {
    days.push({ date: new Date(year, month + 1, days.length - last.getDate() - startDow + 1), cur: false });
  }
  return days;
}

function fmtKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
}

/* ── 今日摘要条 ── */
function TodayBanner({ posts, accounts, onSelect }) {
  const today = todayKey();
  const todayPosts = posts.filter(p => toDateKey(p.scheduled_at || p.scheduledAt) === today);
  if (!todayPosts.length) return null;

  return (
    <div style={{
      background: "rgba(255,36,66,0.06)", border: "1px solid rgba(255,36,66,0.18)",
      borderRadius: 10, padding: "12px 16px", marginBottom: 20,
      display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10,
    }}>
      <span style={{ fontSize: 12, color: "#FF2442", fontWeight: 600, flexShrink: 0 }}>
        今日待发布 {todayPosts.length} 条
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {todayPosts.map(p => {
          const acc = accounts.find(a => a.id === (p.account_id ?? p.accountId));
          return (
            <div key={p.id} onClick={() => onSelect(p)} style={{
              display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
              background: acc ? `${acc.color}22` : "#1a1a1a",
              border: `1px solid ${acc?.color || "#333"}44`,
              borderRadius: 20, padding: "4px 10px",
            }}>
              {acc && <Avatar acc={acc} size={16} />}
              <span style={{ fontSize: 11, color: "#ddd", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.title}
              </span>
              <Badge status={p.status} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── 桌面日历格 ── */
function DesktopCalendar({ days, postsByDate, accounts, onSelect }) {
  const today = todayKey();
  const [hoveredKey, setHoveredKey] = useState(null);
  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      {/* 星期头 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", background: "rgba(255,255,255,0.025)" }}>
        {WEEKDAYS.map(d => (
          <div key={d} style={{ padding: "10px 0", textAlign: "center", fontSize: 11, color: "#444", fontWeight: 600, letterSpacing: "0.05em" }}>
            {d}
          </div>
        ))}
      </div>

      {/* 日期格 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)" }}>
        {days.map((day, idx) => {
          const key   = fmtKey(day.date);
          const posts = postsByDate[key] || [];
          const isToday = key === today;
          const isLast  = idx >= 35;

          return (
            <div
              key={idx}
              onMouseEnter={() => setHoveredKey(key)}
              onMouseLeave={() => setHoveredKey(null)}
              style={{
              position: "relative",
              minHeight: 110, padding: "8px 8px 6px",
              borderRight: (idx + 1) % 7 === 0 ? "none" : "1px solid rgba(255,255,255,0.045)",
              borderBottom: isLast ? "none" : "1px solid rgba(255,255,255,0.045)",
              background: isToday ? "rgba(255,36,66,0.04)" : "transparent",
              transition: "background 200ms ease",
            }}>
              {/* 日期数字 */}
              <div style={{
                width: 24, height: 24, borderRadius: "50%", marginBottom: 5,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: isToday ? "#FF2442" : "transparent",
                boxShadow: isToday ? "0 0 0 4px rgba(255,36,66,0.12), 0 0 18px rgba(255,36,66,0.35)" : "none",
                fontSize: 12, fontWeight: isToday ? 700 : 400,
                color: isToday ? "#fff" : day.cur ? "#888" : "#2a2a2a",
              }}>
                {day.date.getDate()}
              </div>

              {/* 帖子条目 */}
              {posts.slice(0, 3).map(p => {
                const acc = accounts.find(a => a.id === (p.account_id ?? p.accountId));
                return (
                  <div key={p.id} onClick={() => onSelect(p)} style={{
                    marginBottom: 3, padding: "3px 7px", borderRadius: 4,
                    background: acc ? `${acc.color}18` : "#1a1a1a",
                    borderLeft: `2px solid ${acc?.color || "#555"}`,
                    cursor: "pointer", display: "flex", alignItems: "center", gap: 4,
                    overflow: "hidden",
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = acc ? `${acc.color}30` : "#222"}
                    onMouseLeave={e => e.currentTarget.style.background = acc ? `${acc.color}18` : "#1a1a1a"}
                  >
                    <span style={{ fontSize: 10, color: STATUS_COLOR[p.status] || "#555", flexShrink: 0 }}>●</span>
                    <span style={{ fontSize: 11, color: "#bbb", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.title}
                    </span>
                  </div>
                );
              })}
              {posts.length > 3 && (
                <div style={{ fontSize: 10, color: "#444", paddingLeft: 2 }}>+{posts.length - 3} 条</div>
              )}
              {posts.length > 0 && (
                <div style={{ position: "absolute", left: 8, right: 8, bottom: 6, display: "flex", gap: 3, overflow: "hidden" }}>
                  {posts.slice(0, 6).map(p => {
                    const acc = accounts.find(a => a.id === (p.account_id ?? p.accountId));
                    return <span key={p.id} style={{ width: 5, height: 5, borderRadius: "50%", background: acc?.color || "#666", flexShrink: 0 }} />;
                  })}
                </div>
              )}
              {hoveredKey === key && posts.length > 0 && (
                <div style={{
                  position: "absolute",
                  left: 8,
                  right: 8,
                  top: 34,
                  zIndex: 5,
                  borderRadius: 10,
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(10,10,16,0.96)",
                  boxShadow: "0 12px 26px rgba(0,0,0,0.38)",
                  padding: 10,
                  pointerEvents: "none",
                  animation: "fadeIn 150ms ease",
                }}>
                  <div style={{ fontSize: 11, color: "#FF2442", fontWeight: 700, marginBottom: 6 }}>{posts.length} 条排期</div>
                  {posts.slice(0, 4).map(p => {
                    const acc = accounts.find(a => a.id === (p.account_id ?? p.accountId));
                    return (
                      <div key={p.id} style={{ fontSize: 11, color: "#ddd", lineHeight: 1.5, marginBottom: 4 }}>
                        <span style={{ color: acc?.color || "#888" }}>●</span> {p.title}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ── 手机列表视图 ── */
function MobileList({ days, postsByDate, accounts, onSelect }) {
  const today = todayKey();
  // 只显示有帖子的日期 + 今天
  const activeDays = days.filter(d => {
    const k = fmtKey(d.date);
    return postsByDate[k]?.length || k === today;
  });

  if (!activeDays.length) {
    return (
      <EmptyState title="本月暂无排期帖子" description="创建待发布内容后，日历会按日期自动聚合。" />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {activeDays.map(day => {
        const key   = fmtKey(day.date);
        const posts = postsByDate[key] || [];
        const isToday = key === today;

        return (
          <div key={key}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{
                width: 28, height: 28, borderRadius: "50%",
                background: isToday ? "#FF2442" : "#1a1a1a",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 12, fontWeight: 600, color: isToday ? "#fff" : "#666", flexShrink: 0,
              }}>{day.date.getDate()}</div>
              <span style={{ fontSize: 11, color: "#444" }}>
                {MONTH_ZH[day.date.getMonth()]} {WEEKDAYS[(day.date.getDay() + 6) % 7]}
                {isToday && <span style={{ color: "#FF2442", marginLeft: 6 }}>今天</span>}
              </span>
              {posts.length === 0 && <span style={{ fontSize: 11, color: "#2a2a2a" }}>无排期</span>}
            </div>

            {posts.map(p => {
              const acc = accounts.find(a => a.id === (p.account_id ?? p.accountId));
              return (
                <div key={p.id} onClick={() => onSelect(p)} style={{
                  marginLeft: 36, marginBottom: 6, padding: "10px 12px",
                  background: "rgba(255,255,255,0.03)", border: `1px solid ${designTokens.color.cardBorder}`,
                  boxShadow: designTokens.shadow.card,
                  borderLeft: `3px solid ${acc?.color || "#555"}`,
                  borderRadius: "0 8px 8px 0", cursor: "pointer",
                  display: "flex", alignItems: "center", gap: 10,
                }}>
                  {acc && <Avatar acc={acc} size={24} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "#e0e0e0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.title}
                    </div>
                    <div style={{ fontSize: 11, color: "#555", marginTop: 2 }}>
                      {(p.scheduled_at || p.scheduledAt)?.slice(11, 16)}
                      {acc && <span style={{ marginLeft: 8, color: acc.color }}>{acc.name}</span>}
                    </div>
                  </div>
                  <Badge status={p.status} />
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ── 主组件 ── */
export default function CalendarPage({ accounts, members }) {
  const isMobile = useIsMobile();
  const [now]          = useState(new Date());
  const [curDate, setCur] = useState(new Date());
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedPost, setSelected] = useState(null);

  const year  = curDate.getFullYear();
  const month = curDate.getMonth();

  useEffect(() => {
    fetchPosts();
    const ch = supabase.channel("calendar-posts")
      .on("postgres_changes", { event: "*", schema: "public", table: "posts" }, fetchPosts)
      .subscribe();
    return () => supabase.removeChannel(ch);
  }, []);

  const fetchPosts = async () => {
    const { data, error } = await supabase
      .from("posts").select("*").order("scheduled_at", { ascending: true });
    if (error) { console.error(error); return; }
    setPosts(data.map(p => ({ ...p, accountId: p.account_id, scheduledAt: p.scheduled_at })));
    setLoading(false);
  };

  const handleStatusChange = (id, status) => {
    setPosts(prev => prev.map(p => p.id === id ? { ...p, status } : p));
    setSelected(prev => prev?.id === id ? { ...prev, status } : prev);
  };

  const days = useMemo(() => buildCalendar(year, month), [year, month]);

  const postsByDate = useMemo(() => {
    const map = {};
    posts.forEach(p => {
      const k = toDateKey(p.scheduled_at || p.scheduledAt);
      if (!k) return;
      (map[k] = map[k] || []).push(p);
    });
    return map;
  }, [posts]);

  // 本月帖子统计
  const monthKey = `${year}-${String(month+1).padStart(2,"0")}`;
  const monthPosts    = posts.filter(p => (p.scheduled_at || p.scheduledAt || "").startsWith(monthKey));
  const scheduledCnt  = monthPosts.filter(p => p.status === "scheduled").length;
  const publishedCnt  = monthPosts.filter(p => p.status === "published").length;
  const draftCnt      = monthPosts.filter(p => p.status === "draft").length;

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1100 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ ...designTokens.type.pageTitle, margin: 0 }}>内容日历</h1>
          <p style={{ color: "#555", fontSize: 13, margin: "5px 0 0" }}>
            本月 {monthPosts.length} 条排期
            {scheduledCnt > 0 && <span style={{ color: "#FF9F43", marginLeft: 10 }}>·  待发布 {scheduledCnt}</span>}
            {publishedCnt > 0 && <span style={{ color: "#26DE81", marginLeft: 10 }}>·  已发布 {publishedCnt}</span>}
            {draftCnt > 0     && <span style={{ color: "#666",    marginLeft: 10 }}>·  草稿 {draftCnt}</span>}
          </p>
        </div>

        {/* Month navigation */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button onClick={() => setCur(new Date(year, month - 1, 1))} style={{
            width: 32, height: 32, border: "1px solid #2a2a2a", borderRadius: 7,
            background: "transparent", color: "#aaa", cursor: "pointer", fontSize: 16,
          }}>‹</button>
          <div style={{
            padding: "0 16px", fontSize: 14, fontWeight: 600, color: "#e0e0e0",
            minWidth: 120, textAlign: "center",
          }}>
            {year} 年 {MONTH_ZH[month]}
          </div>
          <button onClick={() => setCur(new Date(year, month + 1, 1))} style={{
            width: 32, height: 32, border: "1px solid #2a2a2a", borderRadius: 7,
            background: "transparent", color: "#aaa", cursor: "pointer", fontSize: 16,
          }}>›</button>
          <button
            onClick={() => setCur(new Date())}
            style={{
              marginLeft: 6, padding: "0 12px", height: 32,
              border: "1px solid #2a2a2a", borderRadius: 7,
              background: "transparent", color: "#666", fontSize: 12, cursor: "pointer",
            }}>
            今天
          </button>
        </div>
      </div>

      {/* Account legend */}
      {!isMobile && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 20 }}>
          {accounts.map(acc => (
            <div key={acc.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: acc.color }} />
              <span style={{ fontSize: 11, color: "#555" }}>{acc.flag} {acc.name}</span>
            </div>
          ))}
        </div>
      )}

      {/* Today banner */}
      <TodayBanner posts={posts} accounts={accounts} onSelect={setSelected} />

      {/* Calendar / List */}
      {loading ? (
        <Skeleton height={isMobile ? 220 : 520} radius={12} />
      ) : isMobile ? (
        <MobileList days={days} postsByDate={postsByDate} accounts={accounts} onSelect={setSelected} />
      ) : (
        <DesktopCalendar days={days} postsByDate={postsByDate} accounts={accounts} onSelect={setSelected} />
      )}

      {/* Post detail drawer */}
      {selectedPost && (
        <PostDetailDrawer
          post={selectedPost}
          accounts={accounts}
          members={members}
          onClose={() => setSelected(null)}
          onStatusChange={handleStatusChange}
        />
      )}
    </div>
  );
}
