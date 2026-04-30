/**
 * Onboarding modal — quick autonomy setup on first /agent visit.
 */

import { useState } from "react";

const MODES = [
  { id: "guided", label: "Guided" },
  { id: "full_auto", label: "Full Auto" },
  { id: "human_all", label: "Human All" },
];

export function OnboardingModal({ open, initialConfig, onStart, onClose }) {
  const [draft, setDraft] = useState(() => ({
    mode: initialConfig?.mode || "guided",
    threshold_gbp: initialConfig?.threshold_gbp ?? 500,
    specter_enrichment: initialConfig?.specter_enrichment !== false,
    aml_checks: initialConfig?.aml_checks !== false,
  }));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  async function start() {
    setSubmitting(true);
    setError(null);
    try {
      await onStart(draft);
    } catch (err) {
      setError(err?.message || "Failed to start agent");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="finoks-modal-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="onb-title" className="finoks-modal">
        <header className="finoks-modal__header">
          <h2 id="onb-title">Welcome to Finoks</h2>
          <button type="button" className="finoks-modal__close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="finoks-modal__body">
          <p className="finoks-muted">
            Set your autonomy preferences before the agent starts. You can change them at any time
            from the navbar.
          </p>

          <label className="finoks-field">
            <span>Auto-act threshold (£)</span>
            <input
              type="range"
              min={0}
              max={5000}
              step={50}
              value={draft.threshold_gbp}
              onChange={(e) => setDraft((d) => ({ ...d, threshold_gbp: Number(e.target.value) }))}
            />
            <span className="finoks-muted">
              £{Number(draft.threshold_gbp).toLocaleString("en-GB")}
            </span>
          </label>

          <fieldset className="finoks-fieldset">
            <legend>Mode</legend>
            <div className="finoks-radios">
              {MODES.map((m) => (
                <label
                  key={m.id}
                  className={`finoks-radio ${draft.mode === m.id ? "is-active" : ""}`}
                >
                  <input
                    type="radio"
                    name="onb-mode"
                    value={m.id}
                    checked={draft.mode === m.id}
                    onChange={() => setDraft((d) => ({ ...d, mode: m.id }))}
                  />
                  <span>{m.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="finoks-toggle">
            <input
              type="checkbox"
              checked={!!draft.specter_enrichment}
              onChange={(e) =>
                setDraft((d) => ({ ...d, specter_enrichment: e.target.checked }))
              }
            />
            <span>Specter enrichment</span>
          </label>
          <label className="finoks-toggle">
            <input
              type="checkbox"
              checked={!!draft.aml_checks}
              onChange={(e) => setDraft((d) => ({ ...d, aml_checks: e.target.checked }))}
            />
            <span>AML pattern checks</span>
          </label>

          {error ? <p className="finoks-form__error">{error}</p> : null}
        </div>

        <div className="finoks-modal__actions">
          <button
            type="button"
            className="finoks-btn finoks-btn--primary"
            onClick={start}
            disabled={submitting}
          >
            {submitting ? "Starting…" : "Start Agent →"}
          </button>
        </div>
      </div>
    </div>
  );
}
