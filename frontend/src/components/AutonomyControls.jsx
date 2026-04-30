/**
 * Autonomy controls — modal settings for autonomy_config.
 */

import { useEffect, useState } from "react";

const MODES = [
  { id: "guided", label: "Guided" },
  { id: "full_auto", label: "Full Auto" },
  { id: "human_all", label: "Human All" },
];

export function AutonomyControls({ open, config, provider, onSave, onClose }) {
  const [draft, setDraft] = useState(() => ({ ...(config || {}) }));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setDraft({ ...(config || {}) });
      setError(null);
    }
  }, [open, config]);

  if (!open) return null;

  function update(field, value) {
    setDraft((cur) => ({ ...cur, [field]: value }));
  }

  async function save() {
    setSubmitting(true);
    setError(null);
    try {
      const payload = { ...draft };
      if (payload.threshold_gbp !== undefined) {
        payload.threshold_gbp = Number(payload.threshold_gbp);
      }
      await onSave(payload);
      onClose();
    } catch (err) {
      setError(err?.message || "Failed to save");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="finoks-modal-backdrop" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="autonomy-title"
        className="finoks-modal"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="finoks-modal__header">
          <h2 id="autonomy-title">Autonomy settings</h2>
          <button type="button" className="finoks-modal__close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="finoks-modal__body">
          <fieldset className="finoks-fieldset">
            <legend>Mode</legend>
            <div className="finoks-radios">
              {MODES.map((m) => (
                <label key={m.id} className={`finoks-radio ${draft.mode === m.id ? "is-active" : ""}`}>
                  <input
                    type="radio"
                    name="settings-mode"
                    value={m.id}
                    checked={draft.mode === m.id}
                    onChange={() => update("mode", m.id)}
                  />
                  <span>{m.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="finoks-field">
            <span>Auto-act threshold (GBP)</span>
            <input
              type="number"
              min={0}
              max={5000}
              step={50}
              value={draft.threshold_gbp ?? 500}
              onChange={(e) => update("threshold_gbp", Number(e.target.value))}
            />
          </label>

          <Toggle
            label="Specter enrichment"
            value={!!draft.specter_enrichment}
            onChange={(v) => update("specter_enrichment", v)}
          />
          <Toggle
            label="AML pattern checks"
            value={!!draft.aml_checks}
            onChange={(v) => update("aml_checks", v)}
          />
          <Toggle
            label="UK Late Payment Act calculations"
            value={!!draft.uk_late_payment_act}
            onChange={(v) => update("uk_late_payment_act", v)}
          />
          <Toggle
            label="Demo redirect (route outbound to test address)"
            value={!!draft.demo_redirect_enabled}
            onChange={(v) => update("demo_redirect_enabled", v)}
          />

          {draft.demo_redirect_enabled ? (
            <>
              <label className="finoks-field">
                <span>Redirect to</span>
                <input
                  type="email"
                  value={draft.redirect_to || ""}
                  onChange={(e) => update("redirect_to", e.target.value)}
                  placeholder="you@example.com"
                />
              </label>
              <label className="finoks-field">
                <span>CC</span>
                <input
                  type="email"
                  value={draft.cc || ""}
                  onChange={(e) => update("cc", e.target.value)}
                  placeholder="optional"
                />
              </label>
            </>
          ) : null}

          <section className="finoks-provider">
            <h4>Providers</h4>
            <ul className="finoks-muted">
              <li>Email provider: {provider?.email_provider || "unset"}</li>
              <li>Specter: {provider?.specter_configured ? "configured" : "mock fallback"}</li>
              <li>Anthropic: {provider?.anthropic_configured ? "configured" : "template fallback"}</li>
            </ul>
          </section>

          {error ? <p className="finoks-form__error">{error}</p> : null}
        </div>

        <div className="finoks-modal__actions">
          <button type="button" className="finoks-btn finoks-btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="finoks-btn finoks-btn--primary"
            disabled={submitting}
            onClick={save}
          >
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Toggle({ label, value, onChange }) {
  return (
    <label className="finoks-toggle">
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}
