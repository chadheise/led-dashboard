import { C } from '../theme'

interface Props {
  icon: string
  size?: number
}

/** Renders an app or library icon SVG at any size using currentColor for tinting. */
export default function AppIcon({ icon, size = 28 }: Props) {
  if (!icon) {
    return <div style={{ width: size, height: size, background: C.surface, borderRadius: 3, flexShrink: 0 }} />
  }
  const sized = icon.replace(/^<svg\b/, `<svg width="${size}" height="${size}"`)
  return (
    <span
      style={{ display: 'inline-flex', flexShrink: 0, color: 'inherit' }}
      dangerouslySetInnerHTML={{ __html: sized }}
    />
  )
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
