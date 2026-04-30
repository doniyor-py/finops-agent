import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Api } from "../api/client.js";

export function Login() {
  const { token, setToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? "/agent";

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
      const result = await Api.loginUser(email.trim().toLowerCase(), password);
      setToken(result.access_token);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err?.message || "Login failed");
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
          <h1>Sign in</h1>
          <p className="finoks-muted">Continue to the autonomous agent dashboard.</p>
          <form className="finoks-form" onSubmit={onSubmit}>
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error ? <p className="finoks-form__error">{error}</p> : null}
            <button type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="finoks-muted">
            No account? <Link to="/signup">Create one</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
