import { useEffect, useRef, useState } from "react";
import AppIcon from "./AppIcon";
import { C, F, fieldStyle } from "../theme";

interface ModuleOption {
  id: string;
  name: string;
  app_id: string;
}

interface AppInfo {
  id: string;
  name: string;
  icon: string;
}

interface Props {
  value: string;
  options: ModuleOption[];
  apps?: AppInfo[];
  onChange: (id: string) => void;
}

export default function ModuleSelect({ value, options, apps, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.id === value);

  const groups = apps
    ? apps
        .map((app) => ({ app, items: options.filter((o) => o.app_id === app.id) }))
        .filter((g) => g.items.length > 0)
    : null;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", flex: 1 }}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          ...fieldStyle,
          display: "flex",
          alignItems: "center",
          gap: 8,
          cursor: "pointer",
          textAlign: "left",
          width: "100%",
        }}
      >
        <span style={{ color: C.textMuted, flexShrink: 0, display: "flex" }}>
          <AppIcon icon={apps?.find(a => a.id === selected?.app_id)?.icon ?? ''} size={15} />
        </span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selected?.name ?? "—"}
        </span>
        <span style={{ color: C.textDim, fontSize: "0.7rem", flexShrink: 0 }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {/* Dropdown */}
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 100,
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: 3,
            marginTop: 2,
            maxHeight: 220,
            overflowY: "auto",
          }}
        >
          {(groups ?? [{ app: null, items: options }]).map(({ app, items }) => (
            <div key={app?.id ?? "__all"}>
              {app && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "5px 10px 3px",
                    color: C.textDim,
                    fontFamily: F.family,
                    fontSize: F.size.xs,
                    letterSpacing: "0.08em",
                    borderTop: `1px solid ${C.border}`,
                    marginTop: 2,
                  }}
                >
                  <AppIcon icon={app.icon} size={11} />
                  {app.name.toUpperCase()}
                </div>
              )}
              {items.map((opt) => {
                const isSelected = opt.id === value;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => { onChange(opt.id); setOpen(false); }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      width: "100%",
                      padding: "7px 10px",
                      background: isSelected ? C.surfaceHover : "none",
                      border: "none",
                      cursor: "pointer",
                      textAlign: "left",
                      color: isSelected ? C.textPrimary : C.textSecondary,
                      fontFamily: F.family,
                      fontSize: F.size.base,
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) (e.currentTarget as HTMLButtonElement).style.background = C.surfaceHover;
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) (e.currentTarget as HTMLButtonElement).style.background = "none";
                    }}
                  >
                    {opt.name}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
