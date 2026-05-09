import { useState } from 'react'
import { C, iconBtnStyle } from '../theme'

const IS = { width: 16, height: 16, display: 'block' as const }

const PrevIcon = () => (
  <svg {...IS} viewBox="0 0 24 24" fill="currentColor">
    <rect x="5" y="5" width="3" height="14" rx="1" />
    <polygon points="19,5 9,12 19,19" />
  </svg>
)
const PlayIcon = () => (
  <svg {...IS} viewBox="0 0 24 24" fill="currentColor">
    <polygon points="5,3 20,12 5,21" />
  </svg>
)
const PauseIcon = () => (
  <svg {...IS} viewBox="0 0 24 24" fill="currentColor">
    <rect x="6" y="4" width="4" height="16" rx="1" />
    <rect x="14" y="4" width="4" height="16" rx="1" />
  </svg>
)
const NextIcon = () => (
  <svg {...IS} viewBox="0 0 24 24" fill="currentColor">
    <polygon points="5,5 15,12 5,19" />
    <rect x="16" y="5" width="3" height="14" rx="1" />
  </svg>
)

function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: React.ReactNode }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        ...iconBtnStyle,
        borderColor: hovered ? C.primary : iconBtnStyle.borderColor as string,
        color: hovered ? C.textPrimary : iconBtnStyle.color as string,
      }}
    >
      {children}
    </button>
  )
}

interface Props {
  paused: boolean
  onPrev: () => void
  onPlayPause: () => void
  onNext: () => void
}

export default function TransportControls({ paused, onPrev, onPlayPause, onNext }: Props) {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      <IconButton onClick={onPrev} title="Previous"><PrevIcon /></IconButton>
      <IconButton onClick={onPlayPause} title={paused ? 'Play' : 'Pause'}>
        {paused ? <PlayIcon /> : <PauseIcon />}
      </IconButton>
      <IconButton onClick={onNext} title="Next"><NextIcon /></IconButton>
    </div>
  )
}
