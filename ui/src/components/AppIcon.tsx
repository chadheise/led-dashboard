import { cloneElement } from 'react'
import { C } from '../theme'

const S = { width: 28, height: 28, display: 'block' as const }

const ICONS: Record<string, React.ReactElement> = {
  // ── App icons ───────────────────────────────────────────────────────────────
  text: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
      <line x1={3} y1={6} x2={21} y2={6} /><line x1={3} y1={10} x2={16} y2={10} />
      <line x1={3} y1={14} x2={21} y2={14} /><line x1={3} y1={18} x2={12} y2={18} />
    </svg>
  ),
  stocks: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3,18 8,11 13,14 20,5" /><polyline points="16,5 20,5 20,9" />
    </svg>
  ),
  sports: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 3v8a5 5 0 0010 0V3H7z" />
      <path d="M7 6H5a1.5 1.5 0 000 3h2" /><path d="M17 6h2a1.5 1.5 0 010 3h-2" />
      <line x1={12} y1={16} x2={12} y2={20} /><line x1={9} y1={20} x2={15} y2={20} />
    </svg>
  ),
  flights: (
    <svg {...S} viewBox="0 0 24 24" fill="currentColor">
      <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" />
    </svg>
  ),

  // ── Library icons ───────────────────────────────────────────────────────────
  canvas_utils: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x={3} y={3} width={18} height={18} rx={2} /><path d="M3 9h18M9 21V9" />
    </svg>
  ),
  text_renderer: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4 7 4 4 20 4 20 7" /><line x1={9} y1={20} x2={15} y2={20} /><line x1={12} y1={4} x2={12} y2={20} />
    </svg>
  ),
  yahoo_finance: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3,18 8,11 13,14 20,5" /><polyline points="16,5 20,5 20,9" />
    </svg>
  ),
  espn_sports: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx={12} cy={12} r={10} /><path d="M12 8v4l3 3" />
    </svg>
  ),
  opensky: (
    <svg {...S} viewBox="0 0 24 24" fill="currentColor">
      <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" />
    </svg>
  ),
  flightaware: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx={12} cy={12} r={10} /><line x1={2} y1={12} x2={22} y2={12} />
      <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
    </svg>
  ),
}

interface Props {
  appId: string
  size?: number
}

/** Renders an app-type icon at any size using currentColor for tinting. */
export default function AppIcon({ appId, size = 28 }: Props) {
  const icon = ICONS[appId]
  if (!icon) {
    return <div style={{ width: size, height: size, background: C.surface, borderRadius: 3, flexShrink: 0 }} />
  }
  return <>{cloneElement(icon, { width: size, height: size })}</>
}

// ── Shared UI icons ────────────────────────────────────────────────────────────

export const PencilIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)

export const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3,6 5,6 21,6" />
    <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
    <path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" />
  </svg>
)
