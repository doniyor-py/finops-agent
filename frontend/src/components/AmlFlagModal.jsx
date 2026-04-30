/**
 * AML flag detail modal — surfaces hedged framework references and override path.
 */

import { useEffect, useRef, useState } from "react";

const SEVERITY_COLOURS = {
  LOW: "finoks-sev--low",
  MEDIUM: "finoks-sev--medium",
  HIGH: "finoks-sev--high",
  CRITICAL: "finoks-sev--critical",
};

export function AmlFlagModal({ invoice, onClose, onOverride }) {
  const [reviewerName, setReviewerName] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const dialogRef = useRef(null);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!invoice) return null;
  const aml = invoice.aml_result || {};
  const flags = aml.flags || [];
  const showSar = !!aml.sar_consideration;
  const isHardBlocked =
    invoice.autonomy_tier === "HARD_BLOCK" ||
    invoice.awaiting_human_review ||
    aml.hard_block_required;

  const trimmedName = reviewerName.trim();
  const trimmedNote = reviewNote.trim();
  const canOverride = trimmedName.length >= 2 && trimmedNote.length >= 4;

  async function submitOverride() {
    if (!canOverride) {
      setError(
        "Reviewer name (≥ 2 characters) and a review note (≥ 4 characters) are required."
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onOverride(trimmedName, trimmedNote);
      onClose();
    } catch (err) {
      setError(err?.message || "Override failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="finoks-modal-backdrop" onMouseDown={onClose} role="presentation">
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="aml-modal-title"
        className="finoks-modal"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="finoks-modal__header">
          <h2 id="aml-modal-title">AML pattern flags — {invoice.client_name || invoice.counterparty}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="finoks-modal__close">
            ×
          </button>
        </header>

        <div className="finoks-modal__body">
          {showSar ? (
            <div className="finoks-sar-banner">
              Consider SAR obligation under POCA 2002 s.330 — this does not mean laundering has occurred. Human
              review required.
            </div>
          ) : null}

          {flags.length === 0 ? (
            <p className="finoks-muted">No pattern flags raised for this invoice.</p>
          ) : (
            <ul className="finoks-flags">
              {flags.map((flag, idx) => (
                <li key={`${flag.check_name || "flag"}-${idx}`} className="finoks-flag">
                  <div className="finoks-flag__row">
                    <span
                      className={`finoks-sev ${SEVERITY_COLOURS[flag.severity] || ""}`}
                      title={flag.severity}
                    >
                      {flag.severity}
                    </span>
                    <strong className="finoks-flag__name">{flag.check_name}</strong>
                    {flag.portfolio_level ? (
                      <span className="finoks-pill finoks-pill--ghost">portfolio</span>
                    ) : null}
                  </div>
                  <p className="finoks-flag__desc">{flag.description}</p>
                  <p className="finoks-flag__ref">{flag.framework_ref}</p>
                </li>
              ))}
            </ul>
          )}

          {aml.human_review_note ? (
            <div className="finoks-review-note">
              <strong>Human review note:</strong>
              <p>{aml.human_review_note}</p>
            </div>
          ) : null}

          {(aml.framework_references || []).length > 0 ? (
            <p className="finoks-muted finoks-frameworks">
              {aml.framework_references.join(" · ")}
            </p>
          ) : null}
        </div>

        {isHardBlocked ? (
          <div className="finoks-modal__override">
            <h3>Override after review</h3>
            <p className="finoks-muted">
              Required by Finoks: a named human reviewer and a written rationale create the audit trail.
            </p>
            <label htmlFor="aml-reviewer">Reviewer name</label>
            <input
              id="aml-reviewer"
              type="text"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              placeholder="e.g. Alex Compliance"
            />
            <label htmlFor="aml-note">Review note</label>
            <textarea
              id="aml-note"
              rows={3}
              value={reviewNote}
              onChange={(e) => setReviewNote(e.target.value)}
              placeholder="What was reviewed, what was found, why it is now safe to proceed."
            />
            {error ? <p className="finoks-form__error">{error}</p> : null}
            <div className="finoks-modal__actions">
              <button type="button" className="finoks-btn finoks-btn--ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="finoks-btn finoks-btn--danger"
                disabled={submitting || !canOverride}
                onClick={submitOverride}
                title={
                  canOverride
                    ? "Record reviewer override"
                    : "Reviewer name and review note required"
                }
              >
                {submitting ? "Submitting…" : "Override after review"}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
