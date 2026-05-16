import { useState, useEffect, useMemo } from "react";
import {
  Plus, X, ExternalLink, ChevronLeft, Edit2, Check, Trash2, Info,
  Eye, Heart, Bookmark, Users, Image as ImgIcon, Clock,
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";
import { supabase } from "../supabase.js";
import {
  Avatar, StatPill, Badge, ChartTip, Card, CountUpNumber, EmptyState,
  fmt, getWeekly, inputStyle, PRESET_COLORS, FLAG_OPTIONS, useIsMobile,
  createGlassCardStyle, createPrimaryButtonStyle, designTokens,
} from "./shared.jsx";
import PostDetailDrawer from "./PostDetailDrawer.jsx";

const ACCOUNT_PUBLIC_COLUMNS = [
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

/* ─────────────────────────────────────────────
   Add Account Modal
───────────────────────────────────────────── */
function AddAccountModal({ onClose, onAdd, onUpdate, account }) {
  const isEdit = !!account;
  const isMobile = useIsMobile();
  const [form, setForm] = useState({
    name:         account?.name         || "",
    avatar:       account?.avatar       || "",
    flag:         account?.flag         || "🌏",
    color:        account?.color        || "#FF2442",
    xhs_link:     account?.xhs_link     || "",
    phone:        account?.phone        || "",
    xhs_password: account?.xhs_password || "",
    followers:    account?.followers    ?? "",
    views:        account?.views        ?? "",
    likes:        account?.likes        ?? "",
    saves:        account?.saves        ?? "",
    bio:          account?.bio          || "",
  });
  const [saving, setSaving] = useState(false);

  const f = (key, val) => setForm(p => ({ ...p, [key]: val }));

  const handleSubmit = async () => {
    if (!form.name.trim()) { alert("请填写账号名称"); return; }
    setSaving(true);
    const payload = {
      name:         form.name.trim(),
      avatar:       form.avatar.trim().startsWith("http") ? form.avatar.trim() : (form.avatar.trim() || form.name.trim()[0]?.toUpperCase() || "?"),
      flag:         form.flag,
      color:        form.color,
      xhs_link:     form.xhs_link.trim() || null,
      bio:          form.bio.trim()      || null,
      followers:    Number(form.followers) || 0,
      views:        Number(form.views)     || 0,
      likes:        Number(form.likes)     || 0,
      saves:        Number(form.saves)     || 0,
    };
    if (!isEdit || form.phone.trim()) {
      payload.phone = form.phone.trim() || null;
    }
    if (!isEdit || form.xhs_password.trim()) {
      payload.xhs_password = form.xhs_password.trim() || null;
    }
    if (isEdit) {
      const { data, error } = await supabase.from("accounts").update(payload).eq("id", account.id).select(ACCOUNT_PUBLIC_COLUMNS).single();
      setSaving(false);
      if (error) { alert("保存失败：" + error.message); return; }
      onUpdate(data);
    } else {
      const { data, error } = await supabase.from("accounts").insert([payload]).select(ACCOUNT_PUBLIC_COLUMNS).single();
      setSaving(false);
      if (error) { alert("创建失败：" + error.message); return; }
      onAdd(data);
    }
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
        padding: isMobile ? "24px 16px" : 32,
        paddingBottom: isMobile ? "calc(24px + env(safe-area-inset-bottom))" : 32,
        width: isMobile ? "100%" : 560,
        maxHeight: isMobile ? "92dvh" : "90vh",
        overflow: "auto",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, color: "#fff", margin: 0 }}>{isEdit ? "编辑账号" : "添加账号"}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        {/* Live preview */}
        <div style={{
          display: "flex", alignItems: "center", gap: 14,
          padding: "14px 16px", background: "#0d0d0d", borderRadius: 10, marginBottom: 22,
        }}>
          <Avatar acc={{ name: form.name || "?", avatar: form.avatar || form.name[0]?.toUpperCase() || "?", color: form.color }} size={48} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#e0e0e0" }}>{form.name || "账号名称"}</div>
            <div style={{ fontSize: 14, color: "#555", marginTop: 2 }}>{form.flag}</div>
          </div>
        </div>

        {/* Name + avatar letter */}
        <div style={{ display: "grid", gridTemplateColumns: form.avatar?.startsWith("http") ? "1fr" : "1fr 100px", gap: 12, marginBottom: 16 }}>
          <div>
            <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>账号名称 *</label>
            <input value={form.name} onChange={e => f("name", e.target.value)} placeholder="e.g. Emily_英国读研" style={inputStyle} />
          </div>
          {!form.avatar?.startsWith("http") && (
            <div>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>头像字母</label>
              <input value={form.avatar} onChange={e => f("avatar", e.target.value.slice(0, 2))}
                placeholder="E" maxLength={2} style={{ ...inputStyle, textAlign: "center" }} />
            </div>
          )}
        </div>

        {/* XHS link */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>小红书主页链接</label>
          <input value={form.xhs_link} onChange={e => f("xhs_link", e.target.value)}
            placeholder="https://www.xiaohongshu.com/user/profile/…" style={inputStyle} />
        </div>

        {/* Bio */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>账号简介 / 人设定位</label>
          <textarea rows={2} value={form.bio} onChange={e => f("bio", e.target.value)}
            placeholder="账号人设和内容定位…" style={{ ...inputStyle, resize: "vertical" }} />
        </div>

        {/* Flag */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 8, fontWeight: 500 }}>所在地区</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {FLAG_OPTIONS.map(flag => (
              <button key={flag} onClick={() => f("flag", flag)} style={{
                width: 36, height: 36, borderRadius: 8, fontSize: 18, cursor: "pointer",
                border: `2px solid ${form.flag === flag ? "#FF2442" : "#2a2a2a"}`,
                background: form.flag === flag ? "rgba(255,36,66,0.1)" : "transparent",
              }}>{flag}</button>
            ))}
          </div>
        </div>

        {/* Color */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 8, fontWeight: 500 }}>账号颜色</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {PRESET_COLORS.map(c => (
              <button key={c} onClick={() => f("color", c)} style={{
                width: 28, height: 28, borderRadius: "50%", background: c, cursor: "pointer",
                border: `2px solid ${form.color === c ? "#fff" : "transparent"}`,
                boxShadow: form.color === c ? `0 0 0 2px ${c}66` : "none",
              }} />
            ))}
          </div>
        </div>

        {/* Sensitive info */}
        <div style={{
          background: "rgba(255,36,66,0.04)", border: "1px solid rgba(255,36,66,0.12)",
          borderRadius: 10, padding: "14px 16px", marginBottom: 16,
        }}>
          <div style={{ fontSize: 11, color: "#FF244280", marginBottom: 12, fontWeight: 500 }}>
            🔒 敏感信息 — 仅存储，点击卡片时不展示
          </div>
          {isEdit && (
            <div style={{ fontSize: 11, color: "#666", marginBottom: 12 }}>
              编辑时留空则保持原值，不会覆盖已存储的手机号和密码。
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>登录手机号</label>
              <input type="tel" value={form.phone} onChange={e => f("phone", e.target.value)}
                placeholder="138xxxx1234" style={inputStyle} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>登录密码</label>
              <input type="password" value={form.xhs_password} onChange={e => f("xhs_password", e.target.value)}
                placeholder="••••••••" style={inputStyle} />
            </div>
          </div>
        </div>

        {/* Initial stats */}
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 8, fontWeight: 500 }}>初始数据（可选）</label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
            {[["粉丝","followers"],["浏览","views"],["点赞","likes"],["收藏","saves"]].map(([label, key]) => (
              <div key={key}>
                <div style={{ fontSize: 11, color: "#555", marginBottom: 4 }}>{label}</div>
                <input type="number" value={form[key]} onChange={e => f(key, e.target.value)}
                  placeholder="0" style={{ ...inputStyle, padding: "7px 10px" }} />
              </div>
            ))}
          </div>
        </div>

        <button onClick={handleSubmit} disabled={saving} style={{
          width: "100%", padding: "11px", border: "none", borderRadius: 8,
          fontSize: 14, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer",
          background: saving ? "#555" : "#FF2442", color: "#fff",
        }}>
          {saving ? (isEdit ? "保存中…" : "添加中…") : (isEdit ? "保存修改" : "添加账号")}
        </button>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Account Detail Page
───────────────────────────────────────────── */
function AccountInfoModal({ account, onClose }) {
  const isMobile = useIsMobile();
  const rows = [
    { label: "账号名称",   value: account.name },
    { label: "头像字母",   value: account.avatar },
    { label: "地区",       value: account.flag },
    { label: "账号颜色",   value: account.color, isColor: true },
    { label: "小红书链接", value: account.xhs_link, isLink: true },
    { label: "账号简介",   value: account.bio },
    { label: "粉丝数",     value: account.followers?.toLocaleString() },
    { label: "浏览量",     value: account.views?.toLocaleString() },
    { label: "点赞数",     value: account.likes?.toLocaleString() },
    { label: "收藏数",     value: account.saves?.toLocaleString() },
    { label: "创建时间",   value: account.created_at ? new Date(account.created_at).toLocaleString("zh-CN") : null },
  ].filter(r => r.value);

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
      display: "flex", alignItems: isMobile ? "flex-end" : "center",
      justifyContent: "center", zIndex: 300,
    }} onClick={onClose}>
      <div style={{
        background: "#111", border: "1px solid #2a2a2a",
        borderRadius: isMobile ? "16px 16px 0 0" : 14,
        padding: isMobile ? "24px 20px 32px" : "28px 28px",
        paddingBottom: isMobile ? "calc(32px + env(safe-area-inset-bottom))" : "28px",
        width: isMobile ? "100%" : 420,
        maxHeight: isMobile ? "85dvh" : "80vh",
        overflow: "auto",
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Avatar acc={account} size={36} />
            <div style={{ fontSize: 15, fontWeight: 600, color: "#fff" }}>{account.name}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", padding: 4 }}>
            <X size={16} />
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 1, borderRadius: 10, overflow: "hidden", border: "1px solid #1e1e1e" }}>
          {rows.map(({ label, value, isColor, isLink }) => (
            <div key={label} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 16px", background: "#0d0d0d", gap: 16,
              borderBottom: "1px solid #1a1a1a",
            }}>
              <span style={{ fontSize: 12, color: "#555", flexShrink: 0 }}>{label}</span>
              {isColor ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 14, height: 14, borderRadius: "50%", background: value }} />
                  <span style={{ fontSize: 13, color: "#bbb", fontFamily: "monospace" }}>{value}</span>
                </div>
              ) : isLink ? (
                <a href={value} target="_blank" rel="noopener noreferrer" style={{
                  fontSize: 12, color: "#FF2442", textDecoration: "none",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220,
                  display: "flex", alignItems: "center", gap: 4,
                }}>
                  <ExternalLink size={11} /> 打开链接
                </a>
              ) : (
                <span style={{ fontSize: 13, color: "#ccc", textAlign: "right", maxWidth: 240, wordBreak: "break-word" }}>{value}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AccountDetail({ account, members, assignments, posts, onBack, onAssign, onDelete, onUpdate }) {
  const isMobile = useIsMobile();
  const [showAssignMenu, setShowAssign] = useState(false);
  const [selectedPost, setSelected]    = useState(null);
  const [deleting, setDeleting]        = useState(false);
  const [showInfo, setShowInfo]        = useState(false);
  const [showEdit, setShowEdit]        = useState(false);

  const handleDelete = async () => {
    if (!window.confirm(`确定要删除账号「${account.name}」吗？\n此操作不可撤销，该账号下的帖子不会被删除。`)) return;
    setDeleting(true);
    const { error } = await supabase.from("accounts").delete().eq("id", account.id);
    setDeleting(false);
    if (error) { alert("删除失败：" + error.message); return; }
    onDelete(account.id);
  };
  const weekly         = getWeekly(account);
  const assignedMember = members.find(m => m.id === assignments[account.id]);
  const accountPosts   = posts.filter(p => (p.account_id ?? p.accountId) === account.id);

  const handleStatusChange = (id, newStatus) => {
    setSelected(prev => prev?.id === id ? { ...prev, status: newStatus } : prev);
  };

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 900 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <button onClick={onBack} style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", color: "#666",
          cursor: "pointer", fontSize: 13, padding: 0,
        }}>
          <ChevronLeft size={16} /> 返回账号列表
        </button>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setShowInfo(true)} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "7px 14px", background: "transparent",
            border: "1px solid #2a2a2a", borderRadius: 8,
            color: "#aaa", fontSize: 12, cursor: "pointer",
          }}>
            <Info size={13} /> 账号信息
          </button>
          <button onClick={() => setShowEdit(true)} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "7px 14px", background: "transparent",
            border: "1px solid #2a2a2a", borderRadius: 8,
            color: "#aaa", fontSize: 12, cursor: "pointer",
          }}>
            <Edit2 size={13} /> 编辑信息
          </button>
          <button onClick={handleDelete} disabled={deleting} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "7px 14px", background: "transparent",
            border: "1px solid #2a2a2a", borderRadius: 8,
            color: deleting ? "#555" : "#FF4444", fontSize: 12,
            cursor: deleting ? "not-allowed" : "pointer",
          }}>
            <Trash2 size={13} /> {deleting ? "删除中…" : "删除账号"}
          </button>
        </div>
      </div>

      {/* Header card */}
      <Card style={{
        display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: isMobile ? 12 : 18,
        marginBottom: isMobile ? 20 : 28,
        padding: isMobile ? "16px" : "22px 24px", borderRadius: 16,
      }}>
        <Avatar acc={account} size={64} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#fff", marginBottom: 4 }}>
            {account.flag} {account.name}
          </div>
          {account.bio && (
            <div style={{ fontSize: 13, color: "#666", marginBottom: 10, lineHeight: 1.6 }}>{account.bio}</div>
          )}
          {account.xhs_link && (
            <a href={account.xhs_link} target="_blank" rel="noopener noreferrer" style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              fontSize: 12, color: "#FF2442", textDecoration: "none",
            }}>
              <ExternalLink size={12} /> 查看小红书主页
            </a>
          )}
        </div>

        {/* Assign member */}
        <div style={{ position: "relative", flexShrink: 0 }}>
          <div style={{ fontSize: 11, color: "#555", marginBottom: 6, textAlign: "right" }}>负责人</div>
          <button onClick={() => setShowAssign(p => !p)} style={{
            display: "flex", alignItems: "center", gap: 8, padding: "8px 14px",
            background: "#161616", border: "1px solid #2a2a2a",
            borderRadius: 8, cursor: "pointer", color: "#ddd", fontSize: 13,
          }}>
            {assignedMember ? assignedMember.name : "待分配"}
            <Edit2 size={12} color="#555" />
          </button>
          {showAssignMenu && members.length > 0 && (
            <div style={{
              position: "absolute", top: "calc(100% + 4px)", right: 0,
              background: "#1a1a1a", border: "1px solid #2a2a2a",
              borderRadius: 8, minWidth: 140, zIndex: 10, overflow: "hidden",
            }}>
              {members.map(m => (
                <button key={m.id} onClick={() => { onAssign(account.id, m.id); setShowAssign(false); }} style={{
                  width: "100%", padding: "10px 14px", background: "none", border: "none",
                  color: m.id === assignments[account.id] ? "#FF2442" : "#ddd",
                  fontSize: 13, cursor: "pointer", textAlign: "left",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                }}>
                  {m.name}
                  {m.id === assignments[account.id] && <Check size={13} />}
                </button>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 10, marginBottom: isMobile ? 20 : 28 }}>
        <StatPill label="粉丝" value={fmt(account.followers)} color={account.color} />
        <StatPill label="浏览" value={fmt(account.views)} />
        <StatPill label="点赞" value={fmt(account.likes)} />
        <StatPill label="收藏" value={fmt(account.saves)} />
      </div>

      {/* Chart */}
      <Card style={{ padding: "22px 24px", marginBottom: 28 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#ddd", marginBottom: 16 }}>近7日趋势</div>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={weekly} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id={`views-${account.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#FF2442" stopOpacity={0.28} />
                <stop offset="95%" stopColor="#FF2442" stopOpacity={0} />
              </linearGradient>
              <linearGradient id={`likes-${account.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#FF9F43" stopOpacity={0.22} />
                <stop offset="95%" stopColor="#FF9F43" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="day" stroke="#333" tick={{ fontSize: 11, fill: "#555" }} />
            <YAxis stroke="#333" tick={{ fontSize: 11, fill: "#555" }} />
            <Tooltip content={<ChartTip />} />
            <Area type="monotone" dataKey="views" name="浏览" stroke="#FF2442" strokeWidth={2} fill={`url(#views-${account.id})`} dot={false} />
            <Area type="monotone" dataKey="likes" name="点赞" stroke="#FF9F43" strokeWidth={2} fill={`url(#likes-${account.id})`} dot={false} />
            <Area type="monotone" dataKey="saves" name="收藏" stroke="#A29BFE" strokeWidth={2} fill="rgba(162,155,254,0.08)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* Posts grid */}
      {accountPosts.length === 0 ? (
        <EmptyState title="该账号暂无帖子" description="排期或发布帖子后，这里会自动汇总账号内容。" />
      ) : (
        <div>
          <div style={{ fontSize: 11, color: "#444", fontWeight: 500, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 14 }}>
            全部帖子 ({accountPosts.length})
          </div>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(3, 1fr)", gap: isMobile ? 10 : 14 }}>
            {accountPosts.map(p => {
              const coverImg = p.images?.[0];
              return (
                <div
                  key={p.id}
                  onClick={() => setSelected(p)}
                  onMouseEnter={e => e.currentTarget.style.borderColor = account.color}
                  onMouseLeave={e => e.currentTarget.style.borderColor = "#1e1e1e"}
                  style={{
                    position: "relative", aspectRatio: "3/4", borderRadius: 12,
                    overflow: "hidden", cursor: "pointer",
                    border: "1px solid #1e1e1e", background: "#111",
                    transition: "border-color 0.15s",
                  }}
                >
                  {/* Cover */}
                  {coverImg ? (
                    <img src={coverImg} alt="" style={{
                      position: "absolute", inset: 0,
                      width: "100%", height: "100%", objectFit: "cover",
                    }} />
                  ) : (
                    <div style={{
                      position: "absolute", inset: 0,
                      background: `${account.color}18`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <ImgIcon size={28} color="#2a2a2a" />
                    </div>
                  )}

                  {/* Gradient */}
                  <div style={{
                    position: "absolute", inset: 0,
                    background: "linear-gradient(to bottom, rgba(0,0,0,0.08) 0%, transparent 35%, transparent 52%, rgba(0,0,0,0.88) 100%)",
                  }} />

                  {/* Status badge top-right */}
                  <div style={{ position: "absolute", top: 10, right: 10 }}>
                    <Badge status={p.status} />
                  </div>

                  {/* Image count top-left */}
                  {(p.images?.length || 0) > 1 && (
                    <div style={{
                      position: "absolute", top: 10, left: 10,
                      background: "rgba(0,0,0,0.65)", color: "#fff",
                      fontSize: 11, padding: "2px 8px", borderRadius: 12,
                      display: "flex", alignItems: "center", gap: 4,
                    }}>
                      <ImgIcon size={10} /> {p.images.length}
                    </div>
                  )}

                  {/* Bottom */}
                  <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "10px 12px" }}>
                    <div style={{
                      fontSize: 13, fontWeight: 600, color: "#fff",
                      overflow: "hidden", display: "-webkit-box",
                      WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                      marginBottom: 5, lineHeight: 1.4,
                    }}>
                      {p.title}
                    </div>
                    {p.scheduled_at && (
                      <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", display: "flex", alignItems: "center", gap: 3 }}>
                        <Clock size={9} /> {p.scheduled_at}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Post detail drawer */}
      {selectedPost && (
        <PostDetailDrawer
          post={selectedPost}
          accounts={[account]}
          members={members}
          onClose={() => setSelected(null)}
          onStatusChange={handleStatusChange}
        />
      )}

      {showInfo && <AccountInfoModal account={account} onClose={() => setShowInfo(false)} />}
      {showEdit && (
        <AddAccountModal
          account={account}
          onClose={() => setShowEdit(false)}
          onUpdate={updated => { onUpdate(updated); setShowEdit(false); }}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────
   Main AccountsPage
───────────────────────────────────────────── */
export default function AccountsPage({ accounts, members, onAccountsChange }) {
  const isMobile = useIsMobile();
  const [detailAccount, setDetail]  = useState(null);
  const [showAddModal, setShowAdd]  = useState(false);
  const [assignments, setAssign]    = useState({});
  const [posts, setPosts]           = useState([]);

  useEffect(() => {
    loadAssignments();
    loadPosts();
  }, []);

  const loadAssignments = async () => {
    const { data, error } = await supabase.from("account_assignments").select("*");
    if (error) return;
    const map = {};
    (data || []).forEach(a => { map[a.account_id] = a.member_id; });
    setAssign(map);
  };

  const loadPosts = async () => {
    const { data } = await supabase
      .from("posts").select("id, title, status, account_id, scheduled_at, images, uploader_id, tags, caption");
    if (data) setPosts(data);
  };

  const handleAssign = async (accountId, memberId) => {
    const { error } = await supabase.from("account_assignments")
      .upsert([{ account_id: accountId, member_id: memberId }], { onConflict: "account_id" });
    if (error) { alert("分配失败：" + error.message); return; }
    setAssign(p => ({ ...p, [accountId]: memberId }));
  };

  // ── Totals across all accounts ──
  const totals = useMemo(() => ({
    followers: accounts.reduce((s, a) => s + (a.followers || 0), 0),
    views:     accounts.reduce((s, a) => s + (a.views     || 0), 0),
    likes:     accounts.reduce((s, a) => s + (a.likes     || 0), 0),
    saves:     accounts.reduce((s, a) => s + (a.saves     || 0), 0),
  }), [accounts]);

  // ── Aggregate 7-day trend (sum of all accounts) ──
  const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const combinedWeekly = useMemo(() => {
    return DAYS.map((day, i) => {
      let views = 0, likes = 0, saves = 0;
      accounts.forEach(acc => {
        const w = getWeekly(acc);
        views += w[i].views;
        likes += w[i].likes;
        saves += w[i].saves;
      });
      return { day, views, likes, saves };
    });
  }, [accounts]);

  if (detailAccount) {
    const fresh = accounts.find(a => a.id === detailAccount.id) || detailAccount;
    return (
      <AccountDetail
        account={fresh}
        members={members}
        assignments={assignments}
        posts={posts}
        onBack={() => setDetail(null)}
        onAssign={handleAssign}
        onDelete={id => { onAccountsChange(prev => prev.filter(a => a.id !== id)); setDetail(null); }}
        onUpdate={updated => { onAccountsChange(prev => prev.map(a => a.id === updated.id ? updated : a)); setDetail(updated); }}
      />
    );
  }

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1100 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: isMobile ? 20 : 28 }}>
        <div>
          <h1 style={{ ...designTokens.type.pageTitle, margin: 0 }}>账号管理</h1>
          <p style={{ color: "#555", margin: "5px 0 0", fontSize: 13 }}>
            {accounts.length} 个账号 · 近7日数据（手动更新，接入 Spider_XHS 后自动同步）
          </p>
        </div>
        <button onClick={() => setShowAdd(true)} style={{
          ...createPrimaryButtonStyle(),
          display: "flex", alignItems: "center", gap: 7,
          padding: "9px 18px", fontSize: 13, fontWeight: 600,
        }}>
          <Plus size={15} /> 添加账号
        </button>
      </div>

      {/* Totals */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 10, marginBottom: 18 }}>
        {[
          { label: "总粉丝", value: totals.followers, icon: <Users size={14} />,    color: "#FF2442" },
          { label: "总浏览", value: totals.views,     icon: <Eye size={14} />,      color: "#FF9F43" },
          { label: "总点赞", value: totals.likes,     icon: <Heart size={14} />,    color: "#FF7A7A" },
          { label: "总收藏", value: totals.saves,     icon: <Bookmark size={14} />, color: "#A29BFE" },
        ].map(s => (
          <Card key={s.label} style={{ padding: "18px 20px" }}>
            <div style={{ color: s.color, display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              {s.icon}<span style={{ fontSize: 11, color: designTokens.color.textMuted }}>{s.label}</span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 700, color: "#fff" }}>
              <CountUpNumber value={s.value} />
            </div>
          </Card>
        ))}
      </div>

      {/* Combined trend chart */}
      <Card style={{ padding: "20px 24px", marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#ddd" }}>全账号近7日趋势</div>
          <div style={{ display: "flex", gap: 18, fontSize: 12, color: "#555" }}>
            {[["#FF2442","浏览"],["#FF9F43","点赞"],["#A29BFE","收藏"]].map(([c,l]) => (
              <div key={l} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 14, height: 2, background: c, borderRadius: 1 }} />{l}
              </div>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={combinedWeekly} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="combined-views" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#FF2442" stopOpacity={0.28} />
                <stop offset="95%" stopColor="#FF2442" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="combined-likes" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#FF9F43" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#FF9F43" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="day" stroke="#333" tick={{ fontSize: 11, fill: "#555" }} />
            <YAxis stroke="#333" tick={{ fontSize: 11, fill: "#555" }} />
            <Tooltip content={<ChartTip />} />
            <Area type="monotone" dataKey="views" name="浏览" stroke="#FF2442" strokeWidth={2} fill="url(#combined-views)" dot={false} />
            <Area type="monotone" dataKey="likes" name="点赞" stroke="#FF9F43" strokeWidth={2} fill="url(#combined-likes)" dot={false} />
            <Area type="monotone" dataKey="saves" name="收藏" stroke="#A29BFE" strokeWidth={2} fill="rgba(162,155,254,0.08)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* Account cards */}
      <div style={{ fontSize: 11, color: "#444", fontWeight: 500, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 14 }}>账号列表</div>
      {accounts.length === 0 ? (
        <EmptyState
          title="还没有账号"
          description="添加第一个小红书账号后，团队数据和内容归属会在这里汇总。"
          action={(
            <button onClick={() => setShowAdd(true)} style={{ ...createPrimaryButtonStyle(), padding: "9px 14px", fontSize: 13, fontWeight: 600 }}>
              <Plus size={14} /> 添加账号
            </button>
          )}
        />
      ) : (
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: isMobile ? 10 : 14 }}>
        {accounts.map(acc => {
          const assignedMember = members.find(m => m.id === assignments[acc.id]);
          const accPosts       = posts.filter(p => p.account_id === acc.id);
          return (
            <div
              key={acc.id}
              onClick={() => setDetail(acc)}
              onMouseEnter={e => { e.currentTarget.style.borderColor = acc.color; e.currentTarget.style.transform = "translateY(-1px)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = designTokens.color.cardBorder; e.currentTarget.style.transform = "translateY(0)"; }}
              style={{
                ...createGlassCardStyle({ interactive: true, padding: "20px 22px", radius: 14 }),
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                <Avatar acc={acc} size={50} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0" }}>{acc.name}</div>
                  <div style={{ fontSize: 13, color: "#555", marginTop: 2 }}>{acc.flag}</div>
                  {acc.bio && (
                    <div style={{ fontSize: 11, color: "#444", marginTop: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {acc.bio}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  <div style={{ fontSize: 10, color: "#555", marginBottom: 3 }}>负责人</div>
                  <div style={{
                    fontSize: 12, fontWeight: assignedMember ? 600 : 400,
                    color: assignedMember ? "#ddd" : "#444",
                  }}>
                    {assignedMember?.name || "待分配"}
                  </div>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
                {[
                  { label: "粉丝", value: fmt(acc.followers), color: acc.color },
                  { label: "浏览", value: fmt(acc.views) },
                  { label: "点赞", value: fmt(acc.likes) },
                  { label: "收藏", value: fmt(acc.saves) },
                ].map(s => (
                  <div key={s.label} style={{ background: "rgba(255,255,255,0.035)", borderRadius: 6, padding: "8px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 15, fontWeight: 600, color: s.color || "#fff", fontVariantNumeric: "tabular-nums" }}>{s.value}</div>
                    <div style={{ fontSize: 10, color: "#555", marginTop: 2 }}>{s.label}</div>
                  </div>
                ))}
              </div>

              {accPosts.length > 0 && (
                <div style={{ marginTop: 12, fontSize: 11, color: "#444", display: "flex", gap: 14 }}>
                  <span style={{ color: "#26DE81" }}>{accPosts.filter(p => p.status === "published").length} 已发布</span>
                  <span style={{ color: "#FF9F43" }}>{accPosts.filter(p => p.status === "scheduled").length} 待发布</span>
                  <span>{accPosts.filter(p => p.status === "draft").length} 草稿</span>
                </div>
              )}
            </div>
          );
        })}

        {/* Add new card */}
        <div
          key="add-account"
          onClick={() => setShowAdd(true)}
          onMouseEnter={e => { e.currentTarget.style.borderColor = "#FF2442"; e.currentTarget.style.color = "#FF2442"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = designTokens.color.cardBorder; e.currentTarget.style.color = "#333"; }}
          style={{
            background: "transparent", border: "2px dashed #1e1e1e", borderRadius: 14,
            padding: "20px 22px", cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            color: "#333", minHeight: 160, transition: "border-color 0.15s, color 0.15s",
          }}
        >
          <Plus size={20} />
          <span style={{ fontSize: 13, fontWeight: 500 }}>添加新账号</span>
        </div>
      </div>
      )}

      {showAddModal && (
        <AddAccountModal
          onClose={() => setShowAdd(false)}
          onAdd={acc => onAccountsChange(prev => [...prev, acc])}
        />
      )}
    </div>
  );
}
