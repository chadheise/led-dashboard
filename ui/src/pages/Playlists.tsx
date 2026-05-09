import { useEffect, useState } from 'react'

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

interface Run { id: string; name: string; plugin_id: string }

// editable item (might be a "new unsaved" item before a run is chosen)
interface EditItem { run_id: string; duration: number }

// ── Styles ────────────────────────────────────────────────────────────────────

const page: React.CSSProperties = { padding: '24px 32px', maxWidth: 720 }
const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const heading: React.CSSProperties = { fontSize: '0.75rem', letterSpacing: '0.12em', color: '#555', margin: 0 }
const card: React.CSSProperties = { border: '1px solid #222', borderRadius: 4, padding: '14px 16px', marginBottom: 10 }
const activeCard: React.CSSProperties = { ...card, border: '1px solid #335' }
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }
const btn = (variant: 'default' | 'primary' | 'danger' | 'active' = 'default'): React.CSSProperties => ({
  background: variant === 'active' ? '#223' : 'none',
  border: `1px solid ${variant === 'primary' ? '#555' : variant === 'danger' ? '#522' : variant === 'active' ? '#446' : '#2a2a2a'}`,
  color: variant === 'primary' ? '#ccc' : variant === 'danger' ? '#a55' : variant === 'active' ? '#88f' : '#555',
  padding: '5px 12px', fontSize: '0.7rem', letterSpacing: '0.08em', cursor: 'pointer', borderRadius: 3,
})
const fieldStyle: React.CSSProperties = {
  background: '#1a1a1a', border: '1px solid #333', color: '#ccc',
  padding: '5px 8px', borderRadius: 3, fontSize: '0.8rem', fontFamily: 'monospace',
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Playlists() {
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [editing, setEditing] = useState<string | null>(null) // playlist id or 'new'

  // form state
  const [fName, setFName] = useState('')
  const [fItems, setFItems] = useState<EditItem[]>([])

  useEffect(() => {
    refresh()
    fetch('/api/runs').then(r => r.json()).then(setRuns)
  }, [])

  const refresh = () =>
    fetch('/api/playlists').then(r => r.json()).then(setPlaylists)

  const openNew = () => {
    setFName('')
    setFItems([])
    setEditing('new')
  }

  const openEdit = (pl: Playlist) => {
    setFName(pl.name)
    setFItems(pl.items.map(it => ({ run_id: it.run_id, duration: it.duration })))
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

  // form helpers
  const addItem = () => {
    if (!runs.length) return
    setFItems(prev => [...prev, { run_id: runs[0].id, duration: 30 }])
  }

  const updateItem = (idx: number, patch: Partial<EditItem>) =>
    setFItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))

  const removeItem = (idx: number) =>
    setFItems(prev => prev.filter((_, i) => i !== idx))

  const runName = (id: string) => runs.find(r => r.id === id)?.name ?? id

  return (
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
              onAddItem={addItem} onUpdateItem={updateItem} onRemoveItem={removeItem}
              runName={runName} onSave={save} onCancel={cancel}
            />
          ) : (
            <>
              <div style={row}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ color: pl.is_active ? '#88f' : '#555', fontSize: '0.8rem' }}>
                    {pl.is_active ? '◉' : '○'}
                  </span>
                  <span style={{ color: '#ccc' }}>{pl.name}</span>
                  {pl.is_active && (
                    <span style={{ fontSize: '0.65rem', color: '#556', letterSpacing: '0.1em' }}>ACTIVE</span>
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
              {pl.items.length > 0 && (
                <ol style={{ margin: '10px 0 0 20px', padding: 0, color: '#444', fontSize: '0.72rem', lineHeight: '1.8' }}>
                  {pl.items.map((it, i) => (
                    <li key={i}>
                      <span style={{ color: '#666' }}>{it.run_name}</span>
                      {' '}
                      <span style={{ color: '#333' }}>· {it.duration}s</span>
                    </li>
                  ))}
                </ol>
              )}
              {pl.items.length === 0 && (
                <div style={{ marginTop: 8, color: '#333', fontSize: '0.72rem' }}>Empty playlist</div>
              )}
            </>
          )}
        </div>
      ))}
    </div>
  )
}

// ── PlaylistForm sub-component ────────────────────────────────────────────────

interface PlaylistFormProps {
  name: string; onNameChange: (v: string) => void
  items: EditItem[]; runs: Run[]
  onAddItem: () => void
  onUpdateItem: (idx: number, patch: Partial<EditItem>) => void
  onRemoveItem: (idx: number) => void
  runName: (id: string) => string
  onSave: () => void; onCancel: () => void; isNew?: boolean
}

function PlaylistForm({ name, onNameChange, items, runs, onAddItem, onUpdateItem, onRemoveItem, onSave, onCancel, isNew }: PlaylistFormProps) {
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
        <button onClick={onSave} disabled={!name.trim()} style={btn('primary')}>
          {isNew ? 'CREATE PLAYLIST' : 'SAVE CHANGES'}
        </button>
        <button onClick={onCancel} style={btn()}>CANCEL</button>
      </div>
    </div>
  )
}
