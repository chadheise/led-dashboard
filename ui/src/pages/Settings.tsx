import { useEffect, useState } from "react";
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
}

export default function Settings() {
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [configs, setConfigs] = useState<Record<string, Record<string, unknown>>>({});
  const [saved, setSaved] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/apps")
      .then((r) => r.json())
      .then((all: AppInfo[]) => {
        setApps(all);
        const initial: Record<string, Record<string, unknown>> = {};
        for (const a of all) initial[a.id] = a.global_config ?? {};
        setConfigs(initial);
      });
  }, []);

  const selectedApp = apps.find((a) => a.id === selected);

  const save = async () => {
    if (!selected) return;
    await fetch(`/api/apps/${selected}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: configs[selected] ?? {} }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const goBack = () => {
    setSelected(null);
    setSaved(false);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
      <div style={pageStyle}>

        {/* ── Detail view ────────────────────────────────────────────────── */}
        {selected && selectedApp && (
          <>
            <button onClick={goBack} style={backBtnStyle}>
              <span style={{ fontSize: "1.3rem", lineHeight: 1 }}>←</span>
              <span>SETTINGS</span>
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
              <div style={{ color: C.sage }}>
                <AppIcon appId={selected} size={22} />
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
                    value={configs[selected] ?? {}}
                    onChange={(v) => setConfigs((prev) => ({ ...prev, [selected]: v }))}
                  />
                  <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 12 }}>
                    <button onClick={save} style={btn("success")}>SAVE</button>
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

        {/* ── App card grid ───────────────────────────────────────────────── */}
        {!selected && (
          <>
            <h2 style={{ ...headingStyle, marginBottom: 8 }}>SETTINGS</h2>
            <p style={{
              color: C.textMuted,
              fontSize: F.size.sm,
              fontFamily: F.family,
              marginBottom: 28,
              lineHeight: 1.6,
            }}>
              App-level configuration — API keys and defaults shared across all modules of that app type.
            </p>

            <div style={sectionLabelStyle}>APP TYPE</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
              {apps.map((app) => (
                <button
                  key={app.id}
                  type="button"
                  onClick={() => setSelected(app.id)}
                  onMouseEnter={() => setHovered(app.id)}
                  onMouseLeave={() => setHovered(null)}
                  style={appCardStyle(false, hovered === app.id)}
                >
                  <div style={{ color: C.textMuted, flexShrink: 0 }}>
                    <AppIcon appId={app.id} size={28} />
                  </div>
                  <div style={{ fontSize: F.size.md, fontFamily: F.family, color: C.textSecondary }}>
                    {app.name}
                  </div>
                  {app.description && (
                    <div style={{ fontSize: F.size.sm, color: C.textMuted, lineHeight: 1.5 }}>
                      {app.description}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </>
        )}

      </div>
    </div>
  );
}
