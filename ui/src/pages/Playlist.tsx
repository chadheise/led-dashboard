import { useEffect, useState } from 'react'

interface PlaylistEntry {
  id: string
  plugin_id: string
  config: Record<string, unknown>
  duration: number
}

interface PluginInfo {
  id: string
  name: string
}

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 700 }
const heading: React.CSSProperties = {
  fontSize: '0.75rem',
  letterSpacing: '0.12em',
  color: '#555',
  margin: '0 0 20px',
}
const card: React.CSSProperties = {
  border: '1px solid #222',
  borderRadius: 4,
  padding: '12px 16px',
  marginBottom: 8,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  gap: 12,
}
const btn: React.CSSProperties = {
  background: 'none',
  border: '1px solid #333',
  color: '#aaa',
  padding: '6px 14px',
  fontSize: '0.7rem',
  letterSpacing: '0.1em',
  cursor: 'pointer',
  borderRadius: 3,
}

export default function Playlist() {
  const [entries, setEntries] = useState<PlaylistEntry[]>([])
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch('/api/playlist').then(r => r.json()),
      fetch('/api/plugins').then(r => r.json()),
    ]).then(([playlist, pluginList]) => {
      setEntries(playlist)
      setPlugins(pluginList)
      setLoading(false)
    })
  }, [])

  const pluginName = (id: string) => plugins.find(p => p.id === id)?.name ?? id

  const removeEntry = async (entryId: string) => {
    const updated = entries.filter(e => e.id !== entryId)
    await fetch('/api/playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated),
    })
    setEntries(updated)
  }

  const nextScene = async () => {
    await fetch('/api/playlist/next', { method: 'POST' })
  }

  const configSummary = (config: Record<string, unknown>) => {
    const parts = Object.entries(config)
      .slice(0, 3)
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(',') : String(v)}`)
    return parts.join(' · ')
  }

  if (loading) {
    return <div style={page}><span style={{ color: '#444' }}>Loading…</span></div>
  }

  return (
    <div style={page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={heading}>PLAYLIST</h2>
        <button onClick={nextScene} style={btn}>NEXT →</button>
      </div>

      {entries.length === 0 && (
        <div style={{ color: '#444', fontSize: '0.85rem' }}>
          No plugins in the playlist. Add one from the Plugins tab.
        </div>
      )}

      {entries.map(entry => (
        <div key={entry.id} style={card}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: '#ccc', marginBottom: 4 }}>{pluginName(entry.plugin_id)}</div>
            <div style={{ color: '#444', fontSize: '0.7rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {entry.duration}s · {configSummary(entry.config)}
            </div>
          </div>
          <button onClick={() => removeEntry(entry.id)} style={{ ...btn, border: 'none', color: '#555' }}>
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}
