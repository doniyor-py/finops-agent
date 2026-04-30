/**
 * Finoks HTTP client — Bearer JWT and JSON helpers.
 *
 * All endpoints are relative to the same origin in dev (proxied by Vite),
 * or to `VITE_API_BASE` when set.
 */

const API_BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || "";

function buildUrl(path) {
  if (!path) return API_BASE;
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export function authHeaders(token, headers = {}) {
  const out = { Accept: "application/json", ...headers };
  if (token) out.Authorization = `Bearer ${token}`;
  return out;
}

async function parseResponse(resp) {
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return resp.json();
  return resp.text();
}

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function apiJson(path, init = {}) {
  const { token, headers, body, json, ...rest } = init;
  const finalHeaders = authHeaders(token, headers || {});
  let payload = body;
  if (json !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
    payload = JSON.stringify(json);
  }
  const resp = await fetch(buildUrl(path), { ...rest, headers: finalHeaders, body: payload });
  const data = await parseResponse(resp);
  if (!resp.ok) {
    const detail =
      (data && typeof data === "object" && (data.detail || data.message)) || resp.statusText;
    throw new ApiError(typeof detail === "string" ? detail : "Request failed", resp.status, data);
  }
  return data;
}

export async function apiBlob(path, init = {}) {
  const { token, headers, ...rest } = init;
  const resp = await fetch(buildUrl(path), { ...rest, headers: authHeaders(token, headers || {}) });
  if (!resp.ok) {
    const data = await parseResponse(resp);
    throw new ApiError("Request failed", resp.status, data);
  }
  return resp.blob();
}

export const Api = {
  health: () => apiJson("/health"),

  registerUser: (email, password) =>
    apiJson("/users/register", { method: "POST", json: { email, password } }),
  loginUser: (email, password) =>
    apiJson("/users/login", { method: "POST", json: { email, password } }),
  getMe: (token) => apiJson("/users/me", { token }),

  getConfig: (token) => apiJson("/agent/config", { token }),
  updateConfig: (token, partial) =>
    apiJson("/agent/config", { method: "POST", token, json: partial }),

  getStatus: (token) => apiJson("/agent/status", { token }),
  getInvoices: (token) => apiJson("/agent/invoices", { token }),
  getEvents: (token, limit = 200) => apiJson(`/agent/events?limit=${limit}`, { token }),

  loadDemo: (token) => apiJson("/agent/load-demo", { method: "POST", token }),
  resetAgent: (token) => apiJson("/agent/reset", { method: "POST", token }),
  addInvoice: (token, invoice) =>
    apiJson("/agent/add-invoice", { method: "POST", token, json: invoice }),

  csvTemplateBlob: (token) => apiBlob("/agent/csv-template", { token }),

  loadCsv: (token, file) => {
    const form = new FormData();
    form.append("file", file);
    return apiJson("/agent/load-csv", { method: "POST", token, body: form });
  },

  markPaid: (token, id) =>
    apiJson(`/agent/invoices/${encodeURIComponent(id)}/mark-paid`, { method: "POST", token }),
  approveInvoice: (token, id) =>
    apiJson(`/agent/invoices/${encodeURIComponent(id)}/approve`, { method: "POST", token }),
  blockInvoice: (token, id) =>
    apiJson(`/agent/invoices/${encodeURIComponent(id)}/block`, { method: "POST", token }),
  amlOverride: (token, id, reviewerName, reviewNote) =>
    apiJson(`/agent/invoices/${encodeURIComponent(id)}/aml-override`, {
      method: "POST",
      token,
      json: { reviewer_name: reviewerName, review_note: reviewNote },
    }),

  simulatePayment: (token) => apiJson("/agent/simulate-payment", { method: "POST", token }),
};

export function buildWsUrl(path = "/ws/agent") {
  if (API_BASE) {
    const u = new URL(API_BASE);
    u.protocol = u.protocol.replace("http", "ws");
    u.pathname = (u.pathname.replace(/\/$/, "") + path).replace(/\/+/g, "/");
    return u.toString();
  }
  if (typeof window === "undefined") return path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
