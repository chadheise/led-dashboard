import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppForm from "../components/AppForm";
import AppIcon, { PencilIcon, TrashIcon } from "../components/AppIcon";
import DisplayPreview from "../components/DisplayPreview";
import MultiSizePreview from "../components/MultiSizePreview";
import TransportControls from "../components/TransportControls";
import Toast, { useToast } from "../components/Toast";
import { apiFetch, apiJson, jsonBody } from "../api";
import {
  C,
  F,
  appCardStyle,
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

interface Module {
  id: string;
  name: string;
  app_id: string;
  config: Record<string, unknown>;
}

interface Schema {
  type: "object";
  properties: Record<
    string,
    {
      type: string;
      title?: string;
      default?: unknown;
      enum?: string[];
      minimum?: number;
      maximum?: number;
      items?: { type: string; enum?: string[] };
      properties?: Record<string, { type: string; default?: unknown }>;
      "x-input-type"?: string;
      "x-default-from-library"?: { library: string; path: string };
    }
  >;
  required?: string[];
}

interface AppInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  schema: Schema;
}

// ── Local layout styles (not visual, no theming needed) ───────────────────────

const hdr: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 20,
};
const row: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
};
const btnRow: React.CSSProperties = { display: "flex", gap: 6, flexShrink: 0 };
const iconBtn = (variant: Parameters<typeof btn>[0]): React.CSSProperties => ({
  ...btn(variant),
  display: "flex",
  alignItems: "center",
  gap: 5,
  padding: "5px 10px",
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function defaultsFromSchema(schema: Schema): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[k] = prop.default;
  }
  return out;
}

function configSummary(config: Record<string, unknown>): string {
  const parts = Object.entries(config)
    .slice(0, 3)
    .map(
      ([k, v]) =>
        `${k}: ${Array.isArray(v) ? (v as unknown[]).join(", ") : String(v)}`,
    );
  return parts.join(" · ") || "(no config)";
}

function stopPreview() {
  fetch("/api/preview", { method: "DELETE" }).catch(() => {});
}

// ── App card grid ─────────────────────────────────────────────────────────────

function AppCardGrid({
  apps,
  selected,
  onSelect,
}: {
  apps: AppInfo[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  return (
    <div>
      <div style={sectionLabelStyle}>APP TYPE</div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 8,
        }}
      >
        {apps.map((app) => {
          const sel = app.id === selected;
          const hov = hovered === app.id && !sel;
          return (
            <button
              key={app.id}
              type="button"
              onClick={() => onSelect(app.id)}
              onMouseEnter={() => setHovered(app.id)}
              onMouseLeave={() => setHovered(null)}
              style={appCardStyle(sel, hov)}
            >
              <div style={{ color: sel ? C.sage : C.textMuted, flexShrink: 0 }}>
                <AppIcon icon={app.icon} size={28} />
              </div>
              <div
                style={{
                  fontSize: F.size.md,
                  fontFamily: F.family,
                  color: sel ? C.sage : C.textSecondary,
                }}
              >
                {app.name}
              </div>
              {app.description && (
                <div
                  style={{
                    fontSize: F.size.sm,
                    color: sel ? C.textSecondary : C.textMuted,
                    lineHeight: 1.5,
                  }}
                >
                  {app.description}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Modules() {
  const { id: routeId } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const editing = routeId ?? null;
  const [modules, setModules] = useState<Module[]>([]);
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [step, setStep] = useState<1 | 2>(1);
  const [fName, setFName] = useState("");
  const [fAppId, setFAppId] = useState("");
  const [fConfig, setFConfig] = useState<Record<string, unknown>>({});
  const [showSizePreviews, setShowSizePreviews] = useState(import.meta.env.DEV);
  const [paused, setPaused] = useState(false);
  const [editPaused, setEditPaused] = useState(false);
  const [origName, setOrigName] = useState("");
  const [origAppId, setOrigAppId] = useState("");
  const [origConfig, setOrigConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const { toast, showToast, dismiss } = useToast();

  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    Promise.all([
      apiJson<Module[]>("/api/modules"),
      apiJson<AppInfo[]>("/api/apps"),
    ])
      .then(([m, a]) => {
        setModules(m);
        setApps(a);
      })
      .catch(() => showToast("Could not reach the engine", "error"));
    apiJson<{ paused?: boolean }>("/api/status")
      .then((s) => {
        if (typeof s.paused === "boolean") setPaused(s.paused);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!editing) stopPreview();
  }, [editing]);
  useEffect(
    () => () => {
      stopPreview();
    },
    [],
  );

  useEffect(() => {
    if (!editing || !fAppId) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => {
      fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: fAppId, config: fConfig }),
      });
    }, 300);
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, [editing, fAppId, fConfig]);

  // ── Transport ──────────────────────────────────────────────────────────────
  const prev = () =>
    fetch("/api/playlist/prev", { method: "POST" }).then(() => setPaused(false));
  const next = () =>
    fetch("/api/playlist/next", { method: "POST" }).then(() => setPaused(false));
  const togglePlayPause = () =>
    fetch("/api/playlist/playpause", { method: "POST" })
      .then((r) => r.json())
      .then((d) => setPaused(d.paused));

  // When editing, play/pause freezes the edit preview, not the live display
  const toggleEditPlayPause = () =>
    fetch("/api/preview/playpause", { method: "POST" })
      .then((r) => r.json())
      .then((d) => setEditPaused(d.paused));

  // Reset edit-preview paused state when editing opens or closes
  useEffect(() => { setEditPaused(false); }, [editing]);

  // Hide sizes strip when leaving edit mode
  useEffect(() => { if (!editing) setShowSizePreviews(false); }, [editing]);

  // ── Navigation ─────────────────────────────────────────────────────────────
  // Sync form state from the URL — covers clicks (openNew/openEdit navigate)
  // as well as direct loads/back-forward navigation to /modules/new or /modules/:id
  const syncedEditing = useRef<string | null>(null);
  useEffect(() => {
    if (editing === syncedEditing.current) return;
    if (editing === "new") {
      setFName("");
      setFAppId("");
      setFConfig({});
      setStep(1);
      syncedEditing.current = "new";
    } else if (editing) {
      const m = modules.find((mod) => mod.id === editing);
      if (!m) {
        if (modules.length > 0) navigate("/modules", { replace: true });
        return;
      }
      setFName(m.name);
      setFAppId(m.app_id);
      setFConfig(m.config);
      setOrigName(m.name);
      setOrigAppId(m.app_id);
      setOrigConfig(m.config);
      setStep(2);
      syncedEditing.current = editing;
    } else {
      syncedEditing.current = null;
    }
  }, [editing, modules, navigate]);

  const openNew = () => navigate("/modules/new");
  const openEdit = (m: Module) => navigate(`/modules/${m.id}`);
  const goBack = () => {
    if (editing === "new" && step === 2) setStep(1);
    else navigate("/modules");
  };

  const handleAppSelect = async (id: string) => {
    if (id !== fAppId) {
      setFAppId(id);
      const schema = apps.find((a) => a.id === id)?.schema;
      if (schema) {
        const defaults = defaultsFromSchema(schema);
        const overrides: Record<string, unknown> = {};
        for (const [key, prop] of Object.entries(schema.properties ?? {})) {
          const libDefault = prop["x-default-from-library"];
          if (libDefault) {
            try {
              const libConfig: Record<string, unknown> = await fetch(
                `/api/libraries/${libDefault.library}/config`
              ).then((r) => r.json());
              const libValue = libConfig[libDefault.path];
              if (libValue !== undefined && typeof libValue === "object") {
                overrides[key] = {
                  ...(defaults[key] as Record<string, unknown> | undefined ?? {}),
                  ...(libValue as Record<string, unknown>),
                };
              }
            } catch {}
          }
        }
        setFConfig({ ...defaults, ...overrides });
      }
    }
    setStep(2);
  };

  // ── CRUD ───────────────────────────────────────────────────────────────────
  const save = async () => {
    const body = { name: fName, app_id: fAppId, config: fConfig };
    setSaving(true);
    try {
      if (editing === "new") {
        const m = await apiJson<Module>("/api/modules", jsonBody("POST", body));
        setModules((prev) => [...prev, m]);
      } else {
        await apiFetch(`/api/modules/${editing}`, jsonBody("PUT", body));
        setModules((prev) =>
          prev.map((m) => (m.id === editing ? { ...m, ...body } : m)),
        );
      }
      showToast("Saved", "success");
      navigate("/modules");
    } catch {
      showToast("Save failed — please retry", "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await apiFetch(`/api/modules/${id}`, { method: "DELETE" });
      setModules((prev) => prev.filter((m) => m.id !== id));
      if (editing === id) navigate("/modules");
    } catch {
      showToast("Delete failed — please retry", "error");
    }
  };

  // ── Derived ────────────────────────────────────────────────────────────────
  const moduleGroups = apps
    .map((app) => ({ app, items: modules.filter((m) => m.app_id === app.id) }))
    .filter((g) => g.items.length > 0);

  const currentSchema = apps.find((a) => a.id === fAppId)?.schema;
  const selectedApp = apps.find((a) => a.id === fAppId);
  const isEditing = editing !== null;
  const showEditPreview = isEditing && fAppId !== "";

  let pLabel = "LIVE DISPLAY";
  if (editing === "new" && step === 1 && fAppId)
    pLabel = `APP PREVIEW · ${selectedApp?.name ?? ""}`;
  else if (editing === "new" && step === 2) pLabel = "NEW MODULE PREVIEW";
  else if (editing && editing !== "new") pLabel = `MODULE PREVIEW · ${fName}`;

  const backLabel = editing === "new" && step === 2 ? "SELECT APP" : "MODULES";

  const hasChanges =
    editing === "new"
      ? fName.trim() !== ""
      : fName.trim() !== "" &&
        (fName !== origName ||
          fAppId !== origAppId ||
          JSON.stringify(fConfig) !== JSON.stringify(origConfig));
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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={previewLabelStyle}>{pLabel}</span>
          {import.meta.env.DEV && (
            <button
              onClick={() => setShowSizePreviews((p) => !p)}
              style={{
                ...btn(showSizePreviews ? "active" : "eye"),
                padding: "2px 8px",
                fontSize: F.size.xs,
              }}
            >
              SIZES
            </button>
          )}
        </div>
        <DisplayPreview
          wsUrl={showEditPreview ? "/ws/preview/edit" : "/ws/preview"}
          scale={3}
          actions={
            <TransportControls
              paused={isEditing ? editPaused : paused}
              onPrev={prev}
              onPlayPause={isEditing ? toggleEditPlayPause : togglePlayPause}
              onNext={next}
              showPrev={!isEditing}
              showNext={!isEditing}
            />
          }
        />
      </div>

      {import.meta.env.DEV && showSizePreviews && (
        <div
          style={{
            background: C.bg,
            borderBottom: `1px solid ${C.border}`,
            padding: "12px 16px",
            overflowX: "auto",
          }}
        >
          {showEditPreview
            ? <MultiSizePreview appId={fAppId} config={fConfig} />
            : <MultiSizePreview live />
          }
        </div>
      )}

      {/* Scrollable content — preview above stays fixed */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <div style={pageStyle}>
          {isEditing && (
            <button onClick={goBack} style={backBtnStyle}>
              <span style={{ fontSize: "1.3rem", lineHeight: 1 }}>←</span>
              <span>{backLabel}</span>
            </button>
          )}

          {/* "New [App] Module" header — step 2 of new module flow */}
          {editing === "new" && step === 2 && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 20,
              }}
            >
              <div style={{ color: C.sage }}>
                <AppIcon icon={apps.find(a => a.id === fAppId)?.icon ?? ''} size={22} />
              </div>
              <h2
                style={{
                  ...headingStyle,
                  color: C.textPrimary,
                  fontSize: F.size.md,
                }}
              >
                New {selectedApp?.name} Module
              </h2>
            </div>
          )}

          {/* Module list */}
          {!isEditing && (
            <>
              <div style={hdr}>
                <h2 style={headingStyle}>MODULES</h2>
                <button onClick={openNew} style={btn("primary")}>
                  + NEW MODULE
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
                A configuration for a specific app that can be re-used when
                creating playlists.
              </p>
              {moduleGroups.map(({ app, items }) => (
                <div key={app.id} style={{ marginBottom: 24 }}>
                  <div
                    style={{
                      ...sectionLabelStyle,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <AppIcon icon={app.icon} size={14} />
                    {app.name.toUpperCase()}
                  </div>
                  {items.map((m) => (
                    <div key={m.id} style={cardStyle()}>
                      <div style={row}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 14,
                            minWidth: 0,
                            flex: 1,
                          }}
                        >
                          <div style={{ minWidth: 0 }}>
                            <div
                              style={{
                                color: C.textPrimary,
                                marginBottom: 3,
                                fontFamily: F.family,
                              }}
                            >
                              {m.name}
                            </div>
                            <div
                              style={{
                                color: C.textMuted,
                                fontSize: F.size.sm,
                                fontFamily: F.family,
                              }}
                            >
                              {configSummary(m.config)}
                            </div>
                          </div>
                        </div>
                        <div style={btnRow}>
                          <button
                            onClick={() => openEdit(m)}
                            style={iconBtn("ghost")}
                            title="Edit"
                          >
                            <PencilIcon />
                          </button>
                          <button
                            onClick={() => remove(m.id)}
                            style={iconBtn("danger")}
                            title="Delete"
                          >
                            <TrashIcon />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </>
          )}

          {/* Step 1: app type selection */}
          {isEditing && editing === "new" && step === 1 && (
            <AppCardGrid
              apps={apps}
              selected={fAppId}
              onSelect={handleAppSelect}
            />
          )}

          {/* Step 2 / edit existing: name first, then config */}
          {isEditing && (editing !== "new" || step === 2) && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <label style={labelStyle}>
                Module name
                <input
                  type="text"
                  value={fName}
                  onChange={(e) => setFName(e.target.value)}
                  placeholder={`e.g. ${selectedApp?.name ?? "My module"}`}
                  style={fieldStyle}
                />
              </label>

              {currentSchema && (
                <div
                  style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16 }}
                >
                  <AppForm
                    schema={currentSchema}
                    value={fConfig}
                    onChange={setFConfig}
                  />
                </div>
              )}

              <div>
                <button
                  onClick={save}
                  disabled={!canSave || saving}
                  style={{
                    ...btn("success"),
                    opacity: canSave && !saving ? 1 : 0.4,
                    cursor: canSave && !saving ? "pointer" : "default",
                  }}
                >
                  {saving
                    ? "SAVING…"
                    : editing === "new"
                      ? "CREATE MODULE"
                      : "SAVE"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <Toast toast={toast} onDismiss={dismiss} />
    </div>
  );
}
