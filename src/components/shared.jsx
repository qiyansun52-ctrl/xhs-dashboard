// Shared constants, helpers, and UI primitives
import { useState, useEffect, useCallback } from "react";
import {
  applyInteractiveHover,
  createGhostButtonStyle,
  createGlassCardStyle,
  createPrimaryButtonStyle,
  designTokens,
} from "./designSystem.js";

export {
  applyInteractiveHover,
  createGhostButtonStyle,
  createGlassCardStyle,
  createPrimaryButtonStyle,
  designTokens,
};

export function useIsMobile() {
  const [width, setWidth] = useState(
    typeof window !== "undefined" ? window.innerWidth : 1200
  );
  useEffect(() => {
    const fn = () => setWidth(window.innerWidth);
    window.addEventListener("resize", fn);
    return () => window.removeEventListener("resize", fn);
  }, []);
  return width < 768;
}

export const STATUS = {
  draft:     { label: "草稿",   color: "#888",    bg: "rgba(136,136,136,0.12)" },
  scheduled: { label: "待发布", color: "#FF9F43", bg: "rgba(255,159,67,0.12)"  },
  published: { label: "已发布", color: "#26DE81", bg: "rgba(38,222,129,0.12)"  },
};

export const ROLE_LABELS = {
  operator: "运营",
  owner:    "主理人",
  admin:    "管理员",
};

export const PRESET_COLORS = [
  "#FF2442","#FF7A7A","#FF9F43","#54A0FF",
  "#A29BFE","#00CFCF","#26DE81","#FFC048",
  "#FF6B9D","#6C5CE7","#00B894","#FDCB6E",
];

export const FLAG_OPTIONS = [
  "🇬🇧","🇦🇺","🇨🇦","🇺🇸","🇨🇳","🌏","🇸🇬","🇳🇿","🇩🇪","🇫🇷","🇯🇵","🇰🇷",
];

export const fmt = (n) =>
  !n ? "0"
  : n >= 10000 ? (n / 10000).toFixed(1) + "w"
  : n >= 1000  ? (n / 1000).toFixed(1) + "k"
  : String(n);

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const seedFn = (n, i) => Math.floor(n * (0.75 + ((n * 17 + i * 31) % 100) / 200));
export function getWeekly(acc) {
  return DAYS.map((day, i) => ({
    day,
    views: seedFn(Math.floor((acc.views || 0) / 30), i),
    likes: seedFn(Math.floor((acc.likes || 0) / 30), i + 7),
    saves: seedFn(Math.floor((acc.saves || 0) / 30), i + 14),
  }));
}

export function Avatar({ acc, size = 36 }) {
  const raw = acc?.avatar || "";
  const letter = (raw.startsWith("http") ? "" : raw) || acc?.name?.[0]?.toUpperCase() || "?";
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: acc?.color || "#333",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: size * 0.38, fontWeight: 600, color: "#fff", flexShrink: 0,
      boxShadow: `0 0 ${Math.max(8, Math.round(size * 0.28))}px ${(acc?.color || "#FF2442")}55`,
      overflow: "hidden",
    }}>
      {raw.startsWith("http") ? (
        <img src={raw} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : letter}
    </div>
  );
}

export function Badge({ status }) {
  const s = STATUS[status] || STATUS.draft;
  return (
    <span style={{
      fontSize: 11, fontWeight: 500, color: s.color, background: s.bg,
      padding: "3px 10px", borderRadius: 20, whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

export function StatPill({ label, value, color }) {
  return (
    <div style={{ ...createGlassCardStyle({ padding: "10px 14px", radius: 8 }) }}>
      <div style={{ fontSize: 18, fontWeight: 600, color: color || "#fff", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 11, color: designTokens.color.textMuted, marginTop: 3 }}>{label}</div>
    </div>
  );
}

export const inputStyle = {
  width: "100%", boxSizing: "border-box",
  background: "rgba(0,0,0,0.22)", border: `1px solid ${designTokens.color.formBorder}`,
  color: designTokens.color.textPrimary, borderRadius: 8, padding: "9px 13px", fontSize: 13, outline: "none",
};

export function Card({ children, style, interactive = false, onClick, ...props }) {
  return (
    <div
      {...props}
      onClick={onClick}
      onMouseEnter={event => {
        if (interactive || onClick) applyInteractiveHover(event.currentTarget, true);
        props.onMouseEnter?.(event);
      }}
      onMouseLeave={event => {
        if (interactive || onClick) applyInteractiveHover(event.currentTarget, false);
        props.onMouseLeave?.(event);
      }}
      style={{
        ...createGlassCardStyle({ interactive: interactive || Boolean(onClick) }),
        cursor: onClick ? "pointer" : style?.cursor,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Skeleton({ width = "100%", height = 14, radius = 8, style }) {
  return (
    <div style={{
      width,
      height,
      borderRadius: radius,
      background: "linear-gradient(90deg, rgba(255,255,255,0.035), rgba(255,255,255,0.08), rgba(255,255,255,0.035))",
      backgroundSize: "200% 100%",
      animation: "shimmer 1.35s ease-in-out infinite",
      ...style,
    }} />
  );
}

export function EmptyState({ icon, title, description, action }) {
  return (
    <div style={{
      ...createGlassCardStyle({ padding: "34px 20px" }),
      textAlign: "center",
      color: designTokens.color.textMuted,
    }}>
      <div style={{
        width: 44,
        height: 44,
        borderRadius: "50%",
        margin: "0 auto 12px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(255,36,66,0.08)",
        color: designTokens.color.brand,
        boxShadow: "0 0 24px rgba(255,36,66,0.12)",
      }}>
        {icon || "空"}
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: designTokens.color.textPrimary }}>{title}</div>
      {description && (
        <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.65, marginTop: 6 }}>{description}</div>
      )}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function useCountUp(value, duration = designTokens.motion.countUp) {
  const numericValue = Number(value) || 0;
  const [display, setDisplay] = useState(numericValue);

  useEffect(() => {
    let frame = 0;
    let startTime = null;
    const startValue = display;
    const change = numericValue - startValue;

    if (!change || typeof window === "undefined") {
      setDisplay(numericValue);
      return undefined;
    }

    const step = timestamp => {
      if (startTime === null) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(startValue + change * eased));
      if (progress < 1) frame = window.requestAnimationFrame(step);
    };

    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericValue, duration]);

  return display;
}

export function CountUpNumber({ value, formatter = fmt, style }) {
  const display = useCountUp(Number(value) || 0);
  return (
    <span style={{ fontVariantNumeric: "tabular-nums", ...style }}>
      {formatter(display)}
    </span>
  );
}

const toastListeners = new Set();

function emitToast(toast) {
  toastListeners.forEach(listener => listener(toast));
}

export function useToast() {
  return useCallback((message, type = "success") => {
    emitToast({
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      message,
      type,
    });
  }, []);
}

export function ToastViewport() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    const listener = toast => {
      setToasts(prev => [...prev, toast].slice(-4));
      window.setTimeout(() => {
        setToasts(prev => prev.filter(item => item.id !== toast.id));
      }, 2200);
    };
    toastListeners.add(listener);
    return () => toastListeners.delete(listener);
  }, []);

  return (
    <div style={{
      position: "fixed",
      top: 16,
      right: 16,
      zIndex: 500,
      display: "flex",
      flexDirection: "column",
      gap: 8,
      pointerEvents: "none",
    }}>
      {toasts.map(toast => {
        const isError = toast.type === "error";
        return (
          <div key={toast.id} style={{
            minWidth: 220,
            maxWidth: 340,
            ...createGlassCardStyle({ padding: "10px 12px", radius: 10 }),
            background: isError ? "rgba(255,36,66,0.14)" : "rgba(38,222,129,0.12)",
            border: `1px solid ${isError ? "rgba(255,36,66,0.28)" : "rgba(38,222,129,0.24)"}`,
            color: isError ? designTokens.color.danger : designTokens.color.success,
            fontSize: 12,
            lineHeight: 1.55,
            animation: "slideUp 220ms ease, fadeIn 220ms ease",
          }}>
            {toast.message}
          </div>
        );
      })}
    </div>
  );
}

export function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ ...createGlassCardStyle({ padding: "10px 14px", radius: 8 }), fontSize: 12 }}>
      <div style={{ color: designTokens.color.textMuted, marginBottom: 6 }}>{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}: <strong>{p.value?.toLocaleString()}</strong>
        </div>
      ))}
    </div>
  );
}
