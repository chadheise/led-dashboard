import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import AppForm from "../components/AppForm";
import AppIcon from "../components/AppIcon";
import {
  C,
  F,
  appCardStyle,
  backBtnStyle,
  btn,
  headingStyle,
  pageStyle,
  sectionLabelStyle,
} from "../theme";

interface AppInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  global_config_schema: {
    type: "object";
    title?: string;
    properties: Record<string, unknown>;
  };
  global_config: Record<string, unknown>;
  libraries: string[];
}

interface LibraryInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  global_config_schema: {
    type: "object";
    title?: string;
    properties: Record<string, unknown>;
  };
  global_config: Record<string, unknown>;
}

type NavState =
  | null
  | { kind: "app"; id: string }
  | { kind: "library"; id: string; fromApp?: string };

export default function Settings() {
  const { appId, libId } = useParams<{ appId?: string; libId?: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [libraries, setLibraries] = useState<LibraryInfo[]>([]);
  const nav: NavState = appId
    ? { kind: "app", id: appId }
    : libId
      ? { kind: "library", id: libId, fromApp: (location.state as { fromApp?: string } | null)?.fromApp }
      : null;
  const [appConfigs, setAppConfigs] = useState<Record<string, Record<string, unknown>>>({});
  const [libConfigs, setLibConfigs] = useState<Record<string, Record<string, unknown>>>({});
  const [saved, setSaved] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/apps").then((r) => r.json()),
      fetch("/api/libraries").then((r) => r.json()),
    ]).then(([allApps, allLibs]: [AppInfo[], LibraryInfo[]]) => {
      setApps(allApps);
      const initApp: Record<string, Record<string, unknown>> = {};
      for (const a of allApps) initApp[a.id] = a.global_config ?? {};
      setAppConfigs(initApp);

      setLibraries(allLibs);
      const initLib: Record<string, Record<string, unknown>> = {};
      for (const l of allLibs) initLib[l.id] = l.global_config ?? {};
      setLibConfigs(initLib);
    });
  }, []);

  // Redirect to /settings if the URL points at an app/library that doesn't exist
  useEffect(() => {
    if (apps.length === 0 && libraries.length === 0) return;
    if (appId && !apps.some((a) => a.id === appId)) navigate("/settings", { replace: true });
    if (libId && !libraries.some((l) => l.id === libId)) navigate("/settings", { replace: true });
  }, [appId, libId, apps, libraries, navigate]);

  const goBack = () => {
    if (nav?.kind === "library" && nav.fromApp) {
      navigate(`/settings/app/${nav.fromApp}`);
    } else {
      navigate("/settings");
    }
    setSaved(false);
  };

  const backLabel =
    nav?.kind === "library" && nav.fromApp
      ? (apps.find((a) => a.id === nav.fromApp)?.name ?? "SETTINGS").toUpperCase()
      : "SETTINGS";

  const saveApp = async (appId: string) => {
    await fetch(`/api/apps/${appId}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: appConfigs[appId] ?? {} }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const saveLib = async (libId: string) => {
    await fetch(`/api/libraries/${libId}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: libConfigs[libId] ?? {} }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const selectedApp = nav?.kind === "app" ? apps.find((a) => a.id === nav.id) : null;
  const selectedLib = nav?.kind === "library" ? libraries.find((l) => l.id === nav.id) : null;

  const cardGrid = (items: { id: string; name: string; description: string }[], onClick: (id: string) => void) => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onClick(item.id)}
          onMouseEnter={() => setHovered(item.id)}
          onMouseLeave={() => setHovered(null)}
          style={appCardStyle(false, hovered === item.id)}
        >
          <div style={{ color: C.textMuted, flexShrink: 0 }}>
            <AppIcon appId={item.id} size={28} />
          </div>
          <div style={{ fontSize: F.size.md, fontFamily: F.family, color: C.textSecondary }}>
            {item.name}
          </div>
          {item.description && (
            <div style={{ fontSize: F.size.sm, color: C.textMuted, lineHeight: 1.5 }}>
              {item.description}
            </div>
          )}
        </button>
      ))}
    </div>
  );

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
      <div style={pageStyle}>

        {/* ── App detail ────────────────────────────────────────────────────── */}
        {nav?.kind === "app" && selectedApp && (
          <>
            <button onClick={goBack} style={backBtnStyle}>
              <span style={{ fontSize: "1.3rem", lineHeight: 1 }}>←</span>
              <span>SETTINGS</span>
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
              <div style={{ color: C.sage }}>
                <AppIcon appId={nav.id} size={22} />
              </div>
              <h2 style={{ ...headingStyle, color: C.textPrimary, fontSize: F.size.md }}>
                {selectedApp.name}
              </h2>
            </div>

            <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
              {Object.keys(selectedApp.global_config_schema?.properties ?? {}).length === 0 ? (
                <p style={{ color: C.textMuted, fontSize: F.size.sm, fontFamily: F.family, lineHeight: 1.6 }}>
                  This app has no global settings.
                </p>
              ) : (
                <>
                  <div style={sectionLabelStyle}>
                    {selectedApp.global_config_schema.title ?? "GLOBAL SETTINGS"}
                  </div>
                  <AppForm
                    schema={selectedApp.global_config_schema as Parameters<typeof AppForm>[0]["schema"]}
                    value={appConfigs[nav.id] ?? {}}
                    onChange={(v) => setAppConfigs((prev) => ({ ...prev, [nav.id]: v }))}
                  />
                  <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 12 }}>
                    <button onClick={() => saveApp(nav.id)} style={btn("success")}>SAVE</button>
                    {saved && (
                      <span style={{ color: C.positive, fontSize: F.size.sm, fontFamily: F.family }}>
                        Saved ✓
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Libraries used by this app */}
            {selectedApp.libraries.length > 0 && (
              <div style={{ marginTop: 28, borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
                <div style={sectionLabelStyle}>LIBRARIES USED</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {selectedApp.libraries.map((id) => {
                    const lib = libraries.find((l) => l.id === id);
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => { setSaved(false); navigate(`/settings/library/${id}`, { state: { fromApp: nav.id } }); }}
                        onMouseEnter={() => setHovered(id)}
                        onMouseLeave={() => setHovered(null)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "6px 12px",
                          background: hovered === id ? C.surfaceHover : C.surface,
                          border: `1px solid ${C.border}`,
                          borderRadius: 4,
                          cursor: "pointer",
                          color: C.sage,
                          fontSize: F.size.sm,
                          fontFamily: F.family,
                          transition: "background 0.15s",
                        }}
                      >
                        <AppIcon appId={id} size={14} />
                        {lib?.name ?? id}
                        <span style={{ color: C.textMuted, fontSize: "0.9em" }}>→</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}

        {/* ── Library detail ────────────────────────────────────────────────── */}
        {nav?.kind === "library" && selectedLib && (
          <>
            <button onClick={goBack} style={backBtnStyle}>
              <span style={{ fontSize: "1.3rem", lineHeight: 1 }}>←</span>
              <span>{backLabel}</span>
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
              <div style={{ color: C.sage }}>
                <AppIcon appId={nav.id} size={22} />
              </div>
              <h2 style={{ ...headingStyle, color: C.textPrimary, fontSize: F.size.md }}>
                {selectedLib.name}
              </h2>
            </div>

            <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
              {Object.keys(selectedLib.global_config_schema?.properties ?? {}).length === 0 ? (
                <p style={{ color: C.textMuted, fontSize: F.size.sm, fontFamily: F.family, lineHeight: 1.6 }}>
                  This library has no settings.
                </p>
              ) : (
                <>
                  <div style={sectionLabelStyle}>
                    {selectedLib.global_config_schema.title ?? "SETTINGS"}
                  </div>
                  <AppForm
                    schema={selectedLib.global_config_schema as Parameters<typeof AppForm>[0]["schema"]}
                    value={libConfigs[nav.id] ?? {}}
                    onChange={(v) => setLibConfigs((prev) => ({ ...prev, [nav.id]: v }))}
                  />
                  <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 12 }}>
                    <button onClick={() => saveLib(nav.id)} style={btn("success")}>SAVE</button>
                    {saved && (
                      <span style={{ color: C.positive, fontSize: F.size.sm, fontFamily: F.family }}>
                        Saved ✓
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {/* ── Main grid ─────────────────────────────────────────────────────── */}
        {nav === null && (
          <>
            <h2 style={{ ...headingStyle, marginBottom: 8 }}>SETTINGS</h2>
            <p style={{
              color: C.textMuted,
              fontSize: F.size.sm,
              fontFamily: F.family,
              marginBottom: 28,
              lineHeight: 1.6,
            }}>
              App-level configuration and shared library settings — API keys and defaults used across all modules.
            </p>

            <div style={sectionLabelStyle}>APP TYPE</div>
            {cardGrid(apps, (id) => navigate(`/settings/app/${id}`))}

            <div style={{ ...sectionLabelStyle, marginTop: 24 }}>LIBRARIES</div>
            {cardGrid(libraries, (id) => navigate(`/settings/library/${id}`))}
          </>
        )}

      </div>
    </div>
  );
}
