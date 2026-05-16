export const designTokens = {
  color: {
    pageBackground: "linear-gradient(135deg,#0a0a0a,#0f0f18)",
    sidebarBackground: "linear-gradient(180deg,#0f0f1a,#0a0a12)",
    panelBackground: "rgba(255,255,255,0.03)",
    panelBackgroundStrong: "rgba(255,255,255,0.05)",
    panelInset: "rgba(255,255,255,0.025)",
    cardBorder: "rgba(255,255,255,0.07)",
    cardBorderHover: "rgba(255,255,255,0.14)",
    formBorder: "rgba(255,255,255,0.1)",
    brand: "#FF2442",
    brandGradient: "linear-gradient(135deg,#FF2442,#ff6b6b)",
    brandGlow: "0 0 8px rgba(255,36,66,0.35)",
    success: "#26DE81",
    warning: "#FF9F43",
    info: "#54A0FF",
    danger: "#FF5C7A",
    textPrimary: "rgba(255,255,255,0.88)",
    textStrong: "#fff",
    textSecondary: "rgba(255,255,255,0.7)",
    textMuted: "rgba(255,255,255,0.45)",
    textFaint: "rgba(255,255,255,0.3)",
  },
  space: {
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    6: 24,
    8: 32,
  },
  radius: {
    pill: 999,
    chip: 6,
    button: 8,
    card: 12,
    modal: 16,
  },
  shadow: {
    card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 4px 16px rgba(0,0,0,0.3)",
    button: "0 2px 8px rgba(255,36,66,0.35)",
    modal: "0 18px 60px rgba(0,0,0,0.45)",
  },
  type: {
    pageTitle: { fontSize: 24, fontWeight: 600, color: "#fff", lineHeight: 1.2 },
    cardTitle: { fontSize: 16, fontWeight: 500, color: "rgba(255,255,255,0.88)", lineHeight: 1.35 },
    body: { fontSize: 13, fontWeight: 400, color: "rgba(255,255,255,0.7)", lineHeight: 1.65 },
    label: { fontSize: 11, fontWeight: 500, color: "rgba(255,255,255,0.45)", lineHeight: 1.4 },
  },
  motion: {
    cardHover: "200ms ease",
    buttonPress: "100ms ease",
    modalEnter: "220ms ease",
    pageSwitch: "150ms ease",
    countUp: 600,
  },
};

export function createGlassCardStyle({ interactive = false, padding = 14, radius = designTokens.radius.card } = {}) {
  return {
    background: designTokens.color.panelBackground,
    border: `1px solid ${designTokens.color.cardBorder}`,
    borderRadius: radius,
    boxShadow: designTokens.shadow.card,
    padding,
    transition: interactive
      ? `border-color ${designTokens.motion.cardHover}, transform ${designTokens.motion.cardHover}, box-shadow ${designTokens.motion.cardHover}`
      : undefined,
  };
}

export function createPrimaryButtonStyle({ disabled = false } = {}) {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    border: "none",
    borderRadius: designTokens.radius.button,
    background: disabled ? "rgba(255,255,255,0.14)" : designTokens.color.brandGradient,
    color: "#fff",
    boxShadow: disabled ? "none" : designTokens.shadow.button,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: `transform ${designTokens.motion.buttonPress}, opacity ${designTokens.motion.buttonPress}`,
  };
}

export function createGhostButtonStyle({ active = false, color = designTokens.color.brand } = {}) {
  return {
    border: `1px solid ${active ? `${color}66` : designTokens.color.formBorder}`,
    borderRadius: designTokens.radius.button,
    background: active ? `${color}18` : "transparent",
    color: active ? color : designTokens.color.textMuted,
    cursor: "pointer",
    transition: `border-color ${designTokens.motion.cardHover}, color ${designTokens.motion.cardHover}, background ${designTokens.motion.cardHover}`,
  };
}

export function applyInteractiveHover(node, active = true) {
  if (!node) return;
  node.style.borderColor = active ? designTokens.color.cardBorderHover : designTokens.color.cardBorder;
  node.style.transform = active ? "translateY(-1px)" : "translateY(0)";
}
