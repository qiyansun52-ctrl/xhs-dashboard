import { useState, useMemo, useEffect, useRef } from "react";
import { Plus, X, Clock, Image as ImgIcon } from "lucide-react";
import { supabase } from "../supabase.js";
import {
  Avatar, Badge, STATUS, inputStyle, useIsMobile,
  Card, CountUpNumber, EmptyState, Skeleton,
  createGlassCardStyle, createPrimaryButtonStyle, designTokens,
} from "./shared.jsx";
import PostDetailDrawer from "./PostDetailDrawer.jsx";

/* ── Image upload zone ── */
function ImageUploadZone({ files, onChange, disabled }) {
  const inputRef = useRef(null);

  const addFiles = (incoming) => {
    const imgs = incoming.filter(f => f.type.startsWith("image/"));
    onChange([...files, ...imgs].slice(0, 9));
  };

  const handleDrop = (e) => {
    e.preventDefault();
    addFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <div>
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => !disabled && inputRef.current?.click()}
        style={{
          border: "2px dashed #2a2a2a", borderRadius: 10,
          padding: "18px 16px", textAlign: "center",
          cursor: disabled ? "not-allowed" : "pointer",
          color: "#555", fontSize: 13,
        }}
      >
        <ImgIcon size={20} style={{ marginBottom: 6, color: "#333", display: "block", margin: "0 auto 8px" }} />
        <div>点击或拖拽上传图片（最多9张）</div>
        <div style={{ fontSize: 11, marginTop: 4, color: "#444" }}>{files.length}/9 张</div>
        <input
          ref={inputRef} type="file" multiple accept="image/*"
          style={{ display: "none" }}
          onChange={e => { addFiles(Array.from(e.target.files)); e.target.value = ""; }}
        />
      </div>

      {files.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
          {files.map((f, i) => (
            <div key={i} style={{ position: "relative", width: 68, height: 68 }}>
              <img
                src={URL.createObjectURL(f)} alt=""
                style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6 }}
              />
              {!disabled && (
                <button
                  onClick={e => { e.stopPropagation(); onChange(files.filter((_, j) => j !== i)); }}
                  style={{
                    position: "absolute", top: -6, right: -6, width: 18, height: 18,
                    borderRadius: "50%", background: "#FF2442", border: "none",
                    color: "#fff", fontSize: 13, cursor: "pointer", lineHeight: 1,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >×</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main component ── */
export default function ContentManager({ accounts, members }) {
  const isMobile = useIsMobile();
  const [posts, setPosts]           = useState([]);
  const [loading, setLoading]       = useState(true);
  const [filterStatus, setFS]       = useState("all");
  const [filterAccount, setFA]      = useState("all");
  const [showModal, setShowModal]   = useState(false);
  const [saving, setSaving]         = useState(false);
  const [uploadMsg, setUploadMsg]   = useState("");
  const [selectedPost, setSelected] = useState(null);
  const [imageFiles, setImageFiles] = useState([]);
  const [newPost, setNP] = useState({
    accountId: "", title: "", caption: "",
    scheduledAt: "", tags: "", status: "draft", uploaderId: "",
  });

  useEffect(() => {
    fetchPosts();
    const ch = supabase
      .channel("posts-sync")
      .on("postgres_changes", { event: "*", schema: "public", table: "posts" }, fetchPosts)
      .subscribe();
    return () => supabase.removeChannel(ch);
  }, []);

  const fetchPosts = async () => {
    const { data, error } = await supabase
      .from("posts").select("*").order("created_at", { ascending: false });
    if (error) { console.error("加载帖子失败:", error.message); return; }
    setPosts(data.map(p => ({
      ...p,
      accountId:   p.account_id,
      scheduledAt: p.scheduled_at,
    })));
    setLoading(false);
  };

  const createPost = async () => {
    if (!newPost.accountId || !newPost.title.trim()) {
      alert("请填写帖子标题并选择发布账号");
      return;
    }
    setSaving(true);
    const postId = crypto.randomUUID();
    const imageUrls = [];

    for (let i = 0; i < imageFiles.length; i++) {
      const file = imageFiles[i];
      setUploadMsg(`上传图片 ${i + 1} / ${imageFiles.length}…`);
      const ext  = file.name.split(".").pop() || "jpg";
      const path = `${postId}/${Date.now()}_${i}.${ext}`;
      const { error: upErr } = await supabase.storage.from("post-images").upload(path, file);
      if (upErr) {
        alert(`第 ${i + 1} 张图片上传失败：${upErr.message}`);
        setSaving(false); setUploadMsg(""); return;
      }
      const { data: { publicUrl } } = supabase.storage.from("post-images").getPublicUrl(path);
      imageUrls.push(publicUrl);
    }

    setUploadMsg("保存帖子…");
    const { error } = await supabase.from("posts").insert([{
      id:           postId,
      account_id:   Number(newPost.accountId),
      title:        newPost.title.trim(),
      caption:      newPost.caption,
      scheduled_at: newPost.scheduledAt || null,
      status:       newPost.status,
      tags:         newPost.tags.split(/[,，\s]+/).map(t => t.trim()).filter(Boolean),
      img_count:    imageUrls.length,
      images:       imageUrls,
      uploader_id:  newPost.uploaderId || null,
    }]);

    setSaving(false); setUploadMsg("");
    if (error) { alert("创建失败：" + error.message); return; }
    closeModal();
  };

  const closeModal = () => {
    setShowModal(false);
    setImageFiles([]);
    setNP({ accountId: "", title: "", caption: "", scheduledAt: "", tags: "", status: "draft", uploaderId: "" });
  };

  const deletePost = async (id) => {
    if (!confirm("确认删除这条帖子？")) return;
    await supabase.from("posts").delete().eq("id", id);
  };

  const handleStatusChange = (id, newStatus) => {
    setPosts(prev => prev.map(p => p.id === id ? { ...p, status: newStatus } : p));
    setSelected(prev => prev?.id === id ? { ...prev, status: newStatus } : prev);
  };

  const visible = useMemo(() =>
    posts
      .filter(p => filterStatus === "all" || p.status === filterStatus)
      .filter(p => filterAccount === "all" || p.accountId === Number(filterAccount)),
    [posts, filterStatus, filterAccount]
  );

  const counts = useMemo(() => ({
    draft:     posts.filter(p => p.status === "draft").length,
    scheduled: posts.filter(p => p.status === "scheduled").length,
    published: posts.filter(p => p.status === "published").length,
  }), [posts]);

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1100 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <h1 style={{ ...designTokens.type.pageTitle, margin: 0 }}>内容管理</h1>
          <p style={{ color: "#555", margin: "5px 0 0", fontSize: 13 }}>团队实时协作 · 所有人的操作立即同步</p>
        </div>
        <button onClick={() => setShowModal(true)} style={{
          ...createPrimaryButtonStyle(),
          display: "flex", alignItems: "center", gap: 7,
          padding: "9px 18px", fontSize: 13, fontWeight: 600,
        }}>
          <Plus size={15} /> 新建帖子
        </button>
      </div>

      {/* Status tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 22, overflowX: "auto", paddingBottom: 2 }}>
        {[
          ["all", { label: "全部", color: "#fff" }, posts.length],
          ...Object.entries(counts).map(([k, v]) => [k, STATUS[k], v]),
        ].map(([k, meta, v]) => (
          <button key={k} onClick={() => setFS(k)} style={{
            flex: "0 0 auto",
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "9px 14px",
            borderRadius: 999,
            border: `1px solid ${filterStatus === k ? `${meta.color}66` : designTokens.color.cardBorder}`,
            background: filterStatus === k ? `${meta.color}18` : "rgba(255,255,255,0.025)",
            color: filterStatus === k ? meta.color : designTokens.color.textMuted,
            cursor: "pointer",
            fontSize: 12,
            fontWeight: filterStatus === k ? 700 : 500,
          }}>
            <span>{meta.label}</span>
            <CountUpNumber value={v} formatter={n => String(n)} style={{ color: filterStatus === k ? meta.color : designTokens.color.textSecondary, fontWeight: 700 }} />
          </button>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 22 }}>
        <select value={filterStatus} onChange={e => setFS(e.target.value)}
          style={{ ...inputStyle, width: "auto", padding: "7px 12px" }}>
          <option value="all">全部状态</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select value={filterAccount} onChange={e => setFA(e.target.value)}
          style={{ ...inputStyle, width: "auto", padding: "7px 12px" }}>
          <option value="all">全部账号</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.flag} {a.name}</option>)}
        </select>
      </div>

      {/* Grid */}
      {loading ? (
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(3, 1fr)", gap: isMobile ? 10 : 14 }}>
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} height="auto" radius={12} style={{ aspectRatio: "3/4" }} />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          title={posts.length === 0 ? "还没有帖子" : "没有符合条件的帖子"}
          description={posts.length === 0 ? "新建帖子后，封面、状态和排期会在这里统一管理。" : "调整状态或账号筛选，查看其他内容。"}
          action={posts.length === 0 ? (
            <button onClick={() => setShowModal(true)} style={{ ...createPrimaryButtonStyle(), padding: "9px 14px", fontSize: 13, fontWeight: 600 }}>
              <Plus size={14} /> 新建帖子
            </button>
          ) : null}
        />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(3, 1fr)", gap: isMobile ? 10 : 14 }}>
          {visible.map(post => {
            const acc      = accounts.find(a => a.id === post.accountId);
            const coverImg = post.images?.[0];
            return (
              <div
                key={post.id}
                onClick={() => setSelected(post)}
                onMouseEnter={e => { e.currentTarget.style.borderColor = acc?.color || designTokens.color.cardBorderHover; e.currentTarget.style.transform = "translateY(-1px)"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = designTokens.color.cardBorder; e.currentTarget.style.transform = "translateY(0)"; }}
                style={{
                  ...createGlassCardStyle({ interactive: true, padding: 0 }),
                  position: "relative", aspectRatio: "3/4", borderRadius: 12,
                  overflow: "hidden", cursor: "pointer",
                }}
              >
                {/* Cover image */}
                {coverImg ? (
                  <img src={coverImg} alt="" style={{
                    position: "absolute", inset: 0,
                    width: "100%", height: "100%", objectFit: "cover",
                  }} />
                ) : (
                  <div style={{
                    position: "absolute", inset: 0,
                    background: acc ? `linear-gradient(135deg, ${acc.color}22, rgba(255,255,255,0.035))` : "rgba(255,255,255,0.035)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    padding: 18,
                  }}>
                    <div style={{ textAlign: "center" }}>
                      <ImgIcon size={24} color="rgba(255,255,255,0.25)" style={{ marginBottom: 10 }} />
                      <div style={{ fontSize: 14, color: "rgba(255,255,255,0.82)", fontWeight: 700, lineHeight: 1.55 }}>{post.title}</div>
                    </div>
                  </div>
                )}

                {/* Gradient */}
                <div style={{
                  position: "absolute", inset: 0,
                  background: "linear-gradient(to bottom, rgba(0,0,0,0.08) 0%, transparent 35%, transparent 52%, rgba(0,0,0,0.88) 100%)",
                }} />

                {/* Status badge */}
                <div style={{ position: "absolute", top: 10, right: 10 }}>
                  <Badge status={post.status} />
                </div>

                {/* Image count */}
                {(post.images?.length || 0) > 1 && (
                  <div style={{
                    position: "absolute", top: 10, left: 10,
                    background: "rgba(0,0,0,0.65)", color: "#fff",
                    fontSize: 11, padding: "2px 8px", borderRadius: 12,
                    display: "flex", alignItems: "center", gap: 4,
                  }}>
                    <ImgIcon size={10} /> {post.images.length}
                  </div>
                )}

                {/* Bottom overlay */}
                <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "10px 12px" }}>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: "#fff",
                    overflow: "hidden", display: "-webkit-box",
                    WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                    marginBottom: 7, lineHeight: 1.4,
                  }}>
                    {post.title}
                  </div>
                  {acc && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Avatar acc={acc} size={18} />
                      <span style={{ fontSize: 11, color: "rgba(255,255,255,0.65)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {acc.flag} {acc.name}
                      </span>
                    </div>
                  )}
                  {post.scheduledAt && (
                    <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", marginTop: 4, display: "flex", alignItems: "center", gap: 3 }}>
                      <Clock size={9} /> {post.scheduledAt}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Post detail drawer */}
      {selectedPost && (
        <PostDetailDrawer
          post={selectedPost}
          accounts={accounts}
          members={members}
          onClose={() => setSelected(null)}
          onStatusChange={handleStatusChange}
          onDelete={id => setPosts(prev => prev.filter(p => p.id !== id))}
        />
      )}

      {/* Create modal */}
      {showModal && (
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 26 }}>
              <h2 style={{ fontSize: 18, fontWeight: 600, color: "#fff", margin: 0 }}>新建帖子</h2>
              <button onClick={closeModal} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", padding: 4 }}>
                <X size={18} />
              </button>
            </div>

            {/* Title */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>帖子标题 *</label>
              <input value={newPost.title} onChange={e => setNP({ ...newPost, title: e.target.value })}
                placeholder="e.g. 英国留学真实花费｜这些钱不能省" style={inputStyle} />
            </div>

            {/* Caption */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>正文文案</label>
              <textarea rows={4} value={newPost.caption} onChange={e => setNP({ ...newPost, caption: e.target.value })}
                placeholder="帖子正文内容…" style={{ ...inputStyle, resize: "vertical" }} />
            </div>

            {/* Tags */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>话题标签</label>
              <input value={newPost.tags} onChange={e => setNP({ ...newPost, tags: e.target.value })}
                placeholder="多个标签用逗号分隔，e.g. 英国留学,UCL" style={inputStyle} />
            </div>

            {/* Scheduled at */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>预计发布时间</label>
              <input type="datetime-local" value={newPost.scheduledAt}
                onChange={e => setNP({ ...newPost, scheduledAt: e.target.value })} style={inputStyle} />
            </div>

            {/* Account */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>发布账号 *</label>
              <select value={newPost.accountId} onChange={e => setNP({ ...newPost, accountId: e.target.value })} style={inputStyle}>
                <option value="">选择账号</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.flag} {a.name}</option>)}
              </select>
            </div>

            {/* Uploader */}
            {members.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>上传人</label>
                <select value={newPost.uploaderId} onChange={e => setNP({ ...newPost, uploaderId: e.target.value })} style={inputStyle}>
                  <option value="">选择上传人</option>
                  {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              </div>
            )}

            {/* Images */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 7, fontWeight: 500 }}>
                上传图片（最多9张）
              </label>
              <ImageUploadZone files={imageFiles} onChange={setImageFiles} disabled={saving} />
            </div>

            {/* Status */}
            <div style={{ marginBottom: 26 }}>
              <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 10, fontWeight: 500 }}>状态</label>
              <div style={{ display: "flex", gap: 8 }}>
                {Object.entries(STATUS).map(([k, v]) => (
                  <button key={k} onClick={() => setNP({ ...newPost, status: k })} style={{
                    padding: "6px 16px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                    border: `1px solid ${newPost.status === k ? v.color : "#2a2a2a"}`,
                    background: newPost.status === k ? v.bg : "transparent",
                    color: newPost.status === k ? v.color : "#555",
                  }}>{v.label}</button>
                ))}
              </div>
            </div>

            {uploadMsg && (
              <div style={{ marginBottom: 12, fontSize: 12, color: "#FF9F43", textAlign: "center" }}>{uploadMsg}</div>
            )}

            <button onClick={createPost} disabled={saving} style={{
              width: "100%", padding: "11px", border: "none", borderRadius: 8,
              fontSize: 14, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer",
              background: saving ? "#555" : "#FF2442", color: "#fff",
            }}>
              {saving ? (uploadMsg || "保存中…") : "创建帖子"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
