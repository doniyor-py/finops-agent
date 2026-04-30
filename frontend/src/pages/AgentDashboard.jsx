/**
 * Finoks /agent dashboard — orchestrates state, WebSocket, modals, and toasts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext.jsx";
import { Api } from "../api/client.js";
import { useAgentSocket } from "../hooks/useAgentSocket.js";

import { Navbar } from "../components/Navbar.jsx";
import { GuardrailsPanel } from "../components/GuardrailsPanel.jsx";
import { InvoiceQueue } from "../components/InvoiceQueue.jsx";
import { ActivityFeed } from "../components/ActivityFeed.jsx";
import { PipelineStatsBar } from "../components/PipelineStatsBar.jsx";
import { AmlFlagModal } from "../components/AmlFlagModal.jsx";
import { AutonomyControls } from "../components/AutonomyControls.jsx";
import { OnboardingModal } from "../components/OnboardingModal.jsx";
import { ToastStack } from "../components/Toast.jsx";

const ONBOARD_KEY = "finoks_onboarding_seen_v1";

function readOnboardingSeen() {
  try {
    return window.localStorage.getItem(ONBOARD_KEY) === "1";
  } catch {
    return true;
  }
}
function writeOnboardingSeen() {
  try {
    window.localStorage.setItem(ONBOARD_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function AgentDashboard() {
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  const [state, setState] = useState({
    invoices: [],
    events: [],
    stats: {},
    session_stats: {},
    autonomy_config: {
      mode: "guided",
      threshold_gbp: 500,
      specter_enrichment: true,
      aml_checks: true,
      uk_late_payment_act: true,
      demo_redirect_enabled: false,
      redirect_to: "",
      cc: "",
    },
    provider: {},
    running: false,
  });
  const [lastTickAt, setLastTickAt] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [amlInvoice, setAmlInvoice] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const fileInputRef = useRef(null);
  const initialFetchDone = useRef(false);

  const addToast = useCallback((message, kind = "info", durationMs) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((cur) => [...cur, { id, message, kind, durationMs }]);
  }, []);
  const removeToast = useCallback((id) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
  }, []);

  // ----- WebSocket -----
  const handleSocketMessage = useCallback((payload) => {
    if (!payload || typeof payload !== "object") return;
    if (payload.type === "INITIAL_STATE" || payload.type === "STATE_UPDATE") {
      setState((prev) => ({
        ...prev,
        invoices: Array.isArray(payload.invoices) ? payload.invoices : prev.invoices,
        events: Array.isArray(payload.events) ? payload.events : prev.events,
        stats: payload.stats || prev.stats,
        session_stats: payload.session_stats || prev.session_stats,
        autonomy_config: payload.autonomy_config || prev.autonomy_config,
        provider: payload.provider || prev.provider,
        running: payload.running ?? prev.running,
      }));
      // STATE_UPDATE arrives at end of every tick + state-change events.
      // Tick payloads carry meta.processed_this_tick from the agent summary.
      const isTick =
        payload.type === "INITIAL_STATE" ||
        payload?.meta?.processed_this_tick !== undefined;
      if (isTick) {
        setLastTickAt(Date.now());
      }
    }
  }, []);

  const { connected } = useAgentSocket(handleSocketMessage);

  // ----- Initial REST fetches (defensive, in case WS is slow) -----
  const refreshState = useCallback(async () => {
    if (!token) return;
    try {
      const [statusResp, invoicesResp, eventsResp, configResp] = await Promise.all([
        Api.getStatus(token),
        Api.getInvoices(token),
        Api.getEvents(token, 200),
        Api.getConfig(token),
      ]);
      setState((prev) => ({
        ...prev,
        stats: statusResp.stats || prev.stats,
        session_stats: statusResp.session_stats || prev.session_stats,
        autonomy_config: statusResp.autonomy_config || prev.autonomy_config,
        running: statusResp.running ?? prev.running,
        provider: statusResp.provider || configResp.provider || prev.provider,
        invoices: invoicesResp.invoices || prev.invoices,
        events: eventsResp.events || prev.events,
      }));
    } catch (err) {
      if (err?.status === 401) {
        logout();
        navigate("/login", { replace: true });
        return;
      }
      addToast(err?.message || "Failed to refresh state", "error");
    }
  }, [token, logout, navigate, addToast]);

  useEffect(() => {
    if (initialFetchDone.current) return;
    initialFetchDone.current = true;
    refreshState();
  }, [refreshState]);

  // Show onboarding once
  useEffect(() => {
    if (!readOnboardingSeen()) {
      setOnboardingOpen(true);
    }
  }, []);

  // ----- Action handlers -----
  const onUpdateConfig = useCallback(
    async (partial, message) => {
      try {
        const updated = await Api.updateConfig(token, partial);
        setState((prev) => ({ ...prev, autonomy_config: updated.autonomy_config || prev.autonomy_config }));
        addToast(message || "Settings updated", "success");
      } catch (err) {
        addToast(err?.message || "Could not update settings", "error");
      }
    },
    [token, addToast]
  );

  const onLoadDemo = useCallback(async () => {
    try {
      const result = await Api.loadDemo(token);
      addToast(`Demo loaded — ${result.loaded} invoices`, "success");
      // Trigger a refresh so non-WS state propagates immediately.
      refreshState();
    } catch (err) {
      addToast(err?.message || "Failed to load demo", "error");
    }
  }, [token, addToast, refreshState]);

  const onReset = useCallback(async () => {
    if (!window.confirm("Reset all agent state and session counters?")) return;
    try {
      await Api.resetAgent(token);
      addToast("Agent state reset", "success");
      refreshState();
    } catch (err) {
      addToast(err?.message || "Reset failed", "error");
    }
  }, [token, addToast, refreshState]);

  const onUploadCsv = useCallback(
    async (file) => {
      try {
        const result = await Api.loadCsv(token, file);
        addToast(
          `CSV loaded — ${result.loaded} invoice(s); ${result.errors?.length || 0} error(s).`,
          (result.errors?.length || 0) > 0 ? "info" : "success"
        );
        refreshState();
      } catch (err) {
        addToast(err?.message || "CSV upload failed", "error");
      }
    },
    [token, addToast, refreshState]
  );

  const onApprove = useCallback(
    async (invoice) => {
      try {
        await Api.approveInvoice(token, invoice.invoice_id || invoice.id);
        addToast(`Approved — ${invoice.client_name || invoice.counterparty}`, "success");
      } catch (err) {
        addToast(err?.message || "Approve failed", "error");
      }
    },
    [token, addToast]
  );

  const onBlock = useCallback(
    async (invoice) => {
      try {
        await Api.blockInvoice(token, invoice.invoice_id || invoice.id);
        addToast(`Blocked — ${invoice.client_name || invoice.counterparty}`, "success");
      } catch (err) {
        addToast(err?.message || "Block failed", "error");
      }
    },
    [token, addToast]
  );

  const onMarkPaid = useCallback(
    async (invoice) => {
      try {
        await Api.markPaid(token, invoice.invoice_id || invoice.id);
        addToast(`Marked paid (pending confirmation) — ${invoice.client_name || invoice.counterparty}`, "success");
      } catch (err) {
        addToast(err?.message || "Mark-paid failed", "error");
      }
    },
    [token, addToast]
  );

  const onAmlOpen = useCallback((invoice) => {
    setAmlInvoice(invoice);
  }, []);

  const onAmlClose = useCallback(() => setAmlInvoice(null), []);

  const onAmlOverride = useCallback(
    async (reviewerName, reviewNote) => {
      if (!amlInvoice) return;
      const id = amlInvoice.invoice_id || amlInvoice.id;
      const res = await Api.amlOverride(token, id, reviewerName, reviewNote);
      addToast(`AML override recorded for ${amlInvoice.client_name || amlInvoice.counterparty}`, "success");
      return res;
    },
    [amlInvoice, token, addToast]
  );

  const startAgentFromOnboarding = useCallback(
    async (draft) => {
      await onUpdateConfig(draft, "Configuration saved");
      writeOnboardingSeen();
      setOnboardingOpen(false);
    },
    [onUpdateConfig]
  );

  const onLogout = useCallback(() => {
    logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  // Keep amlInvoice in sync when state updates from server.
  useEffect(() => {
    if (!amlInvoice) return;
    const refreshed = state.invoices.find(
      (i) => (i.invoice_id || i.id) === (amlInvoice.invoice_id || amlInvoice.id)
    );
    if (refreshed && refreshed !== amlInvoice) setAmlInvoice(refreshed);
  }, [state.invoices, amlInvoice]);

  const guardrailsConfig = state.autonomy_config;
  const sessionStats = state.session_stats;

  // Memoise queue invoices to avoid re-render churn
  const queueInvoices = useMemo(() => state.invoices, [state.invoices]);

  return (
    <div className="finoks-agent">
      <Navbar
        connected={connected}
        lastTickAt={lastTickAt}
        provider={state.provider}
        onLoadDemo={onLoadDemo}
        onUploadCsv={onUploadCsv}
        onReset={onReset}
        onOpenSettings={() => setSettingsOpen(true)}
        onLogout={onLogout}
        fileInputRef={fileInputRef}
      />

      <main className="finoks-agent__grid">
        <GuardrailsPanel
          config={guardrailsConfig}
          sessionStats={sessionStats}
          onUpdateConfig={onUpdateConfig}
        />

        <section className="finoks-agent__queue">
          <InvoiceQueue
            invoices={queueInvoices}
            onApprove={onApprove}
            onBlock={onBlock}
            onMarkPaid={onMarkPaid}
            onAmlOpen={onAmlOpen}
          />
        </section>

        <ActivityFeed events={state.events} />
      </main>

      <PipelineStatsBar stats={state.stats} sessionStats={sessionStats} />

      {amlInvoice ? (
        <AmlFlagModal
          invoice={amlInvoice}
          onClose={onAmlClose}
          onOverride={onAmlOverride}
        />
      ) : null}

      <AutonomyControls
        open={settingsOpen}
        config={guardrailsConfig}
        provider={state.provider}
        onSave={(payload) => onUpdateConfig(payload, "Settings saved")}
        onClose={() => setSettingsOpen(false)}
      />

      <OnboardingModal
        open={onboardingOpen}
        initialConfig={guardrailsConfig}
        onStart={startAgentFromOnboarding}
        onClose={() => {
          writeOnboardingSeen();
          setOnboardingOpen(false);
        }}
      />

      <ToastStack toasts={toasts} onDismiss={removeToast} />
    </div>
  );
}
