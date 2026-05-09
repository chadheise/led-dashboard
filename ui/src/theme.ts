/**
 * Design system — single source of truth for colors, typography, and shared styles.
 * Update values here and every component that imports from this file will reflect the change.
 */
import type { CSSProperties } from "react";

// ── Color tokens ───────────────────────────────────────────────────────────────

export const C = {
  // Backgrounds — blue-grey base
  bg:           "#2C3E50",   // main page background (Wet Asphalt)
  surface:      "#34495e",   // cards, inputs, panels (Midnight Blue)
  surfaceHover: "#3d566e",   // hovered / selected surfaces

  // Palette accents (from brand colors)
  olive:  "#4B4F2B",   // dark olive — selected card background
  rust:   "#4F2E2B",   // dark rust — alternate accent surface
  sage:   "#C9CF9B",   // muted sage green — primary highlight

  // Borders
  border:       "#3d566e",   // default borders
  borderAccent: "#C9CF9B",   // selected / focused (sage)

  // Interactive
  primary: "#C9CF9B",   // primary interactive color (sage)

  // Status — subtle, desaturated variants
  positive: "#6aab72",   // soft green — success, active, connected
  negative: "#b85c5c",   // soft red — danger, error, disconnected
  neutral:  "#c8a84e",   // soft amber — warning, connecting

  // Text — readable against #2C3E50
  textPrimary:   "#ecf0f1",   // Clouds — near-white, high contrast
  textSecondary: "#bdc3c7",   // Silver — secondary labels
  textMuted:     "#95a5a6",   // Concrete — dim labels
  textDim:       "#7f8c8d",   // Asbestos — barely-visible decorations
} as const;

// ── Typography ─────────────────────────────────────────────────────────────────

export const F = {
  family: '"clother", "Helvetica Neue", Helvetica, Arial, sans-serif' as const,
  size: {
    xs:    "0.8rem",
    sm:    "0.95rem",
    base:  "1.05rem",
    label: "1rem",
    md:    "1.1rem",
  },
  tracking: {
    normal: "0.05em",
    wide:   "0.1em",
    wider:  "0.15em",
  },
} as const;

// ── Radius ─────────────────────────────────────────────────────────────────────

const R = { sm: 3, md: 4, lg: 6 } as const;

// ── Shared style objects ───────────────────────────────────────────────────────

export const pageStyle: CSSProperties = {
  padding: "24px 32px",
  maxWidth: 720,
  margin: "0 auto",
};

export const headingStyle: CSSProperties = {
  fontSize: F.size.sm,
  letterSpacing: F.tracking.wider,
  color: C.textMuted,
  fontFamily: F.family,
  margin: 0,
};

export const sectionLabelStyle: CSSProperties = {
  fontSize: F.size.xs,
  letterSpacing: F.tracking.wider,
  color: C.textMuted,
  fontFamily: F.family,
  marginBottom: 8,
};

export const labelStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  fontSize: F.size.label,
  color: C.textSecondary,
  fontFamily: F.family,
};

export const fieldStyle: CSSProperties = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  color: C.textPrimary,
  padding: "6px 8px",
  borderRadius: R.sm,
  fontSize: F.size.base,
  fontFamily: F.family,
  width: "100%",
  boxSizing: "border-box",
};

export const backBtnStyle: CSSProperties = {
  background: "none",
  border: "none",
  color: C.textSecondary,
  cursor: "pointer",
  padding: 0,
  fontFamily: F.family,
  fontSize: "1.15rem",
  letterSpacing: F.tracking.normal,
  display: "flex",
  alignItems: "center",
  gap: 10,
  marginBottom: 24,
};

export const previewPaneStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  padding: "12px 0 16px",
  background: C.bg,
  borderBottom: `1px solid ${C.border}`,
  gap: 8,
};

export const previewLabelStyle: CSSProperties = {
  fontSize: F.size.xs,
  letterSpacing: F.tracking.wider,
  color: C.textMuted,
  fontFamily: F.family,
};

export const iconBtnStyle: CSSProperties = {
  background: "none",
  border: `1px solid ${C.border}`,
  color: C.textSecondary,
  padding: "4px 7px",
  cursor: "pointer",
  borderRadius: R.sm,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

// ── Style factories ────────────────────────────────────────────────────────────

export type BtnVariant = "primary" | "success" | "danger" | "ghost" | "active" | "eye";

export function btn(variant: BtnVariant = "ghost"): CSSProperties {
  const v: Record<BtnVariant, Partial<CSSProperties>> = {
    primary: { borderColor: C.primary,  color: C.textPrimary },
    success: { borderColor: C.positive, color: C.positive },
    danger:  { borderColor: C.negative, color: C.negative },
    ghost:   { borderColor: C.border,   color: C.textSecondary },
    active:  { borderColor: C.positive, color: C.positive, background: "rgba(106,171,114,0.15)" },
    eye:     { borderColor: C.textDim,  color: C.textDim },
  };
  return {
    background: "none",
    border: `1px solid ${C.border}`,
    padding: "5px 12px",
    fontSize: F.size.sm,
    letterSpacing: F.tracking.wide,
    cursor: "pointer",
    borderRadius: R.sm,
    fontFamily: F.family,
    ...v[variant],
  };
}

export function cardStyle(active = false): CSSProperties {
  return {
    border: `1px solid ${active ? C.positive : C.border}`,
    borderRadius: R.md,
    padding: "14px 16px",
    marginBottom: 10,
    background: active ? "rgba(106,171,114,0.08)" : "transparent",
  };
}

export function appCardStyle(selected: boolean, hovered: boolean): CSSProperties {
  return {
    background: selected ? C.olive : hovered ? C.surfaceHover : C.surface,
    border: `1px solid ${selected ? C.borderAccent : C.border}`,
    borderRadius: R.lg,
    padding: "16px 14px",
    cursor: "pointer",
    textAlign: "left",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    fontFamily: F.family,
  };
}
