import { useCallback, useEffect, useState } from "react";
import { C, F } from "../theme";

// Minimal, dependency-free toast. Each page owns its own toast state via
// useToast() and renders a single <Toast/>; styling reuses the shared theme
// tokens (positive/negative/neutral) so it matches the rest of the UI.

export type ToastKind = "success" | "error" | "info";

export interface ToastState {
  id: number;
  kind: ToastKind;
  message: string;
}

const BORDER: Record<ToastKind, string> = {
  success: C.positive,
  error: C.negative,
  info: C.neutral,
};

let _nextId = 0;

export function useToast() {
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, kind: ToastKind = "info") => {
    setToast({ id: ++_nextId, kind, message });
  }, []);
  const dismiss = useCallback(() => setToast(null), []);
  return { toast, showToast, dismiss };
}

export default function Toast({
  toast,
  onDismiss,
  duration = 3000,
}: {
  toast: ToastState | null;
  onDismiss: () => void;
  duration?: number;
}) {
  // Re-arms whenever a new toast appears (id changes).
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, duration);
    return () => clearTimeout(t);
  }, [toast, onDismiss, duration]);

  if (!toast) return null;
  return (
    <div
      role="status"
      onClick={onDismiss}
      style={{
        position: "fixed",
        bottom: 20,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 1000,
        background: C.surface,
        border: `1px solid ${BORDER[toast.kind]}`,
        color: C.textPrimary,
        padding: "10px 18px",
        borderRadius: 4,
        fontFamily: F.family,
        fontSize: F.size.sm,
        letterSpacing: F.tracking.normal,
        boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
        maxWidth: "90vw",
        cursor: "pointer",
      }}
    >
      {toast.message}
    </div>
  );
}
