import { cloneElement } from 'react'
import { C } from '../theme'

const S = { width: 28, height: 28, display: 'block' as const }

const ICONS: Record<string, React.ReactElement> = {
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
