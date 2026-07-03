import { useEffect, useRef, useState } from 'react'
import DisplayPreview from '../components/DisplayPreview'
import PluginForm from '../components/PluginForm'
import { configSummary } from '../configSummary'

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

interface PluginInfo {
  id: string
  name: string
  description: string
  schema: Schema
}

// ── Constants ─────────────────────────────────────────────────────────────────

const NAV_H = 35

// ── Plugin icons (React SVG — explicit dimensions so they size correctly) ──────

const S = { width: 28, height: 28, display: 'block' as const }

const PLUGIN_ICONS: Record<string, React.ReactElement> = {
  text: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
      <line x1={3} y1={6} x2={21} y2={6} />
      <line x1={3} y1={10} x2={16} y2={10} />
      <line x1={3} y1={14} x2={21} y2={14} />
      <line x1={3} y1={18} x2={12} y2={18} />
    </svg>
  ),
  stocks: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3,18 8,11 13,14 20,5" />
      <polyline points="16,5 20,5 20,9" />
    </svg>
  ),
  sports: (
    <svg {...S} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 3v8a5 5 0 0010 0V3H7z" />
      <path d="M7 6H5a1.5 1.5 0 000 3h2" />
      <path d="M17 6h2a1.5 1.5 0 010 3h-2" />
      <line x1={12} y1={16} x2={12} y2={20} />
      <line x1={9} y1={20} x2={15} y2={20} />
    </svg>
  ),
  flights: (
    <svg {...S} viewBox="0 0 24 24" fill="currentColor">
      <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" />
    </svg>
  ),
}

// ── Styles ────────────────────────────────────────────────────────────────────

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 720 }
const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const heading: React.CSSProperties = { fontSize: '0.75rem', letterSpacing: '0.12em', color: '#555', margin: 0 }
const card: React.CSSProperties = { border: '1px solid #222', borderRadius: 4, padding: '14px 16px', marginBottom: 8 }
const rowStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }
const btnRowStyle: React.CSSProperties = { display: 'flex', gap: 6, flexShrink: 0 }

const mkBtn = (variant: 'default' | 'primary' | 'danger' = 'default'): React.CSSProperties => ({
  background: 'none',
  border: `1px solid ${variant === 'primary' ? '#555' : variant === 'danger' ? '#522' : '#2a2a2a'}`,
  color: variant === 'primary' ? '#ccc' : variant === 'danger' ? '#a55' : '#555',
  padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3,
})

const fieldStyle: React.CSSProperties = {
  background: '#1a1a1a', border: '1px solid #333', color: '#ccc',
  padding: '6px 8px', borderRadius: 3, fontSize: '0.8rem', fontFamily: 'monospace',
  width: '100%', boxSizing: 'border-box',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function defaultsFromSchema(schema: Schema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[k] = prop.default
  }
  return out
}

function stopPreview() {
  fetch('/api/preview', { method: 'DELETE' }).catch(() => {})
}

// ── Preview bar ───────────────────────────────────────────────────────────────

function EditPreviewBar({ label }: { label: string }) {
  return (
    <div style={{
      position: 'sticky', top: NAV_H, zIndex: 10,
      background: '#0a0a0a', borderBottom: '1px solid #1a1a1a',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '10px 0 8px', gap: 6,
    }}>
      <span style={{ fontSize: '0.6rem', letterSpacing: '0.15em', color: '#333' }}>
        PREVIEW · {label.toUpperCase()}
      </span>
      <DisplayPreview wsUrl="/ws/preview/edit" scale={2} />
    </div>
  )
}

// ── Plugin card grid ──────────────────────────────────────────────────────────

function PluginCardGrid({
  plugins, selected, onSelect,
}: {
  plugins: PluginInfo[]
  selected: string
  onSelect: (id: string) => void
}) {
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <div>
      <div style={{ fontSize: '0.65rem', letterSpacing: '0.12em', color: '#555', marginBottom: 10 }}>
        PLUGIN TYPE
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {plugins.map(plugin => {
          const sel = plugin.id === selected
          const hov = hovered === plugin.id && !sel
          return (
            <button
              key={plugin.id}
              type="button"
              onClick={() => onSelect(plugin.id)}
              onMouseEnter={() => setHovered(plugin.id)}
              onMouseLeave={() => setHovered(null)}
              style={{
                background: sel ? '#161616' : hov ? '#0e0e0e' : 'transparent',
                border: `1px solid ${sel ? '#555' : hov ? '#2e2e2e' : '#1e1e1e'}`,
                borderRadius: 6,
                padding: '16px 14px',
                cursor: 'pointer',
                textAlign: 'left',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                transition: 'background 0.1s',
              }}
            >
              {/* Icon */}
              <div style={{ color: sel ? '#bbb' : '#666', flexShrink: 0 }}>
                {PLUGIN_ICONS[plugin.id] ?? (
                  <div style={{ width: 28, height: 28, background: '#222', borderRadius: 4 }} />
                )}
              </div>
              {/* Name */}
              <div style={{
                fontSize: '0.82rem', fontFamily: 'monospace',
                color: sel ? '#ddd' : '#555', letterSpacing: '0.03em',
              }}>
                {plugin.name}
              </div>
              {/* Description */}
              {plugin.description && (
                <div style={{
                  fontSize: '0.68rem', color: sel ? '#4a4a4a' : '#333',
                  lineHeight: 1.5,
                }}>
                  {plugin.description}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Runs() {
  const [runs, setRuns] = useState<Run[]>([])
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [editing, setEditing] = useState<string | null>(null)

  const [fName, setFName] = useState('')
  const [fPluginId, setFPluginId] = useState('')
  const [fConfig, setFConfig] = useState<Record<string, unknown>>({})

  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/runs').then(r => r.json()),
      fetch('/api/plugins').then(r => r.json()),
    ]).then(([r, p]) => { setRuns(r); setPlugins(p) })
  }, [])

  // Stop preview when editing closes or page unmounts
  useEffect(() => { if (!editing) stopPreview() }, [editing])
  useEffect(() => () => { stopPreview() }, [])

  // Debounced preview update whenever plugin or config changes
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
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current) }
  }, [editing, fPluginId, fConfig])

  const currentSchema = plugins.find(p => p.id === fPluginId)?.schema

  const openNew = () => {
    setFName('')
    setFPluginId('')   // no pre-selection — user picks in step 1
    setFConfig({})
    setEditing('new')
  }

  const openEdit = (run: Run) => {
    setFName(run.name)
    setFPluginId(run.plugin_id)
    setFConfig(run.config)
    setEditing(run.id)
  }

  const handlePluginSelect = (id: string) => {
    if (id === fPluginId) return   // same type — keep existing config
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

  const selectedPlugin = plugins.find(p => p.id === fPluginId)
  const editLabel = editing === 'new'
    ? (selectedPlugin?.name ?? 'New run')
    : (fName || 'Editing')

  return (
    <>
      {editing && fPluginId && <EditPreviewBar label={editLabel} />}

      <div style={page}>
        <div style={hdr}>
          <h2 style={heading}>RUNS</h2>
          {editing !== 'new' && <button onClick={openNew} style={mkBtn('primary')}>+ NEW RUN</button>}
        </div>

        {editing === 'new' && (
          <div style={{ ...card, border: '1px solid #2a2a2a' }}>
            <RunForm
              name={fName} onNameChange={setFName}
              pluginId={fPluginId} plugins={plugins} onPluginSelect={handlePluginSelect}
              schema={currentSchema} config={fConfig} onConfigChange={setFConfig}
              onSave={save} onCancel={() => setEditing(null)} isNew
            />
          </div>
        )}

        {editing !== 'new' && runs.map(run => {
          const pluginName = plugins.find(p => p.id === run.plugin_id)?.name ?? run.plugin_id
          return (
            <div key={run.id} style={card}>
              {editing === run.id ? (
                <RunForm
                  name={fName} onNameChange={setFName}
                  pluginId={fPluginId} plugins={plugins} onPluginSelect={handlePluginSelect}
                  schema={currentSchema} config={fConfig} onConfigChange={setFConfig}
                  onSave={save} onCancel={() => setEditing(null)}
                />
              ) : (
                <div style={rowStyle}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: '#ccc', marginBottom: 3 }}>{run.name}</div>
                    <div style={{ color: '#444', fontSize: '0.7rem' }}>
                      <span style={{ color: '#666' }}>{pluginName}</span>
                      {' · '}
                      {configSummary(run.config)}
                    </div>
                  </div>
                  <div style={btnRowStyle}>
                    <button onClick={() => openEdit(run)} style={mkBtn()}>EDIT</button>
                    <button onClick={() => remove(run.id)} style={mkBtn('danger')}>✕</button>
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

// ── RunForm ───────────────────────────────────────────────────────────────────

interface RunFormProps {
  name: string; onNameChange: (v: string) => void
  pluginId: string; plugins: PluginInfo[]; onPluginSelect: (id: string) => void
  schema?: Schema; config: Record<string, unknown>; onConfigChange: (v: Record<string, unknown>) => void
  onSave: () => void; onCancel: () => void; isNew?: boolean
}

function RunForm({
  name, onNameChange, pluginId, plugins, onPluginSelect,
  schema, config, onConfigChange, onSave, onCancel, isNew,
}: RunFormProps) {
  // New runs start on step 1 (type selection); edits go straight to step 2.
  const [step, setStep] = useState<1 | 2>(isNew ? 1 : 2)

  const selectedPlugin = plugins.find(p => p.id === pluginId)

  const handleCardSelect = (id: string) => {
    onPluginSelect(id)
    setStep(2)
  }

  // ── Step 1: pick plugin type ──────────────────────────────────────────────

  if (step === 1) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
        <PluginCardGrid plugins={plugins} selected={pluginId} onSelect={handleCardSelect} />
        <div>
          <button onClick={onCancel} style={mkBtn()}>CANCEL</button>
        </div>
      </div>
    )
  }

  // ── Step 2: configure + name ──────────────────────────────────────────────

  const labelStyle: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#888',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>

      {/* Back nav — only shown when creating a new run */}
      {isNew && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 12, borderBottom: '1px solid #1a1a1a' }}>
          <button
            onClick={() => setStep(1)}
            style={{
              background: 'none', border: 'none', color: '#555',
              cursor: 'pointer', padding: 0,
              fontFamily: 'monospace', fontSize: '0.72rem', letterSpacing: '0.08em',
              display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            <span style={{ fontSize: '1rem', lineHeight: 1 }}>←</span>
            <span>BACK</span>
          </button>
          <span style={{ color: '#2a2a2a' }}>·</span>
          <span style={{ color: '#666', fontFamily: 'monospace', fontSize: '0.72rem' }}>
            {selectedPlugin?.name ?? ''}
          </span>
        </div>
      )}

      {/* Plugin config */}
      {schema && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <PluginForm schema={schema} value={config} onChange={onConfigChange} />
        </div>
      )}

      {/* Run name */}
      <div style={{ borderTop: '1px solid #1a1a1a', paddingTop: 16 }}>
        <label style={labelStyle}>
          Run name
          <input
            type="text"
            value={name}
            onChange={e => onNameChange(e.target.value)}
            placeholder={`e.g. ${selectedPlugin?.name ?? 'My run'}`}
            style={fieldStyle}
          />
        </label>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={onSave}
          disabled={!name.trim()}
          style={{
            background: 'none', border: '1px solid #555', color: '#ccc',
            padding: '5px 14px', fontSize: '0.7rem', letterSpacing: '0.08em',
            cursor: name.trim() ? 'pointer' : 'default', borderRadius: 3,
            opacity: name.trim() ? 1 : 0.4,
          }}
        >
          {isNew ? 'CREATE RUN' : 'SAVE CHANGES'}
        </button>
        <button onClick={onCancel} style={mkBtn()}>CANCEL</button>
      </div>
    </div>
  )
}
