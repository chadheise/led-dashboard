import { useEffect, useState } from 'react'
import PluginForm from '../components/PluginForm'

interface Schema {
  type: 'object'
  title?: string
  properties: Record<string, {
    type: string
    title?: string
    default?: unknown
    enum?: string[]
    minimum?: number
    maximum?: number
    items?: { type: string }
  }>
  required?: string[]
}

interface PluginInfo {
  id: string
  name: string
  schema: Schema
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
  padding: '16px',
  marginBottom: 12,
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

function defaultsFromSchema(schema: Schema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[key] = prop.default
  }
  return out
}

export default function Plugins() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [expanding, setExpanding] = useState<string | null>(null)
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [duration, setDuration] = useState(30)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/plugins').then(r => r.json()).then(setPlugins)
  }, [])

  const openForm = (plugin: PluginInfo) => {
    setFormValues(defaultsFromSchema(plugin.schema))
    setDuration(30)
    setExpanding(plugin.id)
    setStatus(null)
  }

  const addToPlaylist = async (plugin: PluginInfo) => {
    const playlist = await fetch('/api/playlist').then(r => r.json())
    const newEntry = { plugin_id: plugin.id, config: formValues, duration }
    const resp = await fetch('/api/playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([...playlist, newEntry]),
    })
    if (resp.ok) {
      setStatus('Added to playlist.')
      setExpanding(null)
    } else {
      setStatus('Error — check config.')
    }
  }

  const inputStyle: React.CSSProperties = {
    background: '#1a1a1a',
    border: '1px solid #333',
    color: '#ccc',
    padding: '6px 8px',
    borderRadius: 3,
    fontSize: '0.8rem',
    fontFamily: 'monospace',
    width: 80,
  }

  return (
    <div style={page}>
      <h2 style={heading}>PLUGINS</h2>

      {status && (
        <div style={{ marginBottom: 16, color: '#4f4', fontSize: '0.75rem' }}>{status}</div>
      )}

      {plugins.map(plugin => (
        <div key={plugin.id} style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ color: '#ccc' }}>{plugin.name}</div>
            <button
              onClick={() => expanding === plugin.id ? setExpanding(null) : openForm(plugin)}
              style={btn}
            >
              {expanding === plugin.id ? 'CANCEL' : '+ ADD'}
            </button>
          </div>

          {expanding === plugin.id && (
            <div style={{ marginTop: 16, borderTop: '1px solid #1a1a1a', paddingTop: 16 }}>
              <PluginForm
                schema={plugin.schema}
                value={formValues}
                onChange={setFormValues}
              />
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14, fontSize: '0.75rem', color: '#888' }}>
                Scene duration (s)
                <input
                  type="number"
                  value={duration}
                  min={5}
                  onChange={e => setDuration(Number(e.target.value))}
                  style={inputStyle}
                />
              </label>
              <button
                onClick={() => addToPlaylist(plugin)}
                style={{ ...btn, marginTop: 14, borderColor: '#555', color: '#ccc' }}
              >
                ADD TO PLAYLIST
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
