import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Api } from "../api/client.js";

export function Signup() {
  const { token, setToken } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  if (token) {
    return <Navigate to="/agent" replace />;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await Api.registerUser(email.trim().toLowerCase(), password);
      setToken(result.access_token);
      navigate("/agent", { replace: true });
    } catch (err) {
      setError(err?.message || "Sign-up failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="finoks-page">
      <header className="finoks-navbar finoks-navbar--auth">
        <Link to="/" className="finoks-brand">
          <strong>Finoks</strong>
        </Link>
      </header>
      <main className="finoks-auth">
        <div className="finoks-card">
          <h1>Create your Finoks account</h1>
          <p className="finoks-muted">Then configure your agent before it starts working.</p>
          <form className="finoks-form" onSubmit={onSubmit}>
            <label htmlFor="signup-email">Email</label>
            <input
              id="signup-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="signup-password">Password (min 8 characters)</label>
            <input
              id="signup-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error ? <p className="finoks-form__error">{error}</p> : null}
            <button type="submit" disabled={submitting}>
              {submitting ? "Creating account…" : "Create account"}
            </button>
          </form>
          <p className="finoks-muted">
            Already have an account? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
