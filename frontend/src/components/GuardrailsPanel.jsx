/**
 * Guardrails panel — autonomy mode, threshold, what the agent will / won't do, session counters.
 */

import { useEffect, useRef, useState } from "react";

const MODES = [
  { id: "guided", label: "Guided" },
  { id: "full_auto", label: "Full Auto" },
  { id: "human_all", label: "Human All" },
];

function formatGbp(v) {
  return `£${(Number(v) || 0).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}

export function GuardrailsPanel({ config, sessionStats, onUpdateConfig }) {
  const [pendingThreshold, setPendingThreshold] = useState(null);
  const debounceRef = useRef(null);

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    []
  );

  const threshold = pendingThreshold ?? Number(config?.threshold_gbp ?? 500);
  const mode = config?.mode || "guided";

  function commitThreshold(value) {
    setPendingThreshold(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onUpdateConfig({ threshold_gbp: value }, `Auto-act threshold set to ${formatGbp(value)}`);
      setPendingThreshold(null);
    }, 500);
  }

  function chooseMode(next) {
    if (next === mode) return;
    onUpdateConfig({ mode: next }, `Autonomy mode set to ${next}`);
  }

  const stats = sessionStats || {};

  return (
    <aside className="finoks-guardrails" aria-label="Agent guardrails">
      <section className="finoks-guardrails__section">
        <h3>Autonomy mode</h3>
        <div className="finoks-radios">
          {MODES.map((m) => (
            <label key={m.id} className={`finoks-radio ${mode === m.id ? "is-active" : ""}`}>
              <input
                type="radio"
                name="autonomy-mode"
                value={m.id}
                checked={mode === m.id}
                onChange={() => chooseMode(m.id)}
              />
              <span>{m.label}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="finoks-guardrails__section">
        <h3>Auto-act threshold</h3>
        <div className="finoks-threshold">
          <input
            type="range"
            min={0}
            max={5000}
            step={50}
            value={threshold}
            onChange={(e) => commitThreshold(Number(e.target.value))}
          />
          <input
            type="number"
            min={0}
            max={5000}
            step={50}
            value={threshold}
            onChange={(e) => commitThreshold(Number(e.target.value))}
          />
          <span className="finoks-muted">{formatGbp(threshold)}</span>
        </div>
      </section>

      <section className="finoks-guardrails__section">
        <h3>Will act alone on</h3>
        <ul className="finoks-checks finoks-checks--ok">
          <li>First chase under {formatGbp(threshold)}</li>
          <li>PO reminders (procurement routed)</li>
          <li>Thank-you confirmations</li>
        </ul>
      </section>

      <section className="finoks-guardrails__section">
        <h3>Will pause for you</h3>
        <ul className="finoks-checks finoks-checks--warn">
          <li>Invoices over {formatGbp(threshold)}</li>
          <li>Mixed or HIGH Specter signal</li>
          <li>3rd+ chase attempt</li>
          <li>New client over £8,000</li>
        </ul>
      </section>

      <section className="finoks-guardrails__section">
        <h3>Will never do</h3>
        <ul className="finoks-checks finoks-checks--forbid">
          <li>Act on AML-flagged invoices</li>
          <li>Email FLAGGED counterparties</li>
          <li>Override AML blocks automatically</li>
          <li>Act on invoices over £5,000 with FAILED CDD</li>
        </ul>
      </section>

      <section className="finoks-guardrails__section">
        <h3>AML framework</h3>
        <p className="finoks-muted finoks-framework-line">
          POCA 2002 · MLR 2017 · FCA FCG · NCA Typologies
        </p>
      </section>

      <section className="finoks-guardrails__section">
        <h3>This session</h3>
        <dl className="finoks-counters">
          <div>
            <dt>Autonomous actions</dt>
            <dd>{stats.auto_actioned ?? 0}</dd>
          </div>
          <div>
            <dt>Escalated to you</dt>
            <dd>{stats.escalated ?? 0}</dd>
          </div>
          <div>
            <dt>Hard blocked</dt>
            <dd>{stats.hard_blocked ?? 0}</dd>
          </div>
          <div>
            <dt>AML flags raised</dt>
            <dd>{stats.aml_flags_raised ?? 0}</dd>
          </div>
          <div>
            <dt>SAR considerations</dt>
            <dd>{stats.sar_considerations ?? 0}</dd>
          </div>
          <div>
            <dt>Late fees identified</dt>
            <dd>{formatGbp(stats.late_payment_interest_identified ?? 0)}</dd>
          </div>
        </dl>
      </section>
    </aside>
  );
}
