import { Suspense, lazy, useState, useEffect } from "react";
import { FileText, Users2, CalendarDays, BookOpen, BarChart2, Plus, X, UserCircle, Sparkles } from "lucide-react";
import { supabase } from "./supabase.js";
import {
  ROLE_LABELS,
  Skeleton,
  ToastViewport,
  createGlassCardStyle,
  designTokens,
  inputStyle,
  useIsMobile,
} from "./components/shared.jsx";

const ContentManager = lazy(() => import("./components/ContentManager.jsx"));
const AccountsPage = lazy(() => import("./components/AccountsPage.jsx"));
const CalendarPage = lazy(() => import("./components/CalendarPage.jsx"));
const MaterialPage = lazy(() => import("./components/MaterialPage.jsx"));
const AnalyticsPage = lazy(() => import("./components/AnalyticsPage.jsx"));
const AIWorkbenchPage = lazy(() => import("./components/AIWorkbenchPage.jsx"));
const AISearchPage = lazy(() => import("./components/AISearchPage.jsx"));
const AgentPage = lazy(() => import("./components/AgentPage.jsx"));

const ACCOUNT_LIST_COLUMNS = [
  "id",
  "name",
  "avatar",
  "flag",
  "color",
  "xhs_link",
  "bio",
  "followers",
  "views",
  "likes",
  "saves",
  "created_at",
].join(", ");


function PageFallback({ isMobile }) {
  return (
    <div style={{ padding: isMobile ? 16 : 32 }}>
      <Skeleton height={90} radius={12} />
    </div>
  );
}


function JoinTeamModal({ onClose, onJoin }) {
  const isMobile = useIsMobile();
  const [form, setForm] = useState({ name: "", role: "operator" });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    if (!form.name.trim()) { alert("请填写姓名"); return; }
    setSaving(true);
    const { data, error } = await supabase
      .from("members")
      .insert([{ name: form.name.trim(), role: form.role }])
      .select().single();
    setSaving(false);
    if (error) { alert("加入失败：" + error.message); return; }
    onJoin(data);
    onClose();
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
      display: "flex",
      alignItems: isMobile ? "flex-end" : "center",
      justifyContent: "center", zIndex: 200,
    }}>
      <div style={{
        background: "#111", border: "1px solid #2a2a2a",
        borderRadius: isMobile ? "16px 16px 0 0" : 16,
        padding: isMobile ? "24px 20px 32px" : 32,
        width: isMobile ? "100%" : 380,
        paddingBottom: isMobile ? "calc(32px + env(safe-area-inset-bottom))" : 32,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: "#fff", margin: 0 }}>加入团队</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", padding: 4 }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>你的名字</label>
          <input
            value={form.name}
            onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
            onKeyDown={e => e.key === "Enter" && handleSubmit()}
            placeholder="e.g. 小红"
            style={inputStyle}
            autoFocus
          />
        </div>
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>角色</label>
          <div style={{ display: "flex", gap: 8 }}>
            {Object.entries(ROLE_LABELS).map(([k, v]) => (
              <button key={k} onClick={() => setForm(p => ({ ...p, role: k }))} style={{
                flex: 1, padding: "8px", borderRadius: 8, fontSize: 12, cursor: "pointer",
                border: `1px solid ${form.role === k ? "#FF2442" : "#2a2a2a"}`,
                background: form.role === k ? "rgba(255,36,66,0.1)" : "transparent",
                color: form.role === k ? "#FF2442" : "#666",
              }}>{v}</button>
            ))}
          </div>
        </div>
        <button onClick={handleSubmit} disabled={saving} style={{
          width: "100%", padding: "11px", border: "none", borderRadius: 8,
          fontSize: 14, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer",
          background: saving ? "#555" : "#FF2442", color: "#fff",
        }}>
          {saving ? "加入中…" : "加入团队"}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const isMobile = useIsMobile();
  const [view, setView]         = useState("accounts");
  const [aiMode, setAiMode]     = useState("workbench");
  const [hasOpenedAi, setHasOpenedAi] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const [members, setMembers]   = useState([]);
  const [showJoin, setShowJoin] = useState(false);
  const [hoveredNav, setHoveredNav] = useState(null);
  const [hoveredAccountId, setHoveredAccountId] = useState(null);
  const agentModeEnabled = String(import.meta.env.VITE_AGENT_RUNTIME_ENABLED || "true").toLowerCase() !== "false";
  const shouldRenderAi = hasOpenedAi || view === "ai";

  useEffect(() => {
    loadAccounts();
    loadMembers();
    const ch = supabase.channel("accounts-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "accounts" }, loadAccounts)
      .subscribe();
    return () => supabase.removeChannel(ch);
  }, []);

  useEffect(() => {
    if (view === "ai") setHasOpenedAi(true);
  }, [view]);

  const loadAccounts = async () => {
    const { data, error } = await supabase.from("accounts").select(ACCOUNT_LIST_COLUMNS).order("id");
    if (!error && data) setAccounts(data);
  };

  const loadMembers = async () => {
    const { data } = await supabase.from("members").select("*").order("created_at");
    if (data) setMembers(data);
  };

  const navItems = [
    { key: "accounts",  icon: <Users2 size={20} />,       label: "账号管理" },
    { key: "content",   icon: <FileText size={20} />,     label: "内容管理" },
    { key: "calendar",  icon: <CalendarDays size={20} />, label: "内容日历" },
    { key: "material",  icon: <BookOpen size={20} />,     label: "素材库"   },
    { key: "ai",        icon: <Sparkles size={20} />,     label: "AI 搜索"  },
    { key: "analytics", icon: <BarChart2 size={20} />,    label: "数据监控" },
  ];

  return (
    <div style={{
      fontFamily: "'DM Sans', system-ui, sans-serif",
      background: designTokens.color.pageBackground, color: designTokens.color.textPrimary,
      minHeight: "100vh", display: "flex",
      flexDirection: isMobile ? "column" : "row",
      }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { from { transform: translateY(8px); } to { transform: translateY(0); } }
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        @keyframes glowPulse { 0%, 100% { box-shadow: 0 0 0 4px rgba(255,36,66,0.08), 0 0 12px rgba(255,36,66,0.22); } 50% { box-shadow: 0 0 0 7px rgba(255,36,66,0.12), 0 0 22px rgba(255,36,66,0.42); } }
        @keyframes timelineEnter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>

      {/* ── Desktop sidebar ── */}
      {!isMobile && (
        <div style={{
          width: 230,
          background: designTokens.color.sidebarBackground,
          borderRight: "1px solid rgba(255,36,66,0.08)",
          display: "flex", flexDirection: "column", padding: "22px 0",
          flexShrink: 0, position: "sticky", top: 0, height: "100vh",
        }}>
          {/* Logo */}
          <div style={{ padding: "0 18px 22px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 30, height: 30, background: designTokens.color.brandGradient, boxShadow: designTokens.color.brandGlow, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700 }}>红</div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#fff" }}>XHS 管理台</div>
                <div style={{ fontSize: 10, color: designTokens.color.textFaint, marginTop: 1 }}>团队内部使用</div>
              </div>
            </div>
          </div>

          {/* Nav */}
          <div style={{ padding: "14px 10px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            {navItems.map(item => {
              const active = view === item.key;
              const hovering = hoveredNav === item.key;
              return (
              <button key={item.key} onClick={() => setView(item.key)}
                onMouseEnter={() => setHoveredNav(item.key)}
                onMouseLeave={() => setHoveredNav(null)}
                style={{
                width: "100%", display: "flex", alignItems: "center", gap: 9,
                padding: "9px 12px", borderRadius: 8,
                border: active ? "1px solid rgba(255,36,66,0.25)" : "1px solid transparent",
                cursor: "pointer",
                background: active ? "rgba(255,36,66,0.1)" : hovering ? "rgba(255,255,255,0.03)" : "transparent",
                color: active ? "#FF2442" : hovering ? "rgba(255,255,255,0.6)" : designTokens.color.textMuted,
                boxShadow: active ? "0 0 16px rgba(255,36,66,0.12) inset" : "none",
                fontSize: 13, fontWeight: active ? 600 : 400,
                marginBottom: 3, transition: "all 200ms ease", textAlign: "left",
              }}>
                <span style={{
                  display: "flex",
                  color: active ? "#FF2442" : "inherit",
                  filter: active ? "drop-shadow(0 0 6px rgba(255,36,66,0.6))" : "none",
                }}>
                  {item.icon}
                </span>
                {item.label}
              </button>
            );})}
          </div>

          {/* Account list */}
          <div style={{ padding: "14px 10px", flex: 1, overflow: "auto" }}>
            <div style={{ fontSize: 10, color: "#333", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, paddingLeft: 4 }}>账号</div>
            {accounts.map(acc => (
              <div key={acc.id} onClick={() => setView("accounts")}
                onMouseEnter={() => setHoveredAccountId(acc.id)}
                onMouseLeave={() => setHoveredAccountId(null)}
                style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "7px 8px", borderRadius: 6, cursor: "pointer", marginBottom: 2,
                background: hoveredAccountId === acc.id ? "rgba(255,255,255,0.03)" : "transparent",
                transition: "background 200ms ease",
              }}>
                <div style={{ width: 20, height: 20, borderRadius: "50%", background: acc.color, boxShadow: `${acc.color || "#FF2442"}55 0 0 8px`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>
                  {acc.avatar?.startsWith("http") ? (acc.name?.[0] || "?") : (acc.avatar || acc.name?.[0] || "?")}
                </div>
                <span style={{ fontSize: 12, color: hoveredAccountId === acc.id ? designTokens.color.textSecondary : designTokens.color.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{acc.name}</span>
              </div>
            ))}
          </div>

          {/* Team members */}
          <div style={{ padding: "12px 10px", borderTop: "1px solid #1a1a1a" }}>
            {members.slice(-4).map(m => (
              <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px" }}>
                <UserCircle size={14} color="#333" />
                <span style={{ fontSize: 11, color: "#555", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{m.name}</span>
                <span style={{ fontSize: 9, color: "#2a2a2a", flexShrink: 0 }}>{ROLE_LABELS[m.role] || m.role}</span>
              </div>
            ))}
            <button onClick={() => setShowJoin(true)} style={{
              width: "100%", display: "flex", alignItems: "center", gap: 8,
              padding: "8px 12px", borderRadius: 7, border: "1px dashed #222",
              cursor: "pointer", background: "rgba(255,255,255,0.02)", color: "#555", fontSize: 12, marginTop: 6,
            }}>
              <Plus size={13} /> 加入团队
            </button>
          </div>
        </div>
      )}

      {/* ── Mobile top bar ── */}
      {isMobile && (
        <div style={{
          background: designTokens.color.sidebarBackground, borderBottom: "1px solid rgba(255,36,66,0.08)",
          padding: "12px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          position: "sticky", top: 0, zIndex: 50,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 26, height: 26, background: designTokens.color.brandGradient, boxShadow: designTokens.color.brandGlow, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700 }}>红</div>
            <span style={{ fontSize: 14, fontWeight: 600, color: "#fff" }}>XHS 管理台</span>
          </div>
          <button onClick={() => setShowJoin(true)} style={{
            display: "flex", alignItems: "center", gap: 5,
            padding: "6px 12px", background: "transparent",
            border: "1px dashed #333", borderRadius: 6,
            color: "#555", fontSize: 12, cursor: "pointer",
          }}>
            <Plus size={12} /> 加入团队
          </button>
        </div>
      )}

      {/* ── Main content ── */}
      <div style={{
        flex: 1, overflow: "auto",
        paddingBottom: isMobile ? "calc(60px + env(safe-area-inset-bottom))" : 0,
        animation: "fadeIn 150ms ease",
      }}>
        <Suspense fallback={<PageFallback isMobile={isMobile} />}>
          {view === "content"   && <ContentManager accounts={accounts} members={members} />}
          {view === "accounts"  && <AccountsPage   accounts={accounts} members={members} onAccountsChange={setAccounts} />}
          {view === "calendar"  && <CalendarPage   accounts={accounts} members={members} />}
          {view === "material"  && <MaterialPage />}
          {shouldRenderAi && (
            <div style={{ display: view === "ai" ? "block" : "none" }}>
              <div style={{ padding: isMobile ? "12px 12px 0" : "18px 18px 0" }}>
                <div style={{
                  display: "inline-flex",
                  gap: 8,
                  padding: 4,
                  ...createGlassCardStyle({ padding: 4, radius: 12 }),
                  borderRadius: 12,
                }}>
                  {[
                    { key: "workbench", label: "AI 工作台" },
                    { key: "classic", label: "经典搜索" },
                    ...(agentModeEnabled ? [{ key: "agent", label: "运营助手" }] : []),
                  ].map(item => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setAiMode(item.key)}
                      style={{
                        border: "none",
                        background: aiMode === item.key ? "rgba(255,36,66,0.12)" : "transparent",
                        color: aiMode === item.key ? "#FF2442" : "#666",
                        borderRadius: 9,
                        padding: "9px 12px",
                        fontSize: 12,
                        fontWeight: aiMode === item.key ? 700 : 500,
                        cursor: "pointer",
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              {aiMode === "workbench" && <AIWorkbenchPage />}
              {aiMode === "classic" && <AISearchPage />}
              {aiMode === "agent" && agentModeEnabled && <AgentPage />}
            </div>
          )}
          {view === "analytics" && <AnalyticsPage  accounts={accounts} />}
        </Suspense>
      </div>

      {/* ── Mobile bottom tab bar ── */}
      {isMobile && (
        <div style={{
          position: "fixed", bottom: 0, left: 0, right: 0,
          background: "rgba(12,12,18,0.96)", borderTop: "1px solid rgba(255,36,66,0.08)",
          display: "flex", zIndex: 100,
          paddingBottom: "env(safe-area-inset-bottom)",
          backdropFilter: "blur(18px)",
        }}>
          {navItems.map(item => (
            <button key={item.key} onClick={() => setView(item.key)} style={{
              flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
              padding: "10px 0 8px", gap: 4, background: "none", border: "none",
              cursor: "pointer",
              color: view === item.key ? "#FF2442" : "#555",
            }}>
              {item.icon}
              {view === item.key && (
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "#FF2442", boxShadow: designTokens.color.brandGlow }} />
              )}
              <span style={{ fontSize: 10, fontWeight: view === item.key ? 600 : 400 }}>{item.label}</span>
            </button>
          ))}
        </div>
      )}

      {showJoin && (
        <JoinTeamModal onClose={() => setShowJoin(false)} onJoin={m => setMembers(prev => [...prev, m])} />
      )}
      <ToastViewport />
    </div>
  );
}
