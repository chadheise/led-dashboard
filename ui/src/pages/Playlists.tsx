import { useEffect, useState } from 'react'
import DisplayPreview from '../components/DisplayPreview'
import TransportControls from '../components/TransportControls'
import {
  C, F,
  backBtnStyle, btn, cardStyle,
  fieldStyle, headingStyle, labelStyle,
  pageStyle, previewLabelStyle, previewPaneStyle, sectionLabelStyle,
} from '../theme'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlaylistItem { module_id: string; module_name: string; app_id: string | null; duration: number }
interface Playlist { id: string; name: string; items: PlaylistItem[]; is_active: boolean }
interface Module { id: string; name: string; app_id: string; config: Record<string, unknown> }
interface EditItem { module_id: string; duration: number }

// ── Local layout styles ───────────────────────────────────────────────────────

const hdr: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }
const rowStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }

function eyeBtn(active: boolean): React.CSSProperties {
  return {
    ...btn('eye'),
    padding: '5px 8px',
    color: active ? C.positive : btn('eye').color as string,
    borderColor: active ? C.positive : btn('eye').borderColor as string,
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function stopPreview() { fetch('/api/preview', { method: 'DELETE' }).catch(() => {}) }

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
    const mod = modules.find(m => m.id === resolvedPreviewId)
    if (!mod) return
    fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: mod.app_id, config: mod.config }),
    }).catch(() => {})
  }, [editing, resolvedPreviewId])

  const refresh = () => fetch('/api/playlists').then(r => r.json()).then(setPlaylists)

  // ── Navigation ─────────────────────────────────────────────────────────────
  const openNew = () => { setFName(''); setFItems([]); setPreviewModuleId(null); setEditing('new') }
  const openEdit = (pl: Playlist) => {
    setFName(pl.name)
    setFItems(pl.items.map(it => ({ module_id: it.module_id, duration: it.duration })))
    setPreviewModuleId(null)
    setEditing(pl.id)
  }
  const goBack = () => setEditing(null)

  // ── CRUD ───────────────────────────────────────────────────────────────────
  const save = async () => {
    const body = { name: fName, items: fItems }
    if (editing === 'new') {
      await fetch('/api/playlists', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } else {
      await fetch(`/api/playlists/${editing}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
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

  // ── Transport ──────────────────────────────────────────────────────────────
  const prev = () => fetch('/api/playlist/prev', { method: 'POST' }).then(() => setPaused(false))
  const next = () => fetch('/api/playlist/next', { method: 'POST' }).then(() => setPaused(false))
  const togglePlayPause = () =>
    fetch('/api/playlist/playpause', { method: 'POST' }).then(r => r.json()).then(d => setPaused(d.paused))

  // ── Playlist form helpers ──────────────────────────────────────────────────
  const addItem = () => { if (modules.length) setFItems(prev => [...prev, { module_id: modules[0].id, duration: 30 }]) }
  const updateItem = (idx: number, patch: Partial<EditItem>) =>
    setFItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))
  const removeItem = (idx: number) => {
    if (previewModuleId === fItems[idx]?.module_id) setPreviewModuleId(null)
    setFItems(prev => prev.filter((_, i) => i !== idx))
  }
  const moduleName = (id: string) => modules.find(m => m.id === id)?.name ?? id

  // ── Derived ────────────────────────────────────────────────────────────────
  const isEditing = editing !== null
  const sortedPlaylists = [...playlists].sort((a, b) => {
    if (a.is_active === b.is_active) return 0
    return a.is_active ? -1 : 1
  })

  let pLabel = 'LIVE DISPLAY'
  if (editing === 'new')
    pLabel = resolvedPreviewId ? `NEW PLAYLIST · ${moduleName(resolvedPreviewId)}` : 'NEW PLAYLIST'
  else if (editing)
    pLabel = resolvedPreviewId ? `EDITING · ${moduleName(resolvedPreviewId)}` : `EDITING · ${fName || '…'}`

  const canSave = fName.trim() !== ''

  return (
    <>
      <div style={previewPaneStyle}>
        <span style={previewLabelStyle}>{pLabel}</span>
        <DisplayPreview
          wsUrl={isEditing ? '/ws/preview/edit' : '/ws/preview'}
          scale={3}
          actions={<TransportControls paused={paused} onPrev={prev} onPlayPause={togglePlayPause} onNext={next} />}
        />
      </div>

      <div style={pageStyle}>
        {isEditing && (
          <button onClick={goBack} style={backBtnStyle}>
            <span style={{ fontSize: '1.3rem', lineHeight: 1 }}>←</span>
            <span>PLAYLISTS</span>
          </button>
        )}

        {/* Playlist list */}
        {!isEditing && (
          <>
            <div style={hdr}>
              <h2 style={headingStyle}>PLAYLISTS</h2>
              <button onClick={openNew} style={btn('primary')}>+ NEW PLAYLIST</button>
            </div>
            {sortedPlaylists.map(pl => (
              <div key={pl.id} style={cardStyle(pl.is_active)}>
                <div style={rowStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ color: pl.is_active ? C.positive : C.textMuted, fontSize: F.size.md }}>
                      {pl.is_active ? '◉' : '○'}
                    </span>
                    <span style={{ color: C.textPrimary, fontFamily: F.family }}>{pl.name}</span>
                    {pl.is_active && (
                      <span style={{ fontSize: F.size.xs, color: C.positive, letterSpacing: F.tracking.wider, fontFamily: F.family }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {!pl.is_active && <button onClick={() => activate(pl.id)} style={btn('active')}>ACTIVATE</button>}
                    <button onClick={() => openEdit(pl)} style={btn()}>EDIT</button>
                    <button onClick={() => remove(pl.id)} style={btn('danger')}>✕</button>
                  </div>
                </div>
                {pl.items.length > 0 ? (
                  <ol style={{ margin: '10px 0 0 20px', padding: 0, fontSize: F.size.sm, lineHeight: '1.8', fontFamily: F.family }}>
                    {pl.items.map((it, i) => (
                      <li key={i}>
                        <span style={{ color: C.textSecondary }}>{it.module_name}</span>
                        <span style={{ color: C.textMuted }}> · {it.duration}s</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div style={{ marginTop: 8, color: C.textDim, fontSize: F.size.sm, fontFamily: F.family }}>Empty playlist</div>
                )}
              </div>
            ))}
          </>
        )}

        {/* New / edit playlist form */}
        {isEditing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <label style={labelStyle}>
              Playlist name
              <input
                type="text" value={fName} onChange={e => setFName(e.target.value)}
                style={fieldStyle} placeholder="e.g. Daily Rotation"
              />
            </label>

            <div>
              <div style={sectionLabelStyle}>MODULES IN PLAYLIST</div>
              {fItems.length === 0 && (
                <div style={{ color: C.textDim, fontSize: F.size.sm, marginBottom: 8, fontFamily: F.family }}>
                  No modules yet — add one below.
                </div>
              )}
              {fItems.map((item, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                  <button
                    onClick={() => setPreviewModuleId(item.module_id)}
                    title="Preview this module"
                    style={eyeBtn(previewModuleId === item.module_id)}
                  >▶</button>
                  <select
                    value={item.module_id}
                    onChange={e => updateItem(idx, { module_id: e.target.value })}
                    style={{ ...fieldStyle, flex: 1 }}
                  >
                    {modules.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                  </select>
                  <input
                    type="number" value={item.duration} min={1}
                    onChange={e => updateItem(idx, { duration: Number(e.target.value) })}
                    style={{ ...fieldStyle, width: 64 }}
                    title="Duration (s)"
                  />
                  <span style={{ color: C.textMuted, fontSize: F.size.sm }}>s</span>
                  <button onClick={() => removeItem(idx)} style={btn('danger')}>✕</button>
                </div>
              ))}
              <button onClick={addItem} disabled={!modules.length} style={{ ...btn(), marginTop: 2 }}>
                + ADD MODULE
              </button>
            </div>

            <div>
              <button
                onClick={save} disabled={!canSave}
                style={{ ...btn('success'), opacity: canSave ? 1 : 0.4, cursor: canSave ? 'pointer' : 'default' }}
              >
                {editing === 'new' ? 'CREATE PLAYLIST' : 'SAVE CHANGES'}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
