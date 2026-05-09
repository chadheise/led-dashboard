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

const iconBtn: React.CSSProperties = {
  background: 'none',
  border: '1px solid #2a2a2a',
  color: '#666',
  padding: '4px 7px',
  cursor: 'pointer',
  borderRadius: 3,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
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
      <button onClick={onPrev} title="Previous" style={iconBtn}><PrevIcon /></button>
      <button onClick={onPlayPause} title={paused ? 'Play' : 'Pause'} style={iconBtn}>
        {paused ? <PlayIcon /> : <PauseIcon />}
      </button>
      <button onClick={onNext} title="Next" style={iconBtn}><NextIcon /></button>
    </div>
  )
}
