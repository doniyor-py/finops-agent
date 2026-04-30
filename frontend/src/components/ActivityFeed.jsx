/**
 * Activity feed — keeps the last 200 events, auto-scrolls to bottom on new entries.
 */

import { useEffect, useMemo, useRef, useState } from "react";

const EVENT_STYLES = {
  SPECTER_ENRICHED: { cls: "ev--blue", icon: "🔍" },
  AML_FLAG_RAISED: { cls: "ev--red", icon: "⚠" },
  SAR_CONSIDERATION_TRIGGERED: { cls: "ev--darkred", icon: "🚨" },
  AML_OVERRIDE: { cls: "ev--purple", icon: "👤" },
  OBSERVED: { cls: "ev--grey", icon: "👁" },
  DECIDED: { cls: "ev--blue", icon: "🧠" },
  DRAFTED: { cls: "ev--indigo", icon: "✍" },
  VERIFIED: { cls: "ev--green", icon: "✓" },
  AWAITING_APPROVAL: { cls: "ev--amber", icon: "⏳" },
  APPROVED_BY_USER: { cls: "ev--green", icon: "👤" },
  BLOCKED_BY_USER: { cls: "ev--grey", icon: "🚫" },
  HARD_BLOCKED: { cls: "ev--red", icon: "🛑" },
  SENT: { cls: "ev--green", icon: "📧" },
  BLOCKED: { cls: "ev--orange", icon: "⛔" },
  PAYMENT_RECEIVED: { cls: "ev--green", icon: "💰" },
  CONFIG_UPDATED: { cls: "ev--grey", icon: "⚙" },
  TICK_START: { cls: "ev--grey", icon: "›" },
  TICK_END: { cls: "ev--grey", icon: "‹" },
  SYSTEM: { cls: "ev--grey", icon: "⚙" },
  ERROR: { cls: "ev--orange", icon: "⛔" },
};

const MAX_FEED = 200;

function fmtTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function describe(event) {
  const counterparty = event.counterparty || event.client_name || "";
  switch (event.type) {
    case "SPECTER_ENRICHED":
      return `${event.status_label || "Specter signal"} for ${counterparty || event.invoice_id}`;
    case "AML_FLAG_RAISED":
      return `${counterparty || event.invoice_id} — ${event.flag_count} flag(s), severity ${event.highest_severity}`;
    case "SAR_CONSIDERATION_TRIGGERED":
      return `${counterparty || event.invoice_id} — consider SAR obligation under POCA 2002 s.330`;
    case "AML_OVERRIDE":
      return `Override by ${event.reviewer_name || event.reviewer_user || "reviewer"} on ${counterparty || event.invoice_id}`;
    case "OBSERVED":
      return `${counterparty || event.invoice_id} — observed (${event.days_overdue || 0} day(s) overdue)`;
    case "DECIDED":
      return `${counterparty || event.invoice_id} — ${event.action} (${event.autonomy_tier})`;
    case "AWAITING_APPROVAL":
      return `${counterparty || event.invoice_id} — awaiting human approval (${event.action})`;
    case "APPROVED_BY_USER":
      return `${counterparty || event.invoice_id} — approved by ${event.approver}`;
    case "BLOCKED_BY_USER":
      return `${counterparty || event.invoice_id} — blocked by ${event.blocker}`;
    case "HARD_BLOCKED":
      return `${counterparty || event.invoice_id} — hard-blocked: ${event.reason || ""}`;
    case "SENT":
      return `${counterparty || event.invoice_id} — sent ${event.action} to ${event.to || ""}`;
    case "BLOCKED":
      return `${counterparty || event.invoice_id} — pre-send verification blocked: ${event.reason || ""}`;
    case "CONFIG_UPDATED":
      return `Operator updated config: ${Object.keys(event.changes || {}).join(", ") || "—"}`;
    case "TICK_START":
      return `Tick start (${event.invoice_count || 0} invoices)`;
    case "TICK_END":
      return `Tick end (processed ${event.processed || 0})`;
    case "SYSTEM":
      return event.message || "System event";
    case "ERROR":
      return event.error || "Error";
    default:
      return event.message || event.type;
  }
}

export function ActivityFeed({ events }) {
  const [openId, setOpenId] = useState(null);
  const listRef = useRef(null);
  const stickyRef = useRef(true);

  const trimmed = useMemo(() => {
    const list = events || [];
    return list.slice(-MAX_FEED);
  }, [events]);

  useEffect(() => {
    if (!listRef.current) return;
    if (stickyRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [trimmed.length]);

  function onScroll() {
    const el = listRef.current;
    if (!el) return;
    const slack = 24;
    stickyRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < slack;
  }

  return (
    <aside className="finoks-feed" aria-label="Activity feed">
      <header className="finoks-feed__header">
        <h2>Activity</h2>
        <span className="finoks-muted">{trimmed.length} of last {MAX_FEED}</span>
      </header>
      <ul className="finoks-feed__list" ref={listRef} onScroll={onScroll}>
        {trimmed.map((evt, idx) => {
          const style = EVENT_STYLES[evt.type] || { cls: "ev--grey", icon: "•" };
          const id = `${evt.ts || idx}-${evt.type}-${evt.invoice_id || idx}`;
          const isOpen = openId === id;
          return (
            <li key={id} className={`finoks-feed__item ${style.cls}`}>
              <button
                type="button"
                className="finoks-feed__row"
                onClick={() => setOpenId(isOpen ? null : id)}
                aria-expanded={isOpen}
              >
                <span className="finoks-feed__time">{fmtTime(evt.ts)}</span>
                <span className="finoks-feed__icon" aria-hidden="true">
                  {style.icon}
                </span>
                <span className="finoks-feed__type">{evt.type}</span>
                <span className="finoks-feed__desc">{describe(evt)}</span>
              </button>
              {isOpen ? (
                <pre className="finoks-feed__detail">
                  {JSON.stringify(evt, null, 2)}
                </pre>
              ) : null}
            </li>
          );
        })}
        {trimmed.length === 0 ? (
          <li className="finoks-muted finoks-feed__empty">No events yet.</li>
        ) : null}
      </ul>
    </aside>
  );
}
