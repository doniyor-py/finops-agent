/**
 * Specter signal badge with full CDD + payment velocity surfacing.
 */

const RISK_CLASSES = {
  LOW: "finoks-specter--low",
  MEDIUM: "finoks-specter--medium",
  HIGH: "finoks-specter--high",
  FLAGGED: "finoks-specter--flagged",
};

const VELOCITY_LABELS = {
  IMPROVING: "Payment velocity: IMPROVING",
  STABLE: "Payment velocity: STABLE",
  DETERIORATING: "Payment velocity: DETERIORATING",
  UNKNOWN: "Payment velocity: UNKNOWN",
};

const CDD_LABELS = {
  PASSED: "CDD: PASSED",
  REQUIRES_REVIEW: "CDD: REQUIRES REVIEW",
  FAILED: "CDD: FAILED",
};

function pill(text, modifier) {
  return (
    <span className={`finoks-specter__pill ${modifier}`} title={text}>
      {text}
    </span>
  );
}

export function SpectorSignalBadge({ signal }) {
  if (!signal || signal.mock || signal.available === false) {
    const risk = signal?.risk_classification;
    return (
      <div className="finoks-specter finoks-specter--unavailable">
        <span className="finoks-specter__heading">Specter</span>
        <span className="finoks-specter__pill finoks-specter--unavailable__pill">
          {risk ? `${risk} (mock)` : "UNAVAILABLE"}
        </span>
        {signal?.cdd_status ? (
          <span className="finoks-specter__sub">
            {CDD_LABELS[signal.cdd_status] || signal.cdd_status}
          </span>
        ) : null}
      </div>
    );
  }

  const risk = String(signal.risk_classification || "MEDIUM").toUpperCase();
  const cdd = String(signal.cdd_status || "REQUIRES_REVIEW").toUpperCase();
  const velocity = String(signal.payment_velocity_trend || "UNKNOWN").toUpperCase();
  const change = signal.payment_velocity_change_pct;

  return (
    <div className={`finoks-specter ${RISK_CLASSES[risk] || ""}`}>
      <span className="finoks-specter__heading">Specter</span>
      {pill(risk, "finoks-specter__pill--risk")}
      <span className="finoks-specter__sub">{CDD_LABELS[cdd] || cdd}</span>
      <span className="finoks-specter__sub">
        {VELOCITY_LABELS[velocity] || `Payment velocity: ${velocity}`}
        {typeof change === "number" ? ` (${change > 0 ? "+" : ""}${change.toFixed(1)}%)` : ""}
      </span>
      {typeof signal.company_health_score === "number" ? (
        <span className="finoks-specter__sub">
          Health score: {Math.round(signal.company_health_score)}/100
        </span>
      ) : null}
    </div>
  );
}
