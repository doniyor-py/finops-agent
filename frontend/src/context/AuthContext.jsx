/**
 * Finoks authentication context — JWT persisted to localStorage.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "finoks_auth_token";
const AuthContext = createContext(null);

function readStoredToken() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw && raw.length > 0 ? raw : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [token, setTokenInternal] = useState(readStoredToken);

  useEffect(() => {
    try {
      if (token) window.localStorage.setItem(STORAGE_KEY, token);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore storage failures (e.g. private mode) */
    }
  }, [token]);

  const setToken = useCallback((next) => setTokenInternal(next || null), []);
  const logout = useCallback(() => setTokenInternal(null), []);

  const value = useMemo(() => ({ token, setToken, logout }), [token, setToken, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
