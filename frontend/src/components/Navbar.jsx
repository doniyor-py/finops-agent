/**
 * Top navbar — brand, tick countdown, live indicator, action buttons.
 */

import { useEffect, useRef, useState } from "react";

const TICK_INTERVAL_S = 15;

function useTickCountdown(lastTickAt) {
  const [remaining, setRemaining] = useState(TICK_INTERVAL_S);
  const timerRef = useRef(null);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      if (!lastTickAt) {
        setRemaining(TICK_INTERVAL_S);
        return;
      }
      const elapsedMs = Date.now() - lastTickAt;
      const left = Math.max(0, TICK_INTERVAL_S - Math.floor(elapsedMs / 1000));
      setRemaining(left);
    }, 500);
    return () => clearInterval(timerRef.current);
  }, [lastTickAt]);

  return remaining;
}

export function Navbar({
  connected,
  lastTickAt,
  provider,
  onLoadDemo,
  onUploadCsv,
  onReset,
  onOpenSettings,
  onLogout,
  fileInputRef,
}) {
  const remaining = useTickCountdown(lastTickAt);
  const specterConfigured = !!provider?.specter_configured;
  return (
    <header className="finoks-topbar">
      <div className="finoks-topbar__brand">
        <strong>Finoks</strong>
        <span className="finoks-muted finoks-topbar__sub">
          autonomous AR · invoice chasing
        </span>
      </div>

      <div className="finoks-topbar__center">
        <span className="finoks-tick" title="Next agent tick">
          Next tick in <strong>{remaining}s</strong>
        </span>
        <span
          className={`finoks-live ${connected ? "is-live" : "is-down"}`}
          aria-label={connected ? "Live connection" : "Disconnected"}
          title={connected ? "WebSocket: live" : "WebSocket: reconnecting"}
        >
          <span className="finoks-live__dot" />
          {connected ? "Live" : "Reconnecting"}
        </span>
        {specterConfigured ? (
          <span
            className="finoks-pill finoks-pill--feature"
            title="Specter API key detected"
          >
            Specter: Live
          </span>
        ) : (
          <span
            className="finoks-pill finoks-pill--ghost"
            title="No SPECTER_API_KEY — using deterministic mock data"
          >
            Specter: Mock Mode
          </span>
        )}
      </div>

      <div className="finoks-topbar__actions">
        <button type="button" className="finoks-btn finoks-btn--primary" onClick={onLoadDemo}>
          Load demo
        </button>
        <button
          type="button"
          className="finoks-btn finoks-btn--ghost"
          onClick={() => fileInputRef.current?.click()}
        >
          Upload CSV
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUploadCsv(f);
            if (e.target) e.target.value = "";
          }}
          style={{ display: "none" }}
        />
        <button type="button" className="finoks-btn finoks-btn--ghost" onClick={onReset}>
          Reset
        </button>
        <button
          type="button"
          className="finoks-btn finoks-btn--ghost"
          onClick={onOpenSettings}
          aria-label="Open settings"
          title="Settings"
        >
          ⚙
        </button>
        <button type="button" className="finoks-btn finoks-btn--ghost" onClick={onLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}
