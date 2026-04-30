/**
 * Invoice card — tier badges, signals, late-payment interest, action row, and inline expand.
 */

import { useState } from "react";
import { SpectorSignalBadge } from "./SpectorSignalBadge.jsx";
import { AmlFlagBadge } from "./AmlFlagBadge.jsx";

const TIER_LABEL = {
  AUTO: "AUTO",
  ESCALATE: "ESCALATE",
  HARD_BLOCK: "HARD_BLOCK",
};

const ACTION_DESCRIPTIONS = {
  po_missing: "Request missing PO from procurement",
  po_expired: "Request renewed PO from procurement",
  po_expiring_soon: "Heads-up: PO expiring soon",
  overdue_30: "First reminder (overdue 30+ days)",
  overdue_60: "Second reminder (overdue 60+ days)",
  overdue_90_plus: "Final reminder (90+ days)",
  ready: "Upcoming-payment heads-up",
  paid_pending: "Thank-you / payment receipt",
  hold_dispute: "Follow up on disputed invoice",
  hold_payment_plan: "Payment plan check-in",
  hard_block_aml: "Hard-blocked — AML pattern signals; awaiting human review",
};

function formatGbp(amount) {
  if (amount === null || amount === undefined) return "—";
  return `£${Number(amount).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function statusBadge(invoice) {
  const status = String(invoice.status || "").toLowerCase();
  if (status === "aml_flagged") return { label: "AML FLAGGED", cls: "finoks-status--aml" };
  if (status === "paid_pending" || status === "paid_pending_confirmation")
    return { label: "PAID PENDING", cls: "finoks-status--paid" };
  if (status === "outstanding" || status === "ready")
    return { label: "READY", cls: "finoks-status--ready" };
  if (status === "overdue") return { label: "OVERDUE", cls: "finoks-status--overdue" };
  if (status === "hold") return { label: "ON HOLD", cls: "finoks-status--hold" };
  return { label: status.toUpperCase() || "—", cls: "finoks-status--neutral" };
}

function tierClass(tier, statusCls) {
  if (statusCls === "finoks-status--aml") return "finoks-tier--aml";
  if (tier === "AUTO") return "finoks-tier--auto";
  if (tier === "ESCALATE") return "finoks-tier--escalate";
  if (tier === "HARD_BLOCK") return "finoks-tier--hardblock";
  return "finoks-tier--unknown";
}

function isProcurementAction(action) {
  return typeof action === "string" && action.startsWith("po_");
}

export function InvoiceCard({
  invoice,
  onApprove,
  onBlock,
  onMarkPaid,
  onAmlOpen,
}) {
  const [expanded, setExpanded] = useState(false);
  const tier = invoice.autonomy_tier || (invoice.aml_result?.hard_block_required ? "HARD_BLOCK" : null);
  const status = statusBadge(invoice);
  const tierBadgeCls = tierClass(tier, status.cls);
  const action = invoice.action || invoice._pending_action;
  const actionDescription = ACTION_DESCRIPTIONS[action] || (action ? action.replace(/_/g, " ") : "Pending evaluation");

  const procurementBound = isProcurementAction(action);
  const recipient = procurementBound
    ? invoice.procurement_email || invoice.email
    : invoice.email || invoice.accounts_payable_email;
  const recipientLabel = procurementBound ? "Procurement" : "Accounts payable";

  const draft = invoice.draft || {};
  const verification = invoice.pre_send_verification || {};

  const interest = Number(invoice.late_payment_interest || 0);

  const showApprovalActions = invoice.awaiting_approval && tier === "ESCALATE";
  const showHardBlockActions = tier === "HARD_BLOCK" || invoice.awaiting_human_review;
  const isTerminal = ["paid", "cancelled", "written_off"].includes(
    String(invoice.status || "").toLowerCase()
  );

  let cardTone = "";
  if (status.cls === "finoks-status--aml") cardTone = "finoks-invoice--aml";
  else if (tier === "HARD_BLOCK") cardTone = "finoks-invoice--hardblock";
  else if (tier === "ESCALATE") cardTone = "finoks-invoice--escalate";
  else if (tier === "AUTO") cardTone = "finoks-invoice--auto";

  return (
    <article className={`finoks-invoice ${cardTone} ${expanded ? "is-expanded" : ""}`}>
      <button
        type="button"
        className="finoks-invoice__header"
        onClick={() => setExpanded((x) => !x)}
        aria-expanded={expanded}
      >
        <div className="finoks-invoice__title">
          <strong>{invoice.client_name || invoice.counterparty || "Counterparty"}</strong>
          <span className="finoks-invoice__amount">{formatGbp(invoice.amount ?? invoice.amount_gbp)}</span>
        </div>
        <div className="finoks-invoice__meta">
          <span>
            {invoice.invoice_number || invoice.id} · {invoice.days_overdue || 0} day(s) overdue
          </span>
          <span className={`finoks-status ${status.cls}`}>{status.label}</span>
          {tier ? (
            <span className={`finoks-tier ${tierBadgeCls}`}>
              {tierBadgeCls === "finoks-tier--aml" ? "⚠ " : ""}
              {TIER_LABEL[tier] || tier}
            </span>
          ) : null}
        </div>
      </button>

      <div className="finoks-invoice__body">
        <div className="finoks-invoice__row">
          <SpectorSignalBadge signal={invoice.specter_signal} />
          <AmlFlagBadge amlResult={invoice.aml_result} onOpen={() => onAmlOpen(invoice)} />
        </div>

        {interest > 0 ? (
          <p className="finoks-invoice__interest">
            Late payment interest: <strong>{formatGbp(interest)}</strong>{" "}
            <span className="finoks-muted">
              (UK Late Payment of Commercial Debts (Interest) Act 1998)
            </span>
          </p>
        ) : null}

        <p className="finoks-invoice__action">
          <span className="finoks-muted">Agent:</span> {actionDescription}
        </p>
        <p className="finoks-invoice__route">
          <span className="finoks-muted">Routing:</span>{" "}
          {recipient ? `${recipientLabel} — ${recipient}` : "No recipient available"}
        </p>

        <div className="finoks-invoice__actions">
          {showApprovalActions ? (
            <>
              <button
                type="button"
                className="finoks-btn finoks-btn--primary"
                onClick={() => onApprove(invoice)}
              >
                Approve & send
              </button>
              <button
                type="button"
                className="finoks-btn finoks-btn--ghost"
                onClick={() => onBlock(invoice)}
              >
                Block
              </button>
              <button
                type="button"
                className="finoks-btn finoks-btn--ghost"
                onClick={() => setExpanded(true)}
              >
                View draft
              </button>
            </>
          ) : null}

          {showHardBlockActions ? (
            <>
              <button
                type="button"
                className="finoks-btn finoks-btn--danger"
                onClick={() => onAmlOpen(invoice)}
              >
                Override after review
              </button>
              <button
                type="button"
                className="finoks-btn finoks-btn--ghost"
                onClick={() => onAmlOpen(invoice)}
              >
                View flags
              </button>
            </>
          ) : null}

          {!isTerminal ? (
            <button
              type="button"
              className="finoks-btn finoks-btn--ghost"
              onClick={() => onMarkPaid(invoice)}
            >
              Mark as paid
            </button>
          ) : null}
        </div>

        {expanded ? (
          <div className="finoks-invoice__detail">
            <div className="finoks-invoice__detail-grid">
              <section>
                <h4>Email draft</h4>
                {draft && draft.body ? (
                  <>
                    <p className="finoks-muted">
                      Subject: <strong>{draft.subject}</strong>
                    </p>
                    <pre className="finoks-draft-body">{draft.body}</pre>
                    <p className="finoks-muted">
                      Confidence score: {draft.confidence_score ?? "—"}/100
                    </p>
                  </>
                ) : (
                  <p className="finoks-muted">No draft available yet.</p>
                )}
              </section>
              <section>
                <h4>Pre-send verification</h4>
                {verification.checks ? (
                  <ul className="finoks-checks-detail">
                    {verification.checks.map((c) => (
                      <li key={c.name} className={c.passed ? "ok" : "fail"}>
                        <strong>{c.passed ? "✓" : "✗"} {c.name}</strong>
                        <span className="finoks-muted"> — {c.note}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="finoks-muted">No verification yet.</p>
                )}
                {verification.blocked_reason ? (
                  <p className="finoks-form__error">Blocked: {verification.blocked_reason}</p>
                ) : null}
              </section>
              <section>
                <h4>Recipient</h4>
                <p>
                  {recipientLabel}: <strong>{recipient || "—"}</strong>
                </p>
                {invoice.contact_name || invoice.accounts_contact_name ? (
                  <p className="finoks-muted">
                    Contact: {invoice.contact_name || invoice.accounts_contact_name}
                  </p>
                ) : null}
                <p className="finoks-muted">
                  PO: {invoice.po_number || "—"}{" "}
                  {invoice.po_status ? `(${invoice.po_status.replace(/_/g, " ")})` : ""}
                </p>
              </section>
              <section>
                <h4>Chase history</h4>
                <p>Chase count: {invoice.chase_count ?? 0}</p>
                {invoice.last_sent_action ? (
                  <p className="finoks-muted">Last action: {invoice.last_sent_action}</p>
                ) : null}
                {invoice.approved_by ? (
                  <p className="finoks-muted">Approved by: {invoice.approved_by}</p>
                ) : null}
                {invoice.aml_override ? (
                  <p className="finoks-muted">
                    AML override by {invoice.aml_override_reviewer || "reviewer"}: {" "}
                    {invoice.aml_override_note}
                  </p>
                ) : null}
              </section>
              {interest > 0 ? (
                <section>
                  <h4>Statutory interest</h4>
                  <p>
                    {formatGbp(interest)} on {formatGbp(invoice.amount ?? invoice.amount_gbp)} over{" "}
                    {invoice.days_overdue} day(s) at{" "}
                    {invoice.late_payment_rate_pct?.toFixed?.(1) ?? "13.5"}% (statutory).
                  </p>
                  <p className="finoks-muted">{invoice.late_payment_basis}</p>
                </section>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}
