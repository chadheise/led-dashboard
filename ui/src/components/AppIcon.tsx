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
  spotify: (
    <svg {...S} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
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
    <svg {...S} viewBox="0 0 24 24" fill="currentColor">
      <path d="M18.86 1.56L14.27 11.87H19.4L24 1.56H18.86 M0 6.71L5.15 18.27L3.3 22.44H7.83L14.69 6.71H10.19L7.39 13.44L4.62 6.71H0 M15.62 12.87C13.95 12.87 12.71 14.12 12.71 15.58C12.71 17 13.91 18.19 15.5 18.19C17.18 18.19 18.43 16.96 18.43 15.5C18.43 14.03 17.23 12.87 15.62 12.87Z" />
    </svg>
  ),
  espn_sports: (
    <svg {...S} viewBox="0 0 554 137" fill="currentColor">
      <path d="M181.064.348c-20.608-.027-34.256 10.836-36.176 27.079a1600.065 1600.065 0 0 1-1.384 11.257H411.64s.504-3.957.896-7.133C414.552 15.188 407.6.35 382.312.35v.002S191.928.36 181.064.348zM17.424.353l-4.706 38.331h121.6l4.688-38.33H17.422h.002zm408.184 0l-4.696 38.331h131.824s.16-1.386.744-5.898C556.688 7.626 540.456.353 524.784.353h-99.176zm-6.512 52.926l-10.272 83.656 45.48-.016 10.28-83.624-45.488-.018v.002zm86.4 0l-10.288 83.656 45.48-.016 10.28-83.624-45.472-.018v.002zm-494.552.012L.654 136.939h121.592l4.48-36.288-76.138-.008 1.926-15.648h76.108l3.896-31.702H10.95l-.006-.002zm130.776 0c-3.336 21.832 7.592 31.701 23.08 31.701 8.424 0 61.52-.024 61.52-.024l-1.92 15.672-88.488.008-4.456 36.288s96.336.032 100.24 0c3.224-.232 25.76-.848 33.432-19.28 2.488-5.984 4.688-27.44 5.304-31.944 3.544-26.16-14.568-32.397-28.832-32.397-7.864 0-84.352-.024-99.88-.024zm141.552 0L273 136.939h45.456l6.4-51.944h57.096c16.192 0 24.896-8.706 26.512-20.397a430.97 430.97 0 0 0 1.4-11.305H283.272v-.002z" />
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
  location: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21s-7-7.5-7-12a7 7 0 0114 0c0 4.5-7 12-7 12z" />
      <circle cx={12} cy={9} r={2.5} />
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
