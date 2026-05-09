import { useEffect, useRef, useState } from 'react'
import DisplayPreview from '../components/DisplayPreview'
import PluginForm from '../components/PluginForm'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Run {
  id: string
  name: string
  plugin_id: string
  config: Record<string, unknown>
}

interface Schema {
  type: 'object'
  properties: Record<string, {
    type: string; title?: string; default?: unknown
    enum?: string[]; minimum?: number; maximum?: number; items?: { type: string }
  }>
  required?: string[]
}

interface PluginInfo { id: string; name: string; schema: Schema }

// ── Styles ────────────────────────────────────────────────────────────────────

const NAV_H = 35

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 720 }
const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const heading: React.CSSProperties = { fontSize: '0.75rem', letterSpacing: '0.12em', color: '#555', margin: 0 }
const card: React.CSSProperties = { border: '1px solid #222', borderRadius: 4, padding: '14px 16px', marginBottom: 8 }
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }
const btnRow: React.CSSProperties = { display: 'flex', gap: 6, flexShrink: 0 }
const btn = (variant: 'default' | 'primary' | 'danger' = 'default'): React.CSSProperties => ({
  background: 'none',
  border: `1px solid ${variant === 'primary' ? '#555' : variant === 'danger' ? '#522' : '#2a2a2a'}`,
  color: variant === 'primary' ? '#ccc' : variant === 'danger' ? '#a55' : '#555',
  padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3,
})
const fieldStyle: React.CSSProperties = {
  background: '#1a1a1a', border: '1px solid #333', color: '#ccc',
  padding: '6px 8px', borderRadius: 3, fontSize: '0.8rem', fontFamily: 'monospace', width: '100%', boxSizing: 'border-box',
}
const formSection: React.CSSProperties = { marginTop: 16, borderTop: '1px solid #1a1a1a', paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }

// ── Helpers ───────────────────────────────────────────────────────────────────

function defaultsFromSchema(schema: Schema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[k] = prop.default
  }
  return out
}

function configSummary(config: Record<string, unknown>): string {
  const parts = Object.entries(config).slice(0, 3).map(([k, v]) =>
    `${k}: ${Array.isArray(v) ? (v as unknown[]).join(', ') : String(v)}`
  )
  return parts.join(' · ') || '(no config)'
}

// ── Preview bar ───────────────────────────────────────────────────────────────

function EditPreviewBar({ label }: { label: string }) {
  return (
    <div style={{
      position: 'sticky',
      top: NAV_H,
      zIndex: 10,
      background: '#0a0a0a',
      borderBottom: '1px solid #1a1a1a',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '10px 0 8px',
      gap: 6,
    }}>
      <span style={{ fontSize: '0.6rem', letterSpacing: '0.15em', color: '#333' }}>
        PREVIEW · {label.toUpperCase()}
      </span>
      <DisplayPreview wsUrl="/ws/preview/edit" scale={2} />
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Runs() {
  const [runs, setRuns] = useState<Run[]>([])
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [editing, setEditing] = useState<string | null>(null)

  const [fName, setFName] = useState('')
  const [fPluginId, setFPluginId] = useState('')
  const [fConfig, setFConfig] = useState<Record<string, unknown>>({})

  // Stable ref for debounce timer
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/runs').then(r => r.json()),
      fetch('/api/plugins').then(r => r.json()),
    ]).then(([r, p]) => { setRuns(r); setPlugins(p) })
  }, [])

  // Stop preview when editing closes or page unmounts
  useEffect(() => {
    if (!editing) stopPreview()
  }, [editing])
  useEffect(() => () => { stopPreview() }, [])

  // Start/update preview (debounced) whenever plugin or config changes
  useEffect(() => {
    if (!editing || !fPluginId) return
    if (previewTimer.current) clearTimeout(previewTimer.current)
    previewTimer.current = setTimeout(() => {
      fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: fPluginId, config: fConfig }),
      })
    }, 300)
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current)
    }
  }, [editing, fPluginId, fConfig])

  const currentSchema = plugins.find(p => p.id === fPluginId)?.schema

  const openNew = () => {
    const first = plugins[0]
    setFName('')
    setFPluginId(first?.id ?? '')
    setFConfig(first ? defaultsFromSchema(first.schema) : {})
    setEditing('new')
  }

  const openEdit = (run: Run) => {
    setFName(run.name)
    setFPluginId(run.plugin_id)
    setFConfig(run.config)
    setEditing(run.id)
  }

  const handlePluginChange = (id: string) => {
    setFPluginId(id)
    const schema = plugins.find(p => p.id === id)?.schema
    if (schema) setFConfig(defaultsFromSchema(schema))
  }

  const save = async () => {
    const body = { name: fName, plugin_id: fPluginId, config: fConfig }
    if (editing === 'new') {
      const run: Run = await fetch('/api/runs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(r => r.json())
      setRuns(prev => [...prev, run])
    } else {
      await fetch(`/api/runs/${editing}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      setRuns(prev => prev.map(r => r.id === editing ? { ...r, ...body } : r))
    }
    setEditing(null)
  }

  const remove = async (id: string) => {
    await fetch(`/api/runs/${id}`, { method: 'DELETE' })
    setRuns(prev => prev.filter(r => r.id !== id))
    if (editing === id) setEditing(null)
  }

  const editLabel = editing === 'new'
    ? (fPluginId ? (plugins.find(p => p.id === fPluginId)?.name ?? fPluginId) : 'New run')
    : (fName || 'Editing')

  return (
    <>
      {editing && <EditPreviewBar label={editLabel} />}

      <div style={page}>
        <div style={hdr}>
          <h2 style={heading}>RUNS</h2>
          {editing !== 'new' && <button onClick={openNew} style={btn('primary')}>+ NEW RUN</button>}
        </div>

        {editing === 'new' && (
          <div style={{ ...card, border: '1px solid #333' }}>
            <RunForm
              name={fName} onNameChange={setFName}
              pluginId={fPluginId} plugins={plugins} onPluginChange={handlePluginChange}
              schema={currentSchema} config={fConfig} onConfigChange={setFConfig}
              onSave={save} onCancel={() => setEditing(null)} isNew
            />
          </div>
        )}

        {runs.map(run => {
          const pluginName = plugins.find(p => p.id === run.plugin_id)?.name ?? run.plugin_id
          return (
            <div key={run.id} style={card}>
              {editing === run.id ? (
                <RunForm
                  name={fName} onNameChange={setFName}
                  pluginId={fPluginId} plugins={plugins} onPluginChange={handlePluginChange}
                  schema={currentSchema} config={fConfig} onConfigChange={setFConfig}
                  onSave={save} onCancel={() => setEditing(null)}
                />
              ) : (
                <div style={row}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: '#ccc', marginBottom: 3 }}>{run.name}</div>
                    <div style={{ color: '#444', fontSize: '0.7rem' }}>
                      <span style={{ color: '#666' }}>{pluginName}</span>
                      {' · '}
                      {configSummary(run.config)}
                    </div>
                  </div>
                  <div style={btnRow}>
                    <button onClick={() => openEdit(run)} style={btn()}>EDIT</button>
                    <button onClick={() => remove(run.id)} style={btn('danger')}>✕</button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

function stopPreview() {
  fetch('/api/preview', { method: 'DELETE' }).catch(() => {})
}

// ── RunForm ───────────────────────────────────────────────────────────────────

interface RunFormProps {
  name: string; onNameChange: (v: string) => void
  pluginId: string; plugins: PluginInfo[]; onPluginChange: (v: string) => void
  schema?: Schema; config: Record<string, unknown>; onConfigChange: (v: Record<string, unknown>) => void
  onSave: () => void; onCancel: () => void; isNew?: boolean
}

function RunForm({ name, onNameChange, pluginId, plugins, onPluginChange, schema, config, onConfigChange, onSave, onCancel, isNew }: RunFormProps) {
  const labelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#888' }
  return (
    <div style={formSection}>
      <label style={labelStyle}>
        Name
        <input type="text" value={name} onChange={e => onNameChange(e.target.value)} style={fieldStyle} placeholder="e.g. Tech Stocks" />
      </label>
      <label style={labelStyle}>
        Plugin type
        <select value={pluginId} onChange={e => onPluginChange(e.target.value)} style={fieldStyle}>
          {plugins.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      {schema && (
        <div style={{ borderTop: '1px solid #1a1a1a', paddingTop: 12 }}>
          <PluginForm schema={schema} value={config} onChange={onConfigChange} />
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        <button
          onClick={onSave}
          disabled={!name.trim()}
          style={{ background: 'none', border: '1px solid #555', color: '#ccc', padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: name.trim() ? 'pointer' : 'default', borderRadius: 3, opacity: name.trim() ? 1 : 0.4 }}
        >
          {isNew ? 'CREATE RUN' : 'SAVE CHANGES'}
        </button>
        <button onClick={onCancel} style={{ background: 'none', border: '1px solid #2a2a2a', color: '#555', padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3 }}>CANCEL</button>
      </div>
    </div>
  )
}
