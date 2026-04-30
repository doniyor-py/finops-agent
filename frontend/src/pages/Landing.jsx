import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

const FEATURE_PILLS = [
  "Three-tier autonomy",
  "Specter CDD enrichment",
  "POCA 2002 / MLR 2017 pattern detection",
  "UK Late Payment Act",
  "Real-time WebSocket feed",
];

export function Landing() {
  const { token } = useAuth();
  return (
    <div className="finoks-page finoks-page--landing">
      <header className="finoks-navbar--auth">
        <Link to="/" className="finoks-brand">
          <strong>Finoks</strong>
        </Link>
        <nav className="finoks-navbar__nav">
          {token ? (
            <Link to="/agent" className="finoks-btn finoks-btn--primary">
              Open dashboard
            </Link>
          ) : (
            <>
              <Link to="/login" className="finoks-btn finoks-btn--ghost">
                Sign in
              </Link>
              <Link to="/signup" className="finoks-btn finoks-btn--primary">
                Get started
              </Link>
            </>
          )}
        </nav>
      </header>

      <main className="finoks-landing">
        <section className="finoks-landing__hero">
          <span className="finoks-landing__eyebrow">Autonomous AR · UK</span>
          <h1>
            Your AR runs itself.
            <br />
            <span className="finoks-landing__hl">Your guardrails decide how far.</span>
          </h1>
          <p className="finoks-landing__lead">
            Finoks is an autonomous invoice agent with UK AML pattern detection, Specter
            counterparty intelligence, and configurable human-in-the-loop thresholds.
          </p>
          <div className="finoks-landing__cta">
            <Link className="finoks-btn finoks-btn--primary" to="/signup">
              Get Started →
            </Link>
            <Link className="finoks-btn finoks-btn--ghost" to="/login">
              Sign in
            </Link>
          </div>
          <ul className="finoks-pills" aria-label="Capabilities">
            {FEATURE_PILLS.map((pill) => (
              <li key={pill} className="finoks-pill finoks-pill--feature">
                {pill}
              </li>
            ))}
          </ul>
        </section>

        <aside className="finoks-landing__panel" aria-hidden="true">
          <div className="finoks-landing__panel-row">
            <span className="finoks-tier finoks-tier--auto">AUTO</span>
            <span className="finoks-muted">First chase under threshold</span>
          </div>
          <div className="finoks-landing__panel-row">
            <span className="finoks-tier finoks-tier--escalate">ESCALATE</span>
            <span className="finoks-muted">Mixed Specter signal · awaiting approval</span>
          </div>
          <div className="finoks-landing__panel-row">
            <span className="finoks-tier finoks-tier--hardblock">HARD_BLOCK</span>
            <span className="finoks-muted">AML pattern flags · review required</span>
          </div>
          <div className="finoks-landing__panel-row">
            <span className="finoks-pill finoks-pill--aml">SAR consideration</span>
            <span className="finoks-muted">POCA 2002 s.330 · human in loop</span>
          </div>
        </aside>
      </main>
    </div>
  );
}
