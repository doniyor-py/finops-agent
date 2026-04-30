/**
 * Bottom stats bar — high-level pipeline summary.
 */

function gbp(value) {
  if (value === null || value === undefined) return "£0";
  return `£${Number(value).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}

export function PipelineStatsBar({ stats, sessionStats }) {
  const s = stats || {};
  const ss = sessionStats || {};
  return (
    <footer className="finoks-stats" aria-label="Pipeline stats">
      <Stat label="Total AR" value={gbp(s.portfolio_total_gbp)} />
      <Stat
        label="At risk"
        value={gbp((s.autonomy_distribution?.ESCALATE || 0) + (s.autonomy_distribution?.HARD_BLOCK || 0) > 0
          ? s.portfolio_total_gbp || 0
          : 0)}
        tone="warn"
      />
      <Stat label="Auto-actioned" value={ss.auto_actioned ?? 0} tone="ok" />
      <Stat label="Escalated" value={ss.escalated ?? 0} tone="warn" />
      <Stat label="Hard blocked" value={ss.hard_blocked ?? 0} tone="danger" />
      <Stat label="AML flags" value={ss.aml_flags_raised ?? 0} tone="danger" />
      <Stat label="Late fees ID'd" value={gbp(ss.late_payment_interest_identified)} tone="info" />
    </footer>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className={`finoks-stat finoks-stat--${tone || "neutral"}`}>
      <span className="finoks-stat__label">{label}</span>
      <span className="finoks-stat__value">{value}</span>
    </div>
  );
}
