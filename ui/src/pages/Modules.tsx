import { useEffect, useRef, useState } from 'react'
import AppForm from '../components/AppForm'
import DisplayPreview from '../components/DisplayPreview'
import TransportControls from '../components/TransportControls'
import {
  C, F,
  appCardStyle, backBtnStyle, btn, cardStyle,
  fieldStyle, headingStyle, labelStyle,
  pageStyle, previewLabelStyle, previewPaneStyle, sectionLabelStyle,
} from '../theme'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Module {
  id: string; name: string; app_id: string; config: Record<string, unknown>
}

interface Schema {
  type: 'object'
  properties: Record<string, {
    type: string; title?: string; default?: unknown
    enum?: string[]; minimum?: number; maximum?: number; items?: { type: string }
  }>
  required?: string[]
}

interface AppInfo { id: string; name: string; description: string; schema: Schema }

// ── App icons ─────────────────────────────────────────────────────────────────

const S = { width: 28, height: 28, display: 'block' as const }

const APP_ICONS: Record<string, React.ReactElement> = {
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

// ── Local layout styles (not visual, no theming needed) ───────────────────────

const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }
const btnRow: React.CSSProperties = { display: 'flex', gap: 6, flexShrink: 0 }

// ── Helpers ───────────────────────────────────────────────────────────────────

function defaultsFromSchema(schema: Schema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[k] = prop.default
  }
  return out
}

function configSummary(config: Record<string, unknown>): string {
  const parts = Object.entries(config).slice(0, 3)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? (v as unknown[]).join(', ') : String(v)}`)
  return parts.join(' · ') || '(no config)'
}

function stopPreview() { fetch('/api/preview', { method: 'DELETE' }).catch(() => {}) }

// ── App card grid ─────────────────────────────────────────────────────────────

function AppCardGrid({ apps, selected, onSelect }: { apps: AppInfo[]; selected: string; onSelect: (id: string) => void }) {
  const [hovered, setHovered] = useState<string | null>(null)
  return (
    <div>
      <div style={sectionLabelStyle}>APP TYPE</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {apps.map(app => {
          const sel = app.id === selected
          const hov = hovered === app.id && !sel
          return (
            <button key={app.id} type="button"
              onClick={() => onSelect(app.id)}
              onMouseEnter={() => setHovered(app.id)}
              onMouseLeave={() => setHovered(null)}
              style={appCardStyle(sel, hov)}
            >
              <div style={{ color: sel ? C.sage : C.textMuted, flexShrink: 0 }}>
                {APP_ICONS[app.id] ?? <div style={{ width: 28, height: 28, background: C.surface, borderRadius: 4 }} />}
              </div>
              <div style={{ fontSize: F.size.md, fontFamily: F.family, color: sel ? C.sage : C.textSecondary }}>
                {app.name}
              </div>
              {app.description && (
                <div style={{ fontSize: F.size.sm, color: sel ? C.textSecondary : C.textMuted, lineHeight: 1.5 }}>
                  {app.description}
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

export default function Modules() {
  const [modules, setModules] = useState<Module[]>([])
  const [apps, setApps] = useState<AppInfo[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [step, setStep] = useState<1 | 2>(1)
  const [fName, setFName] = useState('')
  const [fAppId, setFAppId] = useState('')
  const [fConfig, setFConfig] = useState<Record<string, unknown>>({})
  const [paused, setPaused] = useState(false)

  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/modules').then(r => r.json()),
      fetch('/api/apps').then(r => r.json()),
    ]).then(([m, a]) => { setModules(m); setApps(a) })
    fetch('/api/status').then(r => r.json()).then(s => {
      if (typeof s.paused === 'boolean') setPaused(s.paused)
    })
  }, [])

  useEffect(() => { if (!editing) stopPreview() }, [editing])
  useEffect(() => () => { stopPreview() }, [])

  useEffect(() => {
    if (!editing || !fAppId) return
    if (previewTimer.current) clearTimeout(previewTimer.current)
    previewTimer.current = setTimeout(() => {
      fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: fAppId, config: fConfig }),
      })
    }, 300)
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current) }
  }, [editing, fAppId, fConfig])

  // ── Transport ──────────────────────────────────────────────────────────────
  const prev = () => fetch('/api/playlist/prev', { method: 'POST' }).then(() => setPaused(false))
  const next = () => fetch('/api/playlist/next', { method: 'POST' }).then(() => setPaused(false))
  const togglePlayPause = () =>
    fetch('/api/playlist/playpause', { method: 'POST' }).then(r => r.json()).then(d => setPaused(d.paused))

  // ── Navigation ─────────────────────────────────────────────────────────────
  const openNew = () => { setFName(''); setFAppId(''); setFConfig({}); setStep(1); setEditing('new') }
  const openEdit = (m: Module) => { setFName(m.name); setFAppId(m.app_id); setFConfig(m.config); setStep(2); setEditing(m.id) }
  const goBack = () => { if (editing === 'new' && step === 2) setStep(1); else setEditing(null) }

  const handleAppSelect = (id: string) => {
    if (id !== fAppId) {
      setFAppId(id)
      const schema = apps.find(a => a.id === id)?.schema
      if (schema) setFConfig(defaultsFromSchema(schema))
    }
    setStep(2)
  }

  // ── CRUD ───────────────────────────────────────────────────────────────────
  const save = async () => {
    const body = { name: fName, app_id: fAppId, config: fConfig }
    if (editing === 'new') {
      const m: Module = await fetch('/api/modules', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(r => r.json())
      setModules(prev => [...prev, m])
    } else {
      await fetch(`/api/modules/${editing}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      setModules(prev => prev.map(m => m.id === editing ? { ...m, ...body } : m))
    }
    setEditing(null)
  }

  const remove = async (id: string) => {
    await fetch(`/api/modules/${id}`, { method: 'DELETE' })
    setModules(prev => prev.filter(m => m.id !== id))
    if (editing === id) setEditing(null)
  }

  // ── Derived ────────────────────────────────────────────────────────────────
  const currentSchema = apps.find(a => a.id === fAppId)?.schema
  const selectedApp = apps.find(a => a.id === fAppId)
  const isEditing = editing !== null
  const showEditPreview = isEditing && fAppId !== ''

  let pLabel = 'LIVE DISPLAY'
  if (editing === 'new' && step === 1 && fAppId) pLabel = `APP PREVIEW · ${selectedApp?.name ?? ''}`
  else if (editing === 'new' && step === 2)       pLabel = 'NEW MODULE PREVIEW'
  else if (editing && editing !== 'new')           pLabel = `MODULE PREVIEW · ${fName}`

  const backLabel = editing === 'new' && step === 2 ? 'SELECT APP' : 'MODULES'

  const canSave = fName.trim() !== ''

  return (
    <>
      <div style={previewPaneStyle}>
        <span style={previewLabelStyle}>{pLabel}</span>
        <DisplayPreview
          wsUrl={showEditPreview ? '/ws/preview/edit' : '/ws/preview'}
          scale={3}
          actions={<TransportControls paused={paused} onPrev={prev} onPlayPause={togglePlayPause} onNext={next} />}
        />
      </div>

      <div style={pageStyle}>
        {isEditing && (
          <button onClick={goBack} style={backBtnStyle}>
            <span style={{ fontSize: '1.3rem', lineHeight: 1 }}>←</span>
            <span>{backLabel}</span>
          </button>
        )}

        {/* Module list */}
        {!isEditing && (
          <>
            <div style={hdr}>
              <h2 style={headingStyle}>MODULES</h2>
              <button onClick={openNew} style={btn('primary')}>+ NEW MODULE</button>
            </div>
            {modules.map(m => {
              const appName = apps.find(a => a.id === m.app_id)?.name ?? m.app_id
              return (
                <div key={m.id} style={cardStyle()}>
                  <div style={row}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ color: C.textPrimary, marginBottom: 3, fontFamily: F.family }}>{m.name}</div>
                      <div style={{ color: C.textMuted, fontSize: F.size.sm, fontFamily: F.family }}>
                        <span style={{ color: C.textSecondary }}>{appName}</span>
                        {' · '}{configSummary(m.config)}
                      </div>
                    </div>
                    <div style={btnRow}>
                      <button onClick={() => openEdit(m)} style={btn()}>EDIT</button>
                      <button onClick={() => remove(m.id)} style={btn('danger')}>✕</button>
                    </div>
                  </div>
                </div>
              )
            })}
          </>
        )}

        {/* Step 1: app type selection */}
        {isEditing && editing === 'new' && step === 1 && (
          <AppCardGrid apps={apps} selected={fAppId} onSelect={handleAppSelect} />
        )}

        {/* Step 2 / edit existing: config + name */}
        {isEditing && (editing !== 'new' || step === 2) && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {currentSchema && <AppForm schema={currentSchema} value={fConfig} onChange={setFConfig} />}

            <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
              <label style={labelStyle}>
                Module name
                <input
                  type="text" value={fName} onChange={e => setFName(e.target.value)}
                  placeholder={`e.g. ${selectedApp?.name ?? 'My module'}`}
                  style={fieldStyle}
                />
              </label>
            </div>

            <div>
              <button
                onClick={save} disabled={!canSave}
                style={{ ...btn('success'), opacity: canSave ? 1 : 0.4, cursor: canSave ? 'pointer' : 'default' }}
              >
                {editing === 'new' ? 'CREATE MODULE' : 'SAVE CHANGES'}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
