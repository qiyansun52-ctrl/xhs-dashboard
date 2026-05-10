import { useState } from "react";
import { X, ChevronLeft, ChevronRight, Heart, Bookmark, MessageCircle, Eye, ExternalLink, Download } from "lucide-react";
import { useIsMobile } from "./shared.jsx";

function fmt(n) {
  if (!n) return "0";
  if (n >= 10000) return (n / 10000).toFixed(1) + "w";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

const COUNTRY_COLOR = {
  "英国": "#FF7A7A", "美国": "#A29BFE", "澳洲": "#FF9F43",
  "加拿大": "#54A0FF", "新加坡": "#26DE81", "香港": "#FF2442",
};

export default function ViralPostDrawer({ post, onClose }) {
  const isMobile = useIsMobile();
  const [imgIdx, setImgIdx] = useState(0);

  const images = Array.isArray(post.images) && post.images.length > 0
    ? post.images
    : post.cover_image ? [post.cover_image] : [];

  const tags = Array.isArray(post.tags) ? post.tags : [];
  const color = COUNTRY_COLOR[post.country] || "#FF2442";

  const prev = () => setImgIdx(i => Math.max(0, i - 1));
  const next = () => setImgIdx(i => Math.min(images.length - 1, i + 1));

  const drawerStyle = isMobile ? {
    position: "fixed", bottom: 0, left: 0, right: 0,
    height: "92dvh", borderRadius: "16px 16px 0 0",
    zIndex: 400,
  } : {
    position: "fixed", top: 0, right: 0,
    width: 480, height: "100dvh",
    zIndex: 400,
  };

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 399 }} />

      {/* Drawer */}
      <div style={{
        ...drawerStyle,
        background: "#111", borderLeft: isMobile ? "none" : "1px solid #1e1e1e",
        borderTop: isMobile ? "1px solid #1e1e1e" : "none",
        display: "flex", flexDirection: "column",
        animation: "slideIn 0.2s ease-out",
      }}>
        <style>{`
          @keyframes slideIn {
            from { transform: ${isMobile ? "translateY(100%)" : "translateX(100%)"}; }
            to   { transform: ${isMobile ? "translateY(0)" : "translateX(0)"}; }
          }
        `}</style>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", borderBottom: "1px solid #1a1a1a", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#e0e0e0" }}>爆款详情</div>
            {post.country && (
              <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10, background: `${color}22`, color, border: `1px solid ${color}44` }}>
                {post.country}
              </span>
            )}
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        {/* Scrollable content */}
        <div style={{ flex: 1, overflow: "auto", paddingBottom: "env(safe-area-inset-bottom)" }}>

          {/* Image carousel */}
          {images.length > 0 && (
            <div style={{ position: "relative", background: "#0a0a0a" }}>
              <div style={{ aspectRatio: "3/4", maxHeight: isMobile ? "55vw" : 360, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <img
                  src={images[imgIdx]}
                  alt=""
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                />
              </div>

              {/* Nav arrows */}
              {images.length > 1 && (
                <>
                  <button onClick={prev} disabled={imgIdx === 0} style={{
                    position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
                    background: "rgba(0,0,0,0.6)", border: "none", borderRadius: "50%",
                    width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center",
                    color: imgIdx === 0 ? "#333" : "#fff", cursor: imgIdx === 0 ? "default" : "pointer",
                  }}>
                    <ChevronLeft size={16} />
                  </button>
                  <button onClick={next} disabled={imgIdx === images.length - 1} style={{
                    position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                    background: "rgba(0,0,0,0.6)", border: "none", borderRadius: "50%",
                    width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center",
                    color: imgIdx === images.length - 1 ? "#333" : "#fff",
                    cursor: imgIdx === images.length - 1 ? "default" : "pointer",
                  }}>
                    <ChevronRight size={16} />
                  </button>
                  {/* Dots */}
                  <div style={{ position: "absolute", bottom: 10, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 5 }}>
                    {images.map((_, i) => (
                      <div key={i} onClick={() => setImgIdx(i)} style={{
                        width: i === imgIdx ? 16 : 6, height: 6, borderRadius: 3,
                        background: i === imgIdx ? "#fff" : "rgba(255,255,255,0.35)",
                        cursor: "pointer", transition: "all 0.2s",
                      }} />
                    ))}
                  </div>
                  {/* Counter */}
                  <div style={{ position: "absolute", top: 10, right: 12, background: "rgba(0,0,0,0.6)", color: "#fff", fontSize: 11, padding: "3px 8px", borderRadius: 10 }}>
                    {imgIdx + 1} / {images.length}
                  </div>
                </>
              )}
            </div>
          )}

          {/* 数据面板 */}
          <div style={{ padding: "18px 20px", borderBottom: "1px solid #1a1a1a" }}>
            <div style={{ fontSize: 11, color: "#444", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 12 }}>数据表现</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
              {[
                { icon: <Heart size={14} />, label: "点赞", value: post.likes, color: "#FF7A7A" },
                { icon: <Bookmark size={14} />, label: "收藏", value: post.saves, color: "#A29BFE" },
                { icon: <MessageCircle size={14} />, label: "评论", value: post.comments, color: "#54A0FF" },
                { icon: <Eye size={14} />, label: "浏览", value: post.views, color: "#888" },
              ].map(s => (
                <div key={s.label} style={{ background: "#161616", borderRadius: 10, padding: "12px 0", textAlign: "center" }}>
                  <div style={{ color: s.color, display: "flex", justifyContent: "center", marginBottom: 6 }}>{s.icon}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", fontVariantNumeric: "tabular-nums" }}>{fmt(s.value)}</div>
                  <div style={{ fontSize: 10, color: "#444", marginTop: 3 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 帖子信息 */}
          <div style={{ padding: "18px 20px" }}>
            {/* 作者 */}
            {post.author_name && (
              <div style={{ fontSize: 12, color: "#555", marginBottom: 12 }}>
                @{post.author_name}
              </div>
            )}

            {/* 标题 */}
            {post.title && (
              <h2 style={{ fontSize: 16, fontWeight: 700, color: "#e0e0e0", margin: "0 0 12px", lineHeight: 1.5 }}>
                {post.title}
              </h2>
            )}

            {/* 正文 */}
            {post.caption && (
              <p style={{ fontSize: 13, color: "#999", lineHeight: 1.8, margin: "0 0 16px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {post.caption}
              </p>
            )}

            {/* Tags */}
            {tags.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
                {tags.map(t => (
                  <span key={t} style={{ fontSize: 12, color: "#FF2442", background: "rgba(255,36,66,0.1)", padding: "3px 10px", borderRadius: 20, border: "1px solid rgba(255,36,66,0.2)" }}>
                    #{t}
                  </span>
                ))}
              </div>
            )}

            {/* 备注 */}
            {post.note && (
              <div style={{ background: "#161616", border: "1px solid #1e1e1e", borderRadius: 10, padding: "12px 14px", marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: "#444", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 6 }}>团队备注</div>
                <p style={{ fontSize: 13, color: "#888", margin: 0, lineHeight: 1.6 }}>{post.note}</p>
              </div>
            )}

            {/* 操作按钮行 */}
            <div style={{ display: "flex", gap: 10 }}>
              {/* 打开原帖 */}
              {post.url ? (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                    padding: "11px 0", background: "#FF2442", borderRadius: 10,
                    color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none",
                  }}
                >
                  <ExternalLink size={14} /> 打开原帖
                </a>
              ) : (
                <div
                  style={{
                    flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                    padding: "11px 0", background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 10,
                    color: "#666", fontSize: 13, fontWeight: 600,
                  }}
                >
                  暂无原帖链接
                </div>
              )}

              {/* 下载当前图片 */}
              {images.length > 0 && (
                <a
                  href={images[imgIdx]}
                  download={`xhs-${post.xhs_note_id || "post"}-${imgIdx + 1}.webp`}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                    padding: "11px 16px", background: "#1a1a1a",
                    border: "1px solid #2a2a2a", borderRadius: 10,
                    color: "#aaa", fontSize: 13, fontWeight: 600, textDecoration: "none",
                    whiteSpace: "nowrap",
                  }}
                >
                  <Download size={14} />
                  {images.length > 1 ? `下载 ${imgIdx + 1}/${images.length}` : "下载图片"}
                </a>
              )}
            </div>

            {/* 批量下载全部图片（多图时显示）*/}
            {images.length > 1 && (
              <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {images.map((url, i) => (
                  <a
                    key={i}
                    href={url}
                    download={`xhs-${post.xhs_note_id || "post"}-${i + 1}.webp`}
                    style={{
                      fontSize: 11, color: "#555", background: "#161616",
                      border: "1px solid #222", borderRadius: 6,
                      padding: "4px 10px", textDecoration: "none",
                      display: "flex", alignItems: "center", gap: 4,
                    }}
                    onMouseEnter={e => e.currentTarget.style.color = "#aaa"}
                    onMouseLeave={e => e.currentTarget.style.color = "#555"}
                  >
                    <Download size={10} /> 图{i + 1}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
