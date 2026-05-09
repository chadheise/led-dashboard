import { useEffect, useState } from 'react'
import DisplayPreview from '../components/DisplayPreview'
import TransportControls from '../components/TransportControls'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlaylistItem {
  module_id: string
  module_name: string
  app_id: string | null
  duration: number
}

interface Playlist {
  id: string
  name: string
  items: PlaylistItem[]
  is_active: boolean
}

interface Module { id: string; name: string; app_id: string; config: Record<string, unknown> }

interface EditItem { module_id: string; duration: number }

// ── Styles ────────────────────────────────────────────────────────────────────

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 720, margin: '0 auto' }
const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const heading: React.CSSProperties = { fontSize: '0.75rem', letterSpacing: '0.12em', color: '#555', margin: 0 }
const card: React.CSSProperties = { border: '1px solid #222', borderRadius: 4, padding: '14px 16px', marginBottom: 10 }
const activeCard: React.CSSProperties = { ...card, border: '1px solid #335' }
const rowStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }
const previewPane: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center',
  padding: '12px 0 16px', background: '#0d0d0d',
  borderBottom: '1px solid #1a1a1a', gap: 8,
}
const previewLabelStyle: React.CSSProperties = { fontSize: '0.6rem', letterSpacing: '0.15em', color: '#444' }
const backBtnStyle: React.CSSProperties = {
  background: 'none', border: 'none', color: '#555', cursor: 'pointer',
  padding: 0, fontFamily: 'monospace', fontSize: '0.72rem', letterSpacing: '0.08em',
  display: 'flex', alignItems: 'center', gap: 6, marginBottom: 20,
}
const fieldStyle: React.CSSProperties = {
  background: '#1a1a1a', border: '1px solid #333', color: '#ccc',
  padding: '5px 8px', borderRadius: 3, fontSize: '0.8rem', fontFamily: 'monospace',
}

const btn = (variant: 'default' | 'primary' | 'danger' | 'active' | 'eye' = 'default'): React.CSSProperties => ({
  background: variant === 'active' ? '#223' : 'none',
  border: `1px solid ${
    variant === 'primary' ? '#555' : variant === 'danger' ? '#522' : variant === 'active' ? '#446' : variant === 'eye' ? '#252525' : '#2a2a2a'
  }`,
  color: variant === 'primary' ? '#ccc' : variant === 'danger' ? '#a55' : variant === 'active' ? '#88f' : variant === 'eye' ? '#444' : '#555',
  padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3,
})

// ── Helpers ───────────────────────────────────────────────────────────────────

function stopPreview() {
  fetch('/api/preview', { method: 'DELETE' }).catch(() => {})
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Playlists() {
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [modules, setModules] = useState<Module[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [paused, setPaused] = useState(false)

  const [fName, setFName] = useState('')
  const [fItems, setFItems] = useState<EditItem[]>([])
  const [previewModuleId, setPreviewModuleId] = useState<string | null>(null)

  useEffect(() => {
    refresh()
    fetch('/api/modules').then(r => r.json()).then(setModules)
    fetch('/api/status').then(r => r.json()).then(s => {
      if (typeof s.paused === 'boolean') setPaused(s.paused)
    })
  }, [])

  useEffect(() => { if (!editing) stopPreview() }, [editing])
  useEffect(() => () => { stopPreview() }, [])

  const resolvedPreviewId = previewModuleId ?? fItems[0]?.module_id ?? null
  useEffect(() => {
    if (!editing || !resolvedPreviewId) return
    const module = modules.find(m => m.id === resolvedPreviewId)
    if (!module) return
    fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: module.app_id, config: module.config }),
    }).catch(() => {})
  }, [editing, resolvedPreviewId])

  const refresh = () => fetch('/api/playlists').then(r => r.json()).then(setPlaylists)

  // ── Navigation ──────────────────────────────────────────────────────────────

  const openNew = () => {
    setFName(''); setFItems([]); setPreviewModuleId(null)
    setEditing('new')
  }

  const openEdit = (pl: Playlist) => {
    setFName(pl.name)
    setFItems(pl.items.map(it => ({ module_id: it.module_id, duration: it.duration })))
    setPreviewModuleId(null)
    setEditing(pl.id)
  }

  const goBack = () => setEditing(null)

  // ── CRUD ────────────────────────────────────────────────────────────────────

  const save = async () => {
    const body = { name: fName, items: fItems }
    if (editing === 'new') {
      await fetch('/api/playlists', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
    } else {
      await fetch(`/api/playlists/${editing}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
    }
    setEditing(null)
    refresh()
  }

  const remove = async (id: string) => {
    await fetch(`/api/playlists/${id}`, { method: 'DELETE' })
    setPlaylists(prev => prev.filter(p => p.id !== id))
    if (editing === id) setEditing(null)
  }

  const activate = async (id: string) => {
    await fetch(`/api/playlists/${id}/activate`, { method: 'POST' })
    setPlaylists(prev => prev.map(p => ({ ...p, is_active: p.id === id })))
  }

  // ── Transport ───────────────────────────────────────────────────────────────

  const prev = () => fetch('/api/playlist/prev', { method: 'POST' }).then(() => setPaused(false))
  const next = () => fetch('/api/playlist/next', { method: 'POST' }).then(() => setPaused(false))
  const togglePlayPause = () =>
    fetch('/api/playlist/playpause', { method: 'POST' })
      .then(r => r.json()).then(d => setPaused(d.paused))

  // ── Playlist form helpers ───────────────────────────────────────────────────

  const addItem = () => {
    if (!modules.length) return
    setFItems(prev => [...prev, { module_id: modules[0].id, duration: 30 }])
  }

  const updateItem = (idx: number, patch: Partial<EditItem>) =>
    setFItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))

  const removeItem = (idx: number) => {
    if (previewModuleId === fItems[idx]?.module_id) setPreviewModuleId(null)
    setFItems(prev => prev.filter((_, i) => i !== idx))
  }

  const moduleName = (id: string) => modules.find(m => m.id === id)?.name ?? id

  // ── Derived ─────────────────────────────────────────────────────────────────

  const isEditing = editing !== null
  const sortedPlaylists = [...playlists].sort((a, b) => {
    if (a.is_active === b.is_active) return 0
    return a.is_active ? -1 : 1
  })

  let pLabel = 'LIVE DISPLAY'
  if (editing === 'new') {
    pLabel = resolvedPreviewId
      ? `NEW PLAYLIST · ${moduleName(resolvedPreviewId)}`
      : 'NEW PLAYLIST'
  } else if (editing) {
    pLabel = resolvedPreviewId
      ? `EDITING · ${moduleName(resolvedPreviewId)}`
      : `EDITING · ${fName || '…'}`
  }

  return (
    <>
      {/* Preview pane */}
      <div style={previewPane}>
        <span style={previewLabelStyle}>{pLabel}</span>
        <DisplayPreview
          wsUrl={isEditing ? '/ws/preview/edit' : '/ws/preview'}
          scale={3}
          actions={<TransportControls paused={paused} onPrev={prev} onPlayPause={togglePlayPause} onNext={next} />}
        />
      </div>

      <div style={page}>

        {/* Back button — shown on all sub-pages */}
        {isEditing && (
          <button onClick={goBack} style={backBtnStyle}>
            <span style={{ fontSize: '1rem', lineHeight: 1 }}>←</span>
            <span>← PLAYLISTS</span>
          </button>
        )}

        {/* ── Playlist list ── */}
        {!isEditing && (
          <>
            <div style={hdr}>
              <h2 style={heading}>PLAYLISTS</h2>
              <button onClick={openNew} style={btn('primary')}>+ NEW PLAYLIST</button>
            </div>
            {sortedPlaylists.map(pl => (
              <div key={pl.id} style={pl.is_active ? activeCard : card}>
                <div style={rowStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ color: pl.is_active ? '#88f' : '#555', fontSize: '0.8rem' }}>
                      {pl.is_active ? '◉' : '○'}
                    </span>
                    <span style={{ color: '#ccc' }}>{pl.name}</span>
                    {pl.is_active && (
                      <span style={{ fontSize: '0.65rem', color: '#446', letterSpacing: '0.1em' }}>ACTIVE</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {!pl.is_active && (
                      <button onClick={() => activate(pl.id)} style={btn('active')}>ACTIVATE</button>
                    )}
                    <button onClick={() => openEdit(pl)} style={btn()}>EDIT</button>
                    <button onClick={() => remove(pl.id)} style={btn('danger')}>✕</button>
                  </div>
                </div>
                {pl.items.length > 0 ? (
                  <ol style={{ margin: '10px 0 0 20px', padding: 0, color: '#444', fontSize: '0.72rem', lineHeight: '1.8' }}>
                    {pl.items.map((it, i) => (
                      <li key={i}>
                        <span style={{ color: '#666' }}>{it.module_name}</span>
                        <span style={{ color: '#333' }}> · {it.duration}s</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div style={{ marginTop: 8, color: '#333', fontSize: '0.72rem' }}>Empty playlist</div>
                )}
              </div>
            ))}
          </>
        )}

        {/* ── New / edit playlist form ── */}
        {isEditing && (
          <PlaylistForm
            name={fName} onNameChange={setFName}
            items={fItems} modules={modules}
            previewModuleId={resolvedPreviewId}
            onPreview={id => setPreviewModuleId(id)}
            onAddItem={addItem} onUpdateItem={updateItem} onRemoveItem={removeItem}
            moduleName={moduleName} onSave={save} isNew={editing === 'new'}
          />
        )}
      </div>
    </>
  )
}

// ── PlaylistForm ──────────────────────────────────────────────────────────────

interface PlaylistFormProps {
  name: string; onNameChange: (v: string) => void
  items: EditItem[]; modules: Module[]
  previewModuleId: string | null; onPreview: (id: string) => void
  onAddItem: () => void
  onUpdateItem: (idx: number, patch: Partial<EditItem>) => void
  onRemoveItem: (idx: number) => void
  moduleName: (id: string) => string
  onSave: () => void; isNew?: boolean
}

function PlaylistForm({ name, onNameChange, items, modules, previewModuleId, onPreview, onAddItem, onUpdateItem, onRemoveItem, moduleName, onSave, isNew }: PlaylistFormProps) {
  const labelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#888' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <label style={labelStyle}>
        Playlist name
        <input
          type="text" value={name} onChange={e => onNameChange(e.target.value)}
          style={{ ...fieldStyle, width: '100%', boxSizing: 'border-box' }}
          placeholder="e.g. Daily Rotation"
        />
      </label>

      <div>
        <div style={{ fontSize: '0.75rem', color: '#555', marginBottom: 8 }}>MODULES IN PLAYLIST</div>
        {items.length === 0 && (
          <div style={{ color: '#333', fontSize: '0.75rem', marginBottom: 8 }}>No modules yet — add one below.</div>
        )}
        {items.map((item, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <button
              onClick={() => onPreview(item.module_id)}
              title="Preview this module"
              style={{
                ...btn('eye'), padding: '5px 8px',
                color: previewModuleId === item.module_id ? '#88f' : '#333',
                border: `1px solid ${previewModuleId === item.module_id ? '#446' : '#252525'}`,
              }}
            >▶</button>
            <select
              value={item.module_id}
              onChange={e => onUpdateItem(idx, { module_id: e.target.value })}
              style={{ ...fieldStyle, flex: 1 }}
            >
              {modules.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <input
              type="number" value={item.duration} min={1}
              onChange={e => onUpdateItem(idx, { duration: Number(e.target.value) })}
              style={{ ...fieldStyle, width: 64 }} title="Duration (s)"
            />
            <span style={{ color: '#444', fontSize: '0.7rem' }}>s</span>
            <button onClick={() => onRemoveItem(idx)} style={btn('danger')}>✕</button>
          </div>
        ))}
        <button onClick={onAddItem} disabled={!modules.length} style={{ ...btn(), marginTop: 2 }}>
          + ADD MODULE
        </button>
      </div>

      <div>
        <button
          onClick={onSave} disabled={!name.trim()}
          style={{
            background: 'none', border: '1px solid #555', color: '#ccc',
            padding: '5px 14px', fontSize: '0.7rem', letterSpacing: '0.08em',
            cursor: name.trim() ? 'pointer' : 'default', borderRadius: 3,
            opacity: name.trim() ? 1 : 0.4,
          }}
        >
          {isNew ? 'CREATE PLAYLIST' : 'SAVE CHANGES'}
        </button>
      </div>
    </div>
  )
}
