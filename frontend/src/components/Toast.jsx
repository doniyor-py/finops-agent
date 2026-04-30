/**
 * Finoks toast notifier. Plain CSS, no third-party libraries.
 */

import { useEffect } from "react";

const ICONS = {
  success: "✓",
  info: "ℹ",
  error: "⚠",
};

export function ToastStack({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="finoks-toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }) {
  useEffect(() => {
    const ms = toast.durationMs ?? 4000;
    const timer = setTimeout(() => onDismiss(toast.id), ms);
    return () => clearTimeout(timer);
  }, [toast.id, toast.durationMs, onDismiss]);

  return (
    <div className={`finoks-toast finoks-toast--${toast.kind || "info"}`}>
      <span className="finoks-toast__icon" aria-hidden="true">
        {ICONS[toast.kind] || ICONS.info}
      </span>
      <span className="finoks-toast__msg">{toast.message}</span>
      <button
        type="button"
        className="finoks-toast__close"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}
