import { useEffect, useState } from 'react'
import DisplayPreview from '../components/DisplayPreview'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlaylistItem {
  run_id: string
  run_name: string
  plugin_id: string | null
  duration: number
}

interface Playlist {
  id: string
  name: string
  items: PlaylistItem[]
  is_active: boolean
}

interface Run { id: string; name: string; plugin_id: string; config: Record<string, unknown> }

interface EditItem { run_id: string; duration: number }

// ── Constants ─────────────────────────────────────────────────────────────────

const NAV_H = 35

// ── Styles ────────────────────────────────────────────────────────────────────

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 720 }
const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const heading: React.CSSProperties = { fontSize: '0.75rem', letterSpacing: '0.12em', color: '#555', margin: 0 }
const card: React.CSSProperties = { border: '1px solid #222', borderRadius: 4, padding: '14px 16px', marginBottom: 10 }
const activeCard: React.CSSProperties = { ...card, border: '1px solid #335' }
const rowStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }
const btn = (variant: 'default' | 'primary' | 'danger' | 'active' | 'eye' = 'default'): React.CSSProperties => ({
  background: variant === 'active' ? '#223' : 'none',
  border: `1px solid ${
    variant === 'primary' ? '#555' : variant === 'danger' ? '#522' : variant === 'active' ? '#446' : variant === 'eye' ? '#252525' : '#2a2a2a'
  }`,
  color: variant === 'primary' ? '#ccc' : variant === 'danger' ? '#a55' : variant === 'active' ? '#88f' : variant === 'eye' ? '#444' : '#555',
  padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3,
})
const fieldStyle: React.CSSProperties = {
  background: '#1a1a1a', border: '1px solid #333', color: '#ccc',
  padding: '5px 8px', borderRadius: 3, fontSize: '0.8rem', fontFamily: 'monospace',
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

function stopPreview() {
  fetch('/api/preview', { method: 'DELETE' }).catch(() => {})
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Playlists() {
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [editing, setEditing] = useState<string | null>(null)

  const [fName, setFName] = useState('')
  const [fItems, setFItems] = useState<EditItem[]>([])
  // Which run_id the user wants to preview (null = auto first)
  const [previewRunId, setPreviewRunId] = useState<string | null>(null)

  useEffect(() => {
    refresh()
    fetch('/api/runs').then(r => r.json()).then(setRuns)
  }, [])

  // Stop preview when editing closes or page unmounts
  useEffect(() => {
    if (!editing) stopPreview()
  }, [editing])
  useEffect(() => () => { stopPreview() }, [])

  // Fire preview when the target run changes
  const resolvedPreviewId = previewRunId ?? fItems[0]?.run_id ?? null
  useEffect(() => {
    if (!editing || !resolvedPreviewId) return
    const run = runs.find(r => r.id === resolvedPreviewId)
    if (!run) return
    fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plugin_id: run.plugin_id, config: run.config }),
    }).catch(() => {})
  }, [editing, resolvedPreviewId])

  const refresh = () =>
    fetch('/api/playlists').then(r => r.json()).then(setPlaylists)

  const openNew = () => {
    setFName('')
    setFItems([])
    setPreviewRunId(null)
    setEditing('new')
  }

  const openEdit = (pl: Playlist) => {
    setFName(pl.name)
    setFItems(pl.items.map(it => ({ run_id: it.run_id, duration: it.duration })))
    setPreviewRunId(null)
    setEditing(pl.id)
  }

  const cancel = () => setEditing(null)

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

  const next = () => fetch('/api/playlist/next', { method: 'POST' })

  const addItem = () => {
    if (!runs.length) return
    const newItem = { run_id: runs[0].id, duration: 30 }
    setFItems(prev => [...prev, newItem])
  }

  const updateItem = (idx: number, patch: Partial<EditItem>) =>
    setFItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))

  const removeItem = (idx: number) => {
    if (previewRunId === fItems[idx]?.run_id) setPreviewRunId(null)
    setFItems(prev => prev.filter((_, i) => i !== idx))
  }

  const runName = (id: string) => runs.find(r => r.id === id)?.name ?? id

  const editLabel = fName || (editing === 'new' ? 'New playlist' : 'Editing')
  const previewLabel = resolvedPreviewId ? runName(resolvedPreviewId) : editLabel

  return (
    <>
      {editing && <EditPreviewBar label={previewLabel} />}

      <div style={page}>
        <div style={hdr}>
          <h2 style={heading}>PLAYLISTS</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={next} style={btn()}>NEXT →</button>
            {editing !== 'new' && <button onClick={openNew} style={btn('primary')}>+ NEW PLAYLIST</button>}
          </div>
        </div>

        {editing === 'new' && (
          <div style={{ ...card, border: '1px solid #333' }}>
            <PlaylistForm
              name={fName} onNameChange={setFName}
              items={fItems} runs={runs}
              previewRunId={resolvedPreviewId}
              onPreview={id => setPreviewRunId(id)}
              onAddItem={addItem} onUpdateItem={updateItem} onRemoveItem={removeItem}
              runName={runName} onSave={save} onCancel={cancel} isNew
            />
          </div>
        )}

        {playlists.map(pl => (
          <div key={pl.id} style={pl.is_active ? activeCard : card}>
            {editing === pl.id ? (
              <PlaylistForm
                name={fName} onNameChange={setFName}
                items={fItems} runs={runs}
                previewRunId={resolvedPreviewId}
                onPreview={id => setPreviewRunId(id)}
                onAddItem={addItem} onUpdateItem={updateItem} onRemoveItem={removeItem}
                runName={runName} onSave={save} onCancel={cancel}
              />
            ) : (
              <>
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
                        <span style={{ color: '#666' }}>{it.run_name}</span>
                        <span style={{ color: '#333' }}> · {it.duration}s</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div style={{ marginTop: 8, color: '#333', fontSize: '0.72rem' }}>Empty playlist</div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

// ── PlaylistForm ──────────────────────────────────────────────────────────────

interface PlaylistFormProps {
  name: string; onNameChange: (v: string) => void
  items: EditItem[]; runs: Run[]
  previewRunId: string | null; onPreview: (id: string) => void
  onAddItem: () => void
  onUpdateItem: (idx: number, patch: Partial<EditItem>) => void
  onRemoveItem: (idx: number) => void
  runName: (id: string) => string
  onSave: () => void; onCancel: () => void; isNew?: boolean
}

function PlaylistForm({ name, onNameChange, items, runs, previewRunId, onPreview, onAddItem, onUpdateItem, onRemoveItem, onSave, onCancel, isNew }: PlaylistFormProps) {
  const labelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#888' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <label style={labelStyle}>
        Playlist name
        <input
          type="text" value={name} onChange={e => onNameChange(e.target.value)}
          style={{ ...fieldStyle, width: '100%', boxSizing: 'border-box' }}
          placeholder="e.g. Daily Rotation"
        />
      </label>

      <div>
        <div style={{ fontSize: '0.75rem', color: '#555', marginBottom: 6 }}>RUNS IN PLAYLIST</div>
        {items.length === 0 && (
          <div style={{ color: '#333', fontSize: '0.75rem', marginBottom: 8 }}>No runs yet — add one below.</div>
        )}
        {items.map((item, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            {/* Preview toggle */}
            <button
              onClick={() => onPreview(item.run_id)}
              title="Preview this run"
              style={{
                ...btn('eye'),
                padding: '5px 8px',
                color: previewRunId === item.run_id ? '#88f' : '#333',
                border: `1px solid ${previewRunId === item.run_id ? '#446' : '#252525'}`,
              }}
            >
              ▶
            </button>
            <select
              value={item.run_id}
              onChange={e => onUpdateItem(idx, { run_id: e.target.value })}
              style={{ ...fieldStyle, flex: 1 }}
            >
              {runs.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
            <input
              type="number" value={item.duration} min={1}
              onChange={e => onUpdateItem(idx, { duration: Number(e.target.value) })}
              style={{ ...fieldStyle, width: 64 }}
              title="Duration (s)"
            />
            <span style={{ color: '#444', fontSize: '0.7rem' }}>s</span>
            <button onClick={() => onRemoveItem(idx)} style={btn('danger')}>✕</button>
          </div>
        ))}
        <button onClick={onAddItem} disabled={!runs.length} style={{ ...btn(), marginTop: 2 }}>
          + ADD RUN
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, paddingTop: 4 }}>
        <button
          onClick={onSave}
          disabled={!name.trim()}
          style={{ background: 'none', border: '1px solid #555', color: '#ccc', padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: name.trim() ? 'pointer' : 'default', borderRadius: 3, opacity: name.trim() ? 1 : 0.4 }}
        >
          {isNew ? 'CREATE PLAYLIST' : 'SAVE CHANGES'}
        </button>
        <button onClick={onCancel} style={{ background: 'none', border: '1px solid #2a2a2a', color: '#555', padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3 }}>CANCEL</button>
      </div>
    </div>
  )
}
