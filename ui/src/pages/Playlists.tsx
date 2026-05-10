import { useEffect, useState } from "react";
import AppIcon, { PencilIcon, TrashIcon } from "../components/AppIcon";
import ModuleSelect from "../components/ModuleSelect";
import DisplayPreview from "../components/DisplayPreview";
import TransportControls from "../components/TransportControls";
import {
  C,
  F,
  backBtnStyle,
  btn,
  cardStyle,
  fieldStyle,
  headingStyle,
  labelStyle,
  pageStyle,
  previewLabelStyle,
  previewPaneStyle,
  sectionLabelStyle,
} from "../theme";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlaylistItem {
  module_id: string;
  module_name: string;
  app_id: string | null;
  duration: number;
}
interface Playlist {
  id: string;
  name: string;
  items: PlaylistItem[];
  is_active: boolean;
}
interface Module {
  id: string;
  name: string;
  app_id: string;
  config: Record<string, unknown>;
}
interface AppInfo {
  id: string;
  name: string;
}
interface EditItem {
  module_id: string;
  duration: number;
}

// ── Local layout styles ───────────────────────────────────────────────────────

const hdr: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 12,
};
const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
};

function eyeBtn(active: boolean): React.CSSProperties {
  return {
    ...btn("eye"),
    padding: "5px 8px",
    color: active ? C.positive : (btn("eye").color as string),
    borderColor: active ? C.positive : (btn("eye").borderColor as string),
  };
}

function iconBtn(variant: Parameters<typeof btn>[0]): React.CSSProperties {
  return {
    ...btn(variant),
    display: "flex",
    alignItems: "center",
    gap: 5,
    padding: "5px 10px",
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function stopPreview() {
  fetch("/api/preview", { method: "DELETE" }).catch(() => {});
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Playlists() {
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [activeSingleModuleId, setActiveSingleModuleId] = useState<string | null>(null);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [editPaused, setEditPaused] = useState(false);
  const [fName, setFName] = useState("");
  const [fItems, setFItems] = useState<EditItem[]>([]);
  const [previewModuleId, setPreviewModuleId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [showNoModulesWarning, setShowNoModulesWarning] = useState(false);
  const [origName, setOrigName] = useState("");
  const [origItems, setOrigItems] = useState<EditItem[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);

  useEffect(() => {
    refresh();
    fetch("/api/modules")
      .then((r) => r.json())
      .then((mods) => setModules(mods));
    fetch("/api/apps")
      .then((r) => r.json())
      .then(setApps);
    fetch("/api/status")
      .then((r) => r.json())
      .then((s) => {
        if (typeof s.paused === "boolean") setPaused(s.paused);
        if (s.active_single_module_id) {
          setActiveSingleModuleId(s.active_single_module_id);
          setSelectedModuleId(s.active_single_module_id);
          setPlaylists((prev) => prev.map((p) => ({ ...p, is_active: false })));
        }
      });
  }, []);

  // Dismiss no-modules warning automatically when modules appear
  useEffect(() => {
    if (modules.length > 0) setShowNoModulesWarning(false);
  }, [modules.length]);

  // Default selected module to the first one once modules load
  useEffect(() => {
    if (modules.length > 0) setSelectedModuleId((prev) => prev ?? modules[0].id);
  }, [modules]);

  useEffect(() => {
    if (!editing) stopPreview();
  }, [editing]);
  useEffect(
    () => () => {
      stopPreview();
    },
    [],
  );

  const resolvedPreviewId = previewModuleId ?? fItems[0]?.module_id ?? null;
  useEffect(() => {
    if (!editing || !resolvedPreviewId) return;
    const mod = modules.find((m) => m.id === resolvedPreviewId);
    if (!mod) return;
    fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: mod.app_id, config: mod.config }),
    }).catch(() => {});
  }, [editing, resolvedPreviewId]);

  const refresh = () =>
    fetch("/api/playlists")
      .then((r) => r.json())
      .then(setPlaylists);

  // ── Navigation ─────────────────────────────────────────────────────────────
  const openNew = () => {
    if (modules.length === 0) {
      setShowNoModulesWarning(true);
      return;
    }
    setFName("");
    setFItems([]);
    setPreviewModuleId(null);
    setEditing("new");
  };
  const openEdit = (pl: Playlist) => {
    const items = pl.items.map((it) => ({
      module_id: it.module_id,
      duration: it.duration,
    }));
    setFName(pl.name);
    setFItems(items);
    setOrigName(pl.name);
    setOrigItems(items);
    setPreviewModuleId(null);
    setConfirmDeleteId(null);
    setEditing(pl.id);
  };
  const goBack = () => {
    setConfirmDeleteId(null);
    setEditing(null);
  };

  // ── CRUD ───────────────────────────────────────────────────────────────────
  const save = async () => {
    const body = { name: fName, items: fItems };
    if (editing === "new") {
      await fetch("/api/playlists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } else {
      await fetch(`/api/playlists/${editing}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }
    setEditing(null);
    refresh();
  };

  const remove = async (id: string) => {
    await fetch(`/api/playlists/${id}`, { method: "DELETE" });
    setPlaylists((prev) => prev.filter((p) => p.id !== id));
    setConfirmDeleteId(null);
    if (editing === id) setEditing(null);
  };

  const activate = async (id: string) => {
    await fetch(`/api/playlists/${id}/activate`, { method: "POST" });
    setActiveSingleModuleId(null); // clears active indicator; selectedModuleId is preserved
    setPlaylists((prev) => prev.map((p) => ({ ...p, is_active: p.id === id })));
  };

  // ── Transport ──────────────────────────────────────────────────────────────
  const prev = () =>
    fetch("/api/playlist/prev", { method: "POST" }).then(() => setPaused(false));
  const next = () =>
    fetch("/api/playlist/next", { method: "POST" }).then(() => setPaused(false));
  const togglePlayPause = () =>
    fetch("/api/playlist/playpause", { method: "POST" })
      .then((r) => r.json())
      .then((d) => setPaused(d.paused));

  // When editing, play/pause freezes the edit preview, not the live display.
  const toggleEditPlayPause = () =>
    fetch("/api/preview/playpause", { method: "POST" })
      .then((r) => r.json())
      .then((d) => setEditPaused(d.paused));

  // Reset edit-preview paused state whenever editing opens or closes.
  useEffect(() => { setEditPaused(false); }, [editing]);

  // ── Playlist form helpers ──────────────────────────────────────────────────
  const addItem = () => {
    if (modules.length)
      setFItems((prev) => [
        ...prev,
        { module_id: modules[0].id, duration: 30 },
      ]);
  };
  const updateItem = (idx: number, patch: Partial<EditItem>) =>
    setFItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)),
    );
  const removeItem = (idx: number) => {
    if (previewModuleId === fItems[idx]?.module_id) setPreviewModuleId(null);
    setFItems((prev) => prev.filter((_, i) => i !== idx));
  };
  const moduleName = (id: string) =>
    modules.find((m) => m.id === id)?.name ?? id;
  const moduleAppId = (id: string) =>
    modules.find((m) => m.id === id)?.app_id ?? "";

  const onDragStart = (idx: number) => setDragIdx(idx);
  const onDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setDragOver(idx);
  };
  const onDrop = (idx: number) => {
    if (dragIdx !== null && dragIdx !== idx) {
      setFItems((prev) => {
        const items = [...prev];
        const [moved] = items.splice(dragIdx, 1);
        items.splice(idx, 0, moved);
        return items;
      });
    }
    setDragIdx(null);
    setDragOver(null);
  };
  const onDragEnd = () => {
    setDragIdx(null);
    setDragOver(null);
  };

  // ── Single-module quick-play ───────────────────────────────────────────────
  const activateSingleModuleById = async (id: string) => {
    const res = await fetch(`/api/play/module/${id}`, { method: "POST" });
    if (res.ok) {
      setActiveSingleModuleId(id);
      setPlaylists((prev) => prev.map((p) => ({ ...p, is_active: false })));
    }
  };

  const activateSingleModule = () => {
    if (selectedModuleId) activateSingleModuleById(selectedModuleId);
  };

  // ── Derived ────────────────────────────────────────────────────────────────
  const isEditing = editing !== null;
  const activeSingleModule = activeSingleModuleId
    ? modules.find((m) => m.id === activeSingleModuleId) ?? null
    : null;
  const activePlaylist = activeSingleModuleId
    ? null
    : playlists.find((p) => p.is_active) ?? null;
  const previewWsUrl = isEditing ? "/ws/preview/edit" : "/ws/preview";

  let pLabel = "LIVE DISPLAY";
  if (editing === "new")
    pLabel = resolvedPreviewId
      ? `NEW PLAYLIST · ${moduleName(resolvedPreviewId)}`
      : "NEW PLAYLIST";
  else if (editing)
    pLabel = resolvedPreviewId
      ? `EDITING · ${moduleName(resolvedPreviewId)}`
      : `EDITING · ${fName || "…"}`;

  const hasChanges =
    editing === "new"
      ? fName.trim() !== ""
      : fName.trim() !== "" &&
        (fName !== origName ||
          JSON.stringify(fItems) !== JSON.stringify(origItems));
  const canSave = hasChanges;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
      }}
    >
      <div style={previewPaneStyle}>
        <span style={previewLabelStyle}>{pLabel}</span>
        <DisplayPreview
          wsUrl={previewWsUrl}
          scale={3}
          actions={
            <TransportControls
              paused={isEditing ? editPaused : paused}
              onPrev={prev}
              onPlayPause={isEditing ? toggleEditPlayPause : togglePlayPause}
              onNext={next}
            />
          }
        />
      </div>

      {/* Scrollable content — preview above stays fixed */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <div style={pageStyle}>
          {isEditing && (
            <button onClick={goBack} style={backBtnStyle}>
              <span style={{ fontSize: "1.3rem", lineHeight: 1 }}>←</span>
              <span>PLAYLISTS</span>
            </button>
          )}

          {/* ── Playlist list ─────────────────────────────────────────────── */}
          {!isEditing && (
            <>
              <div style={hdr}>
                <h2 style={headingStyle}>PLAYLISTS</h2>
                <button onClick={openNew} style={btn("primary")}>
                  + NEW PLAYLIST
                </button>
              </div>

              <p
                style={{
                  color: C.textMuted,
                  fontSize: F.size.sm,
                  fontFamily: F.family,
                  marginBottom: 20,
                  lineHeight: 1.6,
                }}
              >
                A sequence of modules that will be displayed in order.
              </p>

              {/* No-modules warning */}
              {showNoModulesWarning && (
                <div
                  style={{
                    border: `1px solid ${C.neutral}`,
                    background: "rgba(200,168,78,0.08)",
                    borderRadius: 4,
                    padding: "14px 16px",
                    marginBottom: 20,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <p
                    style={{
                      color: C.textSecondary,
                      fontSize: F.size.sm,
                      fontFamily: F.family,
                      lineHeight: 1.5,
                    }}
                  >
                    Before creating a playlist, you must configure one or more
                    modules.
                  </p>
                  <button
                    onClick={() => setShowNoModulesWarning(false)}
                    style={{ ...btn(), flexShrink: 0 }}
                  >
                    DISMISS
                  </button>
                </div>
              )}

              {/* Featured active item (playlist or single module) */}
              {(activePlaylist || activeSingleModule) && (
                <div style={{ marginBottom: 28 }}>
                  <div style={sectionLabelStyle}>ACTIVE</div>
                  <div
                    style={{
                      ...cardStyle(true),
                      border: `1px solid ${C.positive}`,
                      padding: "18px 20px",
                    }}
                  >
                    {activeSingleModule ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ color: C.positive, fontSize: F.size.md }}>◉</span>
                        <div style={{ color: C.textMuted, flexShrink: 0 }}>
                          <AppIcon appId={activeSingleModule.app_id} size={14} />
                        </div>
                        <span style={{ color: C.textPrimary, fontFamily: F.family, fontSize: F.size.md }}>
                          {activeSingleModule.name}
                        </span>
                        <span style={{ fontSize: F.size.xs, color: C.positive, letterSpacing: F.tracking.wider, fontFamily: F.family }}>
                          SINGLE MODULE
                        </span>
                      </div>
                    ) : activePlaylist ? (
                      <>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            marginBottom: activePlaylist.items.length > 0 ? 12 : 0,
                          }}
                        >
                          <span style={{ color: C.positive, fontSize: F.size.md }}>◉</span>
                          <span style={{ color: C.textPrimary, fontFamily: F.family, fontSize: F.size.md }}>
                            {activePlaylist.name}
                          </span>
                        </div>
                        {activePlaylist.items.length > 0 ? (
                          <ol style={{ margin: "4px 0 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 6, fontFamily: F.family }}>
                            {activePlaylist.items.map((it, i) => (
                              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <div style={{ color: C.textMuted, flexShrink: 0 }}>
                                  <AppIcon appId={it.app_id ?? ""} size={14} />
                                </div>
                                <span style={{ color: C.textSecondary, fontSize: F.size.base }}>{it.module_name}</span>
                                <span style={{ color: C.textMuted, fontSize: F.size.sm }}>· {it.duration}s</span>
                              </div>
                            ))}
                          </ol>
                        ) : (
                          <div style={{ color: C.textDim, fontSize: F.size.sm, fontFamily: F.family }}>Empty playlist</div>
                        )}
                      </>
                    ) : null}
                  </div>
                </div>
              )}

              {/* Single module quick-play */}
              <div style={{ marginBottom: 28 }}>
                <div style={sectionLabelStyle}>SINGLE MODULE</div>
                <div
                  style={{ ...cardStyle(!!activeSingleModuleId), cursor: "pointer" }}
                  onClick={activateSingleModule}
                >
                  <div onClick={(e) => e.stopPropagation()}>
                    <ModuleSelect
                      value={selectedModuleId ?? ""}
                      options={modules}
                      apps={apps}
                      onChange={(id) => {
                        setSelectedModuleId(id);
                        if (activeSingleModuleId) activateSingleModuleById(id);
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Full playlist list */}
              <div style={sectionLabelStyle}>ALL PLAYLISTS</div>
              {playlists.map((pl) => {
                const isConfirming = confirmDeleteId === pl.id;
                return (
                  <div
                    key={pl.id}
                    style={{
                      ...cardStyle(pl.is_active),
                      cursor: pl.is_active ? "default" : "pointer",
                    }}
                    onClick={
                      !pl.is_active && !isConfirming
                        ? () => activate(pl.id)
                        : undefined
                    }
                  >
                    <div style={rowStyle}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                        }}
                      >
                        <span
                          style={{
                            color: pl.is_active ? C.positive : C.textMuted,
                            fontSize: F.size.md,
                          }}
                        >
                          {pl.is_active ? "◉" : "○"}
                        </span>
                        <span
                          style={{ color: C.textPrimary, fontFamily: F.family }}
                        >
                          {pl.name}
                        </span>
                        {pl.is_active && (
                          <span
                            style={{
                              fontSize: F.size.xs,
                              color: C.positive,
                              letterSpacing: F.tracking.wider,
                              fontFamily: F.family,
                            }}
                          >
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openEdit(pl);
                          }}
                          style={iconBtn("ghost")}
                          title="Edit"
                        >
                          <PencilIcon />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(pl.id);
                          }}
                          style={iconBtn("danger")}
                          title="Delete"
                        >
                          <TrashIcon />
                        </button>
                      </div>
                    </div>

                    {/* Inline delete confirmation */}
                    {isConfirming && (
                      <div
                        style={{
                          marginTop: 12,
                          paddingTop: 12,
                          borderTop: `1px solid ${C.border}`,
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          style={{
                            color: C.negative,
                            fontSize: F.size.sm,
                            fontFamily: F.family,
                            flex: 1,
                          }}
                        >
                          Delete "{pl.name}"? This cannot be undone.
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(null);
                          }}
                          style={btn()}
                        >
                          CANCEL
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            remove(pl.id);
                          }}
                          style={btn("danger")}
                        >
                          DELETE
                        </button>
                      </div>
                    )}

                    {!isConfirming && pl.items.length > 0 && (
                      <ol
                        style={{
                          margin: "8px 0 0 0",
                          padding: 0,
                          display: "flex",
                          flexDirection: "column",
                          gap: 5,
                          fontFamily: F.family,
                        }}
                      >
                        {pl.items.map((it, i) => (
                          <div
                            key={i}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                            }}
                          >
                            <div style={{ color: C.textMuted, flexShrink: 0 }}>
                              <AppIcon appId={it.app_id ?? ""} size={13} />
                            </div>
                            <span
                              style={{
                                color: C.textSecondary,
                                fontSize: F.size.sm,
                              }}
                            >
                              {it.module_name}
                            </span>
                            <span
                              style={{
                                color: C.textMuted,
                                fontSize: F.size.xs,
                              }}
                            >
                              · {it.duration}s
                            </span>
                          </div>
                        ))}
                      </ol>
                    )}
                    {!isConfirming && pl.items.length === 0 && (
                      <div
                        style={{
                          marginTop: 8,
                          color: C.textDim,
                          fontSize: F.size.sm,
                          fontFamily: F.family,
                        }}
                      >
                        Empty playlist
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          )}

          {/* ── New / edit playlist form ───────────────────────────────────── */}
          {isEditing && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <label style={labelStyle}>
                Playlist name
                <input
                  type="text"
                  value={fName}
                  onChange={(e) => setFName(e.target.value)}
                  style={fieldStyle}
                  placeholder="e.g. Daily Rotation"
                />
              </label>

              <div>
                <div style={sectionLabelStyle}>MODULES IN PLAYLIST</div>
                {fItems.length === 0 && (
                  <div
                    style={{
                      color: C.textDim,
                      fontSize: F.size.sm,
                      marginBottom: 8,
                      fontFamily: F.family,
                    }}
                  >
                    No modules yet — add one below.
                  </div>
                )}
                {fItems.map((item, idx) => (
                  <div
                    key={idx}
                    draggable
                    onDragStart={() => onDragStart(idx)}
                    onDragOver={(e) => onDragOver(e, idx)}
                    onDrop={() => onDrop(idx)}
                    onDragEnd={onDragEnd}
                    style={{
                      display: "flex",
                      gap: 8,
                      alignItems: "center",
                      marginBottom: 6,
                      opacity: dragIdx === idx ? 0.4 : 1,
                      borderTop: dragOver === idx && dragIdx !== null && dragIdx > idx
                        ? `2px solid ${C.sage}`
                        : "2px solid transparent",
                      borderBottom: dragOver === idx && dragIdx !== null && dragIdx < idx
                        ? `2px solid ${C.sage}`
                        : "2px solid transparent",
                    }}
                  >
                    {/* Drag handle */}
                    <span
                      title="Drag to reorder"
                      style={{
                        cursor: "grab",
                        color: C.textDim,
                        fontSize: "1rem",
                        lineHeight: 1,
                        userSelect: "none",
                        flexShrink: 0,
                      }}
                    >
                      ⠿
                    </span>
                    <button
                      onClick={() => setPreviewModuleId(item.module_id)}
                      title="Preview this module"
                      style={eyeBtn(previewModuleId === item.module_id)}
                    >
                      ▶
                    </button>
                    <ModuleSelect
                      value={item.module_id}
                      options={modules}
                      apps={apps}
                      onChange={(id) => updateItem(idx, { module_id: id })}
                    />
                    <input
                      type="number"
                      value={item.duration}
                      min={1}
                      onChange={(e) =>
                        updateItem(idx, { duration: Number(e.target.value) })
                      }
                      style={{ ...fieldStyle, width: 64 }}
                      title="Duration (s)"
                    />
                    <span style={{ color: C.textMuted, fontSize: F.size.sm }}>
                      s
                    </span>
                    <button
                      onClick={() => removeItem(idx)}
                      style={iconBtn("danger")}
                      title="Remove"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                ))}
                <button
                  onClick={addItem}
                  disabled={!modules.length}
                  style={{ ...btn(), marginTop: 2 }}
                >
                  + ADD MODULE
                </button>
              </div>

              {/* Save + delete actions */}
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <button
                  onClick={save}
                  disabled={!canSave}
                  style={{
                    ...btn("success"),
                    opacity: canSave ? 1 : 0.4,
                    cursor: canSave ? "pointer" : "default",
                  }}
                >
                  {editing === "new" ? "CREATE PLAYLIST" : "SAVE"}
                </button>
                {editing !== "new" && confirmDeleteId !== editing && (
                  <button
                    onClick={() => setConfirmDeleteId(editing)}
                    style={{ ...iconBtn("danger"), marginLeft: "auto" }}
                    title="DELETE"
                  >
                    <TrashIcon /> DELETE
                  </button>
                )}
              </div>

              {/* Delete confirmation in form */}
              {editing !== "new" && confirmDeleteId === editing && (
                <div
                  style={{
                    border: `1px solid ${C.negative}`,
                    background: "rgba(184,92,92,0.08)",
                    borderRadius: 4,
                    padding: "14px 16px",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      color: C.negative,
                      fontSize: F.size.sm,
                      fontFamily: F.family,
                      flex: 1,
                    }}
                  >
                    Delete "{fName}"? This cannot be undone.
                  </span>
                  <button
                    onClick={() => setConfirmDeleteId(null)}
                    style={btn()}
                  >
                    CANCEL
                  </button>
                  <button onClick={() => remove(editing)} style={btn("danger")}>
                    DELETE
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
