"""
Finoks — autonomous AR / invoice chasing agent.

Three-tier autonomy is enforced **every tick**:

- **AUTO**: ≤ ``threshold_gbp`` AND clean Specter / AML signal → agent may send (subject to pre-send verification).
- **ESCALATE**: > threshold OR mixed signal → queue for human approval; **no auto send**.
- **HARD_BLOCK**: AML hard-block flags, Specter ``cdd_status == FAILED``, or ``> £5000 + Specter FLAGGED`` →
  **no email**, no draft sent; only a human action via ``POST /agent/invoices/{id}/approve`` (after review)
  can move the invoice forward.

This module also surfaces `Pattern consistent with MLR 2017 / NCA typologies — human review required.`
for AML hard blocks and uses the `Consider SAR obligation under POCA 2002 s.330` framing for
``sar_consideration``. It never asserts laundering or filing status.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from aml_detector import run_aml_checks
from specter_client import enrich_counterparty, specter_status_label

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Global runtime state — single-process by design (no shared multi-worker state).
# -----------------------------------------------------------------------------

agent_invoices: List[Dict[str, Any]] = []
agent_events: List[Dict[str, Any]] = []
agent_running: bool = False
agent_session_stats: Dict[str, Any] = {
    "total_ticks": 0,
    "emails_sent": 0,
    "auto_actioned": 0,
    "escalated": 0,
    "hard_blocked": 0,
    "aml_flags_raised": 0,
    "sar_considerations": 0,
    "recovered_value": 0.0,
    "late_payment_interest_identified": 0.0,
}

autonomy_config: Dict[str, Any] = {
    "mode": "guided",  # "guided" | "full_auto" | "human_all"
    "threshold_gbp": 500.0,
    "specter_enrichment": True,
    "aml_checks": True,
    "uk_late_payment_act": True,
    "demo_redirect_enabled": False,
    "redirect_to": "",
    "cc": "",
}


# -----------------------------------------------------------------------------
# WebSocket broadcaster registration (main.py wires the actual sender).
# -----------------------------------------------------------------------------

_broadcaster: Optional[Any] = None


def register_broadcaster(broadcaster: Any) -> None:
    """Wire a broadcaster ``async def broadcaster(payload: dict) -> None``."""

    global _broadcaster
    _broadcaster = broadcaster


async def _safe_broadcast(payload: Dict[str, Any]) -> None:
    if _broadcaster is None:
        return
    try:
        await _broadcaster(payload)
    except Exception:  # broadcasting must never crash the tick
        logger.exception("Broadcast failure suppressed")


# -----------------------------------------------------------------------------
# Public types
# -----------------------------------------------------------------------------


class AutonomyTier(str, Enum):
    AUTO = "AUTO"
    ESCALATE = "ESCALATE"
    HARD_BLOCK = "HARD_BLOCK"


_TERMINAL_STATUSES: Set[str] = {"paid", "cancelled", "written_off"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _amount(invoice: Dict[str, Any]) -> float:
    raw = invoice.get("amount_gbp", invoice.get("amount", 0.0))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _invoice_id(invoice: Dict[str, Any]) -> str:
    return str(invoice.get("invoice_id") or invoice.get("id") or "").strip()


def _invoice_number(invoice: Dict[str, Any]) -> str:
    return str(
        invoice.get("invoice_number")
        or invoice.get("reference")
        or invoice.get("invoice_ref")
        or _invoice_id(invoice)
        or ""
    ).strip()


def _counterparty(invoice: Dict[str, Any]) -> str:
    return str(
        invoice.get("counterparty")
        or invoice.get("counterpart")
        or invoice.get("client_name")
        or ""
    ).strip()


def _days_overdue(invoice: Dict[str, Any]) -> int:
    raw = invoice.get("days_overdue")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    due = invoice.get("due_date")
    if not due:
        return 0
    try:
        if isinstance(due, datetime):
            due_dt = due
        else:
            due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - due_dt
        return max(int(diff.days), 0)
    except (ValueError, TypeError):
        return 0


def _chase_count(invoice: Dict[str, Any]) -> int:
    try:
        return int(invoice.get("chase_count") or 0)
    except (TypeError, ValueError):
        return 0


def _is_terminal(invoice: Dict[str, Any]) -> bool:
    status = str(invoice.get("status") or "").lower()
    return status in _TERMINAL_STATUSES


def _log_event(kind: str, **payload: Any) -> Dict[str, Any]:
    """Append an event to ``agent_events`` and return it."""

    event = {"ts": _now_iso(), "type": kind, **payload}
    agent_events.append(event)
    return event


# -----------------------------------------------------------------------------
# Specter enrichment
# -----------------------------------------------------------------------------


async def enrich_invoice_specter(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call Specter for the invoice counterparty and attach a `specter_signal` dict.
    Mock fallback handled inside :mod:`specter_client`. Logs ``SPECTER_ENRICHED``.
    """

    counterparty = _counterparty(invoice)
    amount = _amount(invoice)

    try:
        signal = await enrich_counterparty(counterparty, amount)
    except Exception as exc:  # belt-and-braces — client also handles failures
        logger.warning("Specter enrichment exception (%s) — using empty mock", exc)
        signal = {
            "available": False,
            "company_name": counterparty,
            "risk_classification": "MEDIUM",
            "payment_velocity_trend": "UNKNOWN",
            "payment_velocity_change_pct": None,
            "company_health_score": None,
            "cdd_status": "REQUIRES_REVIEW",
            "cdd_notes": "Specter unavailable — defaulting to review.",
            "raw_specter_data": {"source": "exception_fallback"},
            "enriched_at": _now_iso(),
            "mock": True,
        }

    invoice["specter_signal"] = signal
    invoice["specter_enriched_at"] = signal.get("enriched_at")

    _log_event(
        "SPECTER_ENRICHED",
        invoice_id=_invoice_id(invoice),
        counterparty=counterparty,
        status_label=specter_status_label(signal),
        risk_classification=signal.get("risk_classification"),
        cdd_status=signal.get("cdd_status"),
        mock=signal.get("mock", False),
    )
    return signal


# -----------------------------------------------------------------------------
# AML pipeline
# -----------------------------------------------------------------------------


def run_aml_check_invoice(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply AML checks against the current portfolio (``agent_invoices``).

    Sets ``invoice['aml_result']`` and, when ``hard_block_required``, marks
    ``invoice['status'] = 'aml_flagged'``. Logs ``AML_FLAG_RAISED`` /
    ``SAR_CONSIDERATION_TRIGGERED`` and updates session stats.
    """

    aml_result = run_aml_checks(invoice, agent_invoices)
    invoice["aml_result"] = aml_result
    invoice["aml_checked_at"] = _now_iso()

    flag_count = int(aml_result.get("flag_count") or 0)
    if flag_count:
        agent_session_stats["aml_flags_raised"] = (
            int(agent_session_stats.get("aml_flags_raised") or 0) + flag_count
        )

    if aml_result.get("hard_block_required"):
        invoice["status"] = "aml_flagged"
        invoice["awaiting_human_review"] = True
        _log_event(
            "AML_FLAG_RAISED",
            invoice_id=_invoice_id(invoice),
            counterparty=_counterparty(invoice),
            highest_severity=aml_result.get("highest_severity"),
            flag_count=flag_count,
            framework_references=aml_result.get("framework_references"),
            human_review_note=aml_result.get("human_review_note"),
            framing="Pattern consistent with MLR 2017 / NCA typologies — human review required",
        )

    if aml_result.get("sar_consideration"):
        agent_session_stats["sar_considerations"] = (
            int(agent_session_stats.get("sar_considerations") or 0) + 1
        )
        _log_event(
            "SAR_CONSIDERATION_TRIGGERED",
            invoice_id=_invoice_id(invoice),
            counterparty=_counterparty(invoice),
            framework_references=aml_result.get("framework_references"),
            note="Consider SAR obligation under POCA 2002 s.330 — surface to human reviewer.",
        )

    return aml_result


# -----------------------------------------------------------------------------
# Late Payment of Commercial Debts (Interest) Act 1998
# -----------------------------------------------------------------------------


_UK_STATUTORY_RATE = 0.135  # 5.5% BoE base + 8% per UK statute approximation


def calculate_uk_late_payment_interest(invoice: Dict[str, Any]) -> float:
    """
    Approximate statutory interest under the **Late Payment of Commercial Debts (Interest) Act 1998**.

    Calculates ``amount * (rate/365) * days_overdue`` if ``days_overdue > 30`` and config enables it.
    Attaches ``invoice['late_payment_interest']`` and updates ``late_payment_interest_identified`` stat.
    """

    if not autonomy_config.get("uk_late_payment_act", True):
        invoice["late_payment_interest"] = 0.0
        return 0.0

    days = _days_overdue(invoice)
    if days <= 30:
        invoice["late_payment_interest"] = 0.0
        return 0.0

    amount = _amount(invoice)
    interest = round(amount * (_UK_STATUTORY_RATE / 365.0) * days, 2)

    previous = float(invoice.get("late_payment_interest") or 0.0)
    invoice["late_payment_interest"] = interest
    invoice["late_payment_rate_pct"] = _UK_STATUTORY_RATE * 100.0
    invoice["late_payment_basis"] = (
        "Late Payment of Commercial Debts (Interest) Act 1998 — statutory rate "
        "(approx 5.5% BoE base + 8% = 13.5%)"
    )

    delta = interest - previous
    if delta > 0:
        agent_session_stats["late_payment_interest_identified"] = round(
            float(agent_session_stats.get("late_payment_interest_identified") or 0.0) + delta, 2
        )
    return interest


# -----------------------------------------------------------------------------
# Three-tier autonomy decision
# -----------------------------------------------------------------------------


def determine_autonomy_tier(invoice: Dict[str, Any]) -> str:
    """Resolve **AUTO / ESCALATE / HARD_BLOCK** for one invoice (see module docstring)."""

    aml_result = invoice.get("aml_result") or {}
    specter = invoice.get("specter_signal") or {}
    amount = _amount(invoice)
    risk = str(specter.get("risk_classification") or "").upper()
    cdd = str(specter.get("cdd_status") or "").upper()

    # ---------- HARD_BLOCK conditions ----------
    if aml_result.get("hard_block_required"):
        return AutonomyTier.HARD_BLOCK.value
    if cdd == "FAILED":
        return AutonomyTier.HARD_BLOCK.value
    if amount > 5000.0 and risk == "FLAGGED":
        return AutonomyTier.HARD_BLOCK.value

    mode = str(autonomy_config.get("mode") or "guided").lower()

    # ---------- ESCALATE conditions ----------
    if mode == "human_all":
        return AutonomyTier.ESCALATE.value
    if amount > float(autonomy_config.get("threshold_gbp") or 0.0):
        return AutonomyTier.ESCALATE.value
    if cdd == "REQUIRES_REVIEW":
        return AutonomyTier.ESCALATE.value
    if risk == "HIGH":
        return AutonomyTier.ESCALATE.value
    if _chase_count(invoice) >= 3:
        return AutonomyTier.ESCALATE.value

    pending_action = str(invoice.get("_pending_action") or "").lower()
    if mode == "guided" and pending_action in {"escalate_legal", "escalate_account_manager"}:
        return AutonomyTier.ESCALATE.value

    # ---------- AUTO ----------
    if mode in {"guided", "full_auto"}:
        return AutonomyTier.AUTO.value

    return AutonomyTier.ESCALATE.value


# -----------------------------------------------------------------------------
# Rule engine — outcome action label
# -----------------------------------------------------------------------------


def apply_rules(invoice: Dict[str, Any]) -> str:
    """
    Resolve the next chase action for an invoice.

    AML hard-block on the invoice always returns ``hard_block_aml`` (defence-in-depth).
    Computes statutory interest as a side effect. Other branches:

    - PO lifecycle: ``po_missing`` / ``po_expired`` / ``po_expiring_soon``
    - Overdue bands: ``overdue_30`` / ``overdue_60`` / ``overdue_90_plus``
    - Hold reasons: ``hold_dispute`` / ``hold_payment_plan``
    - Status: ``ready`` (not yet due chase), ``paid_pending`` (paid recorded, awaiting clearing)
    """

    if str(invoice.get("status") or "").lower() == "aml_flagged":
        return "hard_block_aml"

    calculate_uk_late_payment_interest(invoice)

    status = str(invoice.get("status") or "").lower()
    if status in {"paid_pending", "paid", "paid_pending_confirmation"}:
        return "paid_pending"

    hold = str(invoice.get("hold_reason") or invoice.get("hold") or "").lower()
    if hold:
        if "dispute" in hold:
            return "hold_dispute"
        if "plan" in hold or "instalment" in hold:
            return "hold_payment_plan"

    po_status = str(invoice.get("po_status") or "").lower()
    if po_status:
        if po_status in {"missing", "absent", "none"}:
            return "po_missing"
        if po_status in {"expired", "lapsed"}:
            return "po_expired"
        if po_status in {"expiring", "expiring_soon"}:
            return "po_expiring_soon"
    elif invoice.get("po_required") and not invoice.get("po_number"):
        return "po_missing"

    days = _days_overdue(invoice)
    if days >= 90:
        return "overdue_90_plus"
    if days >= 60:
        return "overdue_60"
    if days >= 30:
        return "overdue_30"
    if days > 0:
        return "overdue_30"

    return "ready"


# -----------------------------------------------------------------------------
# Routing / draft / pre-send verification
# -----------------------------------------------------------------------------


def route_for_action(invoice: Dict[str, Any], action: str) -> Tuple[str, str]:
    """
    Decide ``(to_email, routing_reason)`` based on the action.

    PO-related actions go to procurement when present; everything else goes to AP / billing.
    """

    procurement = str(
        invoice.get("procurement_email")
        or invoice.get("supplier_email")
        or invoice.get("billing_email_procurement")
        or ""
    ).strip()
    accounts = str(
        invoice.get("accounts_payable_email")
        or invoice.get("ap_email")
        or invoice.get("billing_email")
        or invoice.get("email")
        or ""
    ).strip()

    if action.startswith("po_"):
        if procurement:
            return procurement, "PO-related action routed to procurement contact"
        if accounts:
            return accounts, "PO-related action routed to AP — procurement contact missing"
        return "", "No routable email address available for PO action"

    if accounts:
        return accounts, "Routed to AP / billing contact"
    if procurement:
        return procurement, "Routed to procurement — AP contact missing"
    return "", "No routable email address available"


def _redirect_if_demo(to_email: str) -> Tuple[str, str]:
    """Apply ``demo_redirect_enabled`` and ``redirect_to`` to outbound (returns final to + cc)."""

    cc = str(autonomy_config.get("cc") or "").strip()
    if autonomy_config.get("demo_redirect_enabled") and autonomy_config.get("redirect_to"):
        return str(autonomy_config["redirect_to"]).strip(), cc
    return to_email, cc


# ---- Email drafting (Anthropic with template fallback) ----

_ACTION_LABELS: Dict[str, str] = {
    "po_missing": "Missing purchase order",
    "po_expired": "Expired purchase order",
    "po_expiring_soon": "Purchase order expiring soon",
    "overdue_30": "Invoice overdue (30+ days)",
    "overdue_60": "Invoice overdue (60+ days)",
    "overdue_90_plus": "Invoice significantly overdue (90+ days)",
    "ready": "Upcoming invoice reminder",
    "paid_pending": "Payment receipt acknowledgement",
    "hold_dispute": "Disputed invoice — clarification request",
    "hold_payment_plan": "Payment plan check-in",
    "escalate_account_manager": "Escalation to account manager",
    "escalate_legal": "Final notice — legal escalation review",
}


def _injection_safe(text: str) -> bool:
    suspicious_patterns = (
        "<script",
        "javascript:",
        "{{",
        "}}",
        "<%",
        "%>",
        "${",
        "ignore previous",
        "system prompt",
    )
    haystack = text.lower()
    return not any(p in haystack for p in suspicious_patterns)


def _format_amount_for_body(amount: float, currency: str = "GBP") -> str:
    sym = "£" if currency.upper() == "GBP" else ""
    return f"{sym}{amount:,.2f}".rstrip("0").rstrip(".") if False else f"{sym}{amount:,.2f}"


def _template_draft(invoice: Dict[str, Any], action: str) -> Dict[str, Any]:
    """Deterministic template fallback used when Anthropic SDK or key is unavailable."""

    counterparty = _counterparty(invoice) or "there"
    inv_no = _invoice_number(invoice) or "(reference unavailable)"
    amount = _amount(invoice)
    currency = str(invoice.get("currency") or "GBP")
    amount_str = f"{('£' if currency.upper() == 'GBP' else currency + ' ')}{amount:,.2f}"
    days = _days_overdue(invoice)
    interest = float(invoice.get("late_payment_interest") or 0.0)
    aml = invoice.get("aml_result") or {}
    has_aml = bool(aml.get("flag_count"))

    label = _ACTION_LABELS.get(action, "Invoice update")
    subject_prefix = {
        "po_missing": "Action needed: PO information for invoice",
        "po_expired": "Action needed: PO renewal for invoice",
        "po_expiring_soon": "Heads-up: PO expiring soon for invoice",
        "overdue_30": "Reminder: invoice overdue",
        "overdue_60": "Second reminder: invoice overdue",
        "overdue_90_plus": "Final reminder: significantly overdue invoice",
        "ready": "Upcoming payment reminder for invoice",
        "paid_pending": "Thank you — payment received for invoice",
        "hold_dispute": "Following up on disputed invoice",
        "hold_payment_plan": "Payment plan check-in for invoice",
    }.get(action, "Update on invoice")

    subject = f"{subject_prefix} {inv_no}"

    if action == "paid_pending":
        opening = (
            f"Hello {counterparty},\n\n"
            f"Thank you for the payment for invoice {inv_no} ({amount_str}). "
            "We're updating our records and will be in touch only if there's anything outstanding.\n\n"
        )
    elif action.startswith("po_"):
        opening = (
            f"Hello {counterparty},\n\n"
            f"We're writing about invoice {inv_no} for {amount_str}. "
            f"{label.lower()} — could your procurement team confirm or provide an updated PO so we can keep things moving?\n\n"
        )
    elif action.startswith("hold_"):
        opening = (
            f"Hello {counterparty},\n\n"
            f"We wanted to follow up on invoice {inv_no} ({amount_str}). "
            f"{label.lower()} — please could you share an update at your convenience?\n\n"
        )
    else:
        days_phrase = f"{days} day{'s' if days != 1 else ''} past due" if days else "approaching its due date"
        opening = (
            f"Hello {counterparty},\n\n"
            f"This is a courtesy follow-up regarding invoice {inv_no} for {amount_str}, currently {days_phrase}.\n\n"
        )

    interest_note = ""
    if interest > 0 and action != "paid_pending":
        interest_note = (
            f"For information, statutory interest under the Late Payment of Commercial Debts "
            f"(Interest) Act 1998 currently estimates at approximately £{interest:,.2f} based on "
            f"a {invoice.get('late_payment_rate_pct', 13.5):.1f}% statutory rate. "
            "We would prefer to settle without applying it.\n\n"
        )

    closing = (
        "Could you confirm a payment date or let us know if anything is outstanding from our side? "
        "Happy to jump on a quick call if that helps.\n\n"
        "Kind regards,\n"
        "Finoks — Accounts team"
    )

    body = opening + interest_note + closing

    confidence = 78
    if not counterparty or counterparty == "there":
        confidence -= 10
    if inv_no.startswith("("):
        confidence -= 15
    if has_aml:
        confidence -= 5
    if not _injection_safe(body):
        confidence -= 30
    confidence = max(0, min(100, confidence))

    return {"subject": subject, "body": body, "confidence_score": confidence, "source": "template"}


def _build_system_prompt(invoice: Dict[str, Any], action: str) -> str:
    aml = invoice.get("aml_result") or {}
    aml_present = bool(aml.get("flag_count"))
    procurement_path = action.startswith("po_")
    return (
        "You are Finoks — an autonomous accounts-receivable assistant for UK B2B invoices.\n"
        "Write a single concise, professional UK-English email (no marketing tone, no emojis).\n"
        "Sign off as 'Finoks — Accounts team'.\n"
        "Tone: respectful, factual, action-oriented. Match British business norms.\n"
        f"Action context: {_ACTION_LABELS.get(action, action)}.\n"
        f"Recipient role: {'procurement / buyer contact' if procurement_path else 'accounts payable / finance contact'}. "
        "Adjust phrasing accordingly.\n"
        "Hard rules:\n"
        "- Reference the invoice number and exact amount in GBP if provided.\n"
        "- Do not mention compliance, AML, suspicion, money laundering, fraud, SAR, or any "
        "internal risk flagging in the email body.\n"
        "- Do not include personal data beyond name and corporate email.\n"
        "- Do not use exaggerated language or threats; mention statutory interest only when relevant.\n"
        + (
            "- Note: this counterparty currently has internal review flags; remain extra neutral, "
            "stick strictly to factual invoice details, and avoid any reference to ongoing review.\n"
            if aml_present
            else ""
        )
        + "Return only the email subject (single line) and body (plain text)."
    )


async def draft_email(invoice: Dict[str, Any], action: str) -> Dict[str, Any]:
    """
    Draft a chase email using Anthropic when configured. Falls back to template otherwise.

    Returns ``{subject, body, confidence_score (0-100), source}``.
    """

    template_draft = _template_draft(invoice, action)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return template_draft

    try:
        import anthropic  # type: ignore
    except Exception:
        logger.info("Anthropic SDK unavailable — using template draft")
        return template_draft

    try:
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(invoice, action)
        counterparty = _counterparty(invoice)
        inv_no = _invoice_number(invoice)
        amount = _amount(invoice)
        days = _days_overdue(invoice)
        interest = float(invoice.get("late_payment_interest") or 0.0)
        currency = str(invoice.get("currency") or "GBP")
        user_payload = (
            f"Counterparty: {counterparty}\n"
            f"Invoice number: {inv_no}\n"
            f"Amount: {currency} {amount:,.2f}\n"
            f"Days overdue: {days}\n"
            f"Statutory late-payment interest (if any): £{interest:,.2f}\n"
            f"Action: {action}\n"
            "Format your reply exactly as:\n"
            "SUBJECT: <single-line subject>\n"
            "BODY:\n<plain text body, multi-line>"
        )
        message = await asyncio.to_thread(
            client.messages.create,
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = ""
        for block in getattr(message, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                text += t
        text = text.strip()
        if not text:
            return template_draft

        m = re.search(r"SUBJECT:\s*(.+)", text)
        subject = m.group(1).strip() if m else template_draft["subject"]
        b = re.search(r"BODY:\s*(.*)", text, flags=re.DOTALL)
        body = b.group(1).strip() if b else text

        confidence = 88
        if not _injection_safe(body):
            confidence -= 40
        if invoice.get("aml_result", {}).get("flag_count"):
            confidence -= 5
        confidence = max(0, min(100, confidence))

        return {"subject": subject, "body": body, "confidence_score": confidence, "source": "anthropic"}
    except Exception as exc:
        logger.warning("Anthropic draft failed (%s) — using template", exc)
        return template_draft


_SUSPICIOUS_TERMS = (
    "money laundering",
    "suspicion",
    "sar",
    "aml",
    "money-laundering",
    "compliance flag",
    "ssn",
    "national insurance",
    "passport number",
    "credit card",
)


def verify_outbound_email(invoice: Dict[str, Any], draft: Dict[str, Any], action: str) -> Dict[str, Any]:
    """
    Pre-send verification — defence-in-depth before any email leaves Finoks.

    Returns ``{passed, confidence, checks, blocked_reason}``.
    """

    body = str(draft.get("body") or "")
    subject = str(draft.get("subject") or "")
    full = f"{subject}\n{body}"
    checks: List[Dict[str, Any]] = []
    blocked_reason: Optional[str] = None

    amount = _amount(invoice)
    inv_no = _invoice_number(invoice)
    aml = invoice.get("aml_result") or {}

    # 1. Amount present
    amount_str_a = f"{amount:,.2f}"
    amount_str_b = f"{amount:.2f}"
    amount_str_c = f"{int(amount):,}" if amount.is_integer() else None
    candidates = [amount_str_a, amount_str_b]
    if amount_str_c:
        candidates.append(amount_str_c)
    amount_ok = action == "paid_pending" or any(c in body for c in candidates)
    if action == "paid_pending":
        amount_ok = True
    checks.append(
        {
            "name": "amount_present",
            "passed": amount_ok,
            "note": "Numeric invoice amount visible in body" if amount_ok else "Amount missing from body",
        }
    )

    # 2. Invoice number present
    inv_ok = (not inv_no) or (inv_no and inv_no in body)
    checks.append(
        {
            "name": "invoice_number_present",
            "passed": bool(inv_ok),
            "note": "Invoice number visible in body" if inv_ok else "Invoice number missing from body",
        }
    )

    # 3. No PII hints beyond name/email
    pii_hits = [t for t in ("ssn", "national insurance", "passport number", "credit card") if t in body.lower()]
    pii_ok = not pii_hits
    checks.append(
        {
            "name": "no_pii_overshare",
            "passed": pii_ok,
            "note": "No sensitive PII detected" if pii_ok else f"Suspicious PII tokens: {pii_hits}",
        }
    )

    # 4. Tone matches overdue level
    days = _days_overdue(invoice)
    tone_ok = True
    tone_note = "Tone consistent with action"
    body_lower = body.lower()
    if action == "ready" and any(w in body_lower for w in ("final notice", "legal action", "demand")):
        tone_ok, tone_note = False, "Aggressive language unsuitable for a non-overdue notice"
    if action in ("overdue_30",) and "final notice" in body_lower and days < 60:
        tone_ok, tone_note = False, "Final-notice phrasing too strong for 30-day band"
    if action == "paid_pending" and any(w in body_lower for w in ("overdue", "chase", "demand")):
        tone_ok, tone_note = False, "Chase phrasing in a thank-you email"
    checks.append({"name": "tone_appropriate", "passed": tone_ok, "note": tone_note})

    # 5. Intent consistent
    intent_ok = True
    intent_note = "Intent matches action"
    if action == "paid_pending" and "thank" not in body_lower:
        intent_ok, intent_note = False, "Acknowledgement email missing thank-you intent"
    elif action.startswith("overdue_") and not any(w in body_lower for w in ("invoice", "payment", "due")):
        intent_ok, intent_note = False, "Chase email lacks payment-context terms"
    checks.append({"name": "intent_consistent", "passed": intent_ok, "note": intent_note})

    # 6. Injection / template-string safety
    inj_ok = _injection_safe(full)
    checks.append(
        {
            "name": "no_injection_strings",
            "passed": inj_ok,
            "note": "No injection / template strings detected" if inj_ok else "Suspicious script/template strings found",
        }
    )

    # 7. AML safety net (final defence-in-depth)
    aml_ok = True
    aml_note = "No AML hard-block on this invoice"
    if str(invoice.get("status") or "").lower() == "aml_flagged" or aml.get("hard_block_required"):
        aml_ok = False
        aml_note = (
            "Pattern consistent with MLR 2017 / NCA typologies — human review required; "
            "send blocked by pre-send verification."
        )
    elif any(term in body_lower for term in _SUSPICIOUS_TERMS):
        aml_ok = False
        aml_note = "Body references compliance / suspicion terminology — must not appear in customer email"
    checks.append({"name": "aml_safety_net", "passed": aml_ok, "note": aml_note})

    # 8. Confidence threshold
    confidence = int(draft.get("confidence_score") or 0)
    conf_ok = confidence >= 70
    checks.append(
        {
            "name": "confidence_threshold",
            "passed": conf_ok,
            "note": f"Draft confidence {confidence} (>=70)" if conf_ok else f"Draft confidence {confidence} below 70",
        }
    )

    failed = [c for c in checks if not c["passed"]]
    if failed:
        if any(c["name"] == "aml_safety_net" for c in failed):
            blocked_reason = "AML hard-block detected at pre-send verification"
        else:
            blocked_reason = f"Pre-send verification failed: {', '.join(c['name'] for c in failed)}"

    return {
        "passed": not failed,
        "confidence": confidence,
        "checks": checks,
        "blocked_reason": blocked_reason,
    }


# -----------------------------------------------------------------------------
# Tick orchestration
# -----------------------------------------------------------------------------


def _broadcast_state_payload(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "AGENT_STATE",
        "ts": _now_iso(),
        "running": agent_running,
        "stats": dict(agent_session_stats),
        "config": dict(autonomy_config),
        "invoice_count": len(agent_invoices),
        "events_tail": agent_events[-25:],
    }
    if extra:
        payload.update(extra)
    return payload


def _eligible_for_processing(invoice: Dict[str, Any]) -> bool:
    if _is_terminal(invoice):
        return False
    if invoice.get("processed_this_session"):
        return False
    return True


async def _process_one_invoice(invoice: Dict[str, Any]) -> None:
    invoice_id = _invoice_id(invoice)
    counterparty = _counterparty(invoice)

    # 1. ENRICH
    if autonomy_config.get("specter_enrichment", True) and not invoice.get("specter_signal"):
        await enrich_invoice_specter(invoice)

    # 2. AML CHECK
    if autonomy_config.get("aml_checks", True) and not invoice.get("aml_result"):
        run_aml_check_invoice(invoice)

    # 3. OBSERVE
    _log_event(
        "OBSERVED",
        invoice_id=invoice_id,
        counterparty=counterparty,
        amount=_amount(invoice),
        days_overdue=_days_overdue(invoice),
        chase_count=_chase_count(invoice),
        status=invoice.get("status"),
    )

    # 4. APPLY RULES
    action = apply_rules(invoice)
    invoice["action"] = action
    invoice["_pending_action"] = action

    # 5. DETERMINE TIER
    tier = determine_autonomy_tier(invoice)

    # 6. DECIDE — log routing and signals snapshot
    to_email, routing_reason = route_for_action(invoice, action)
    final_to, cc = _redirect_if_demo(to_email)
    specter = invoice.get("specter_signal") or {}
    aml = invoice.get("aml_result") or {}
    decided_event = _log_event(
        "DECIDED",
        invoice_id=invoice_id,
        counterparty=counterparty,
        action=action,
        autonomy_tier=tier,
        routing_reason=routing_reason,
        to=final_to,
        cc=cc,
        specter={
            "status_label": specter_status_label(specter) if specter else "Specter: UNAVAILABLE",
            "risk_classification": specter.get("risk_classification"),
            "cdd_status": specter.get("cdd_status"),
            "mock": specter.get("mock", False),
        },
        aml_flag_count=int(aml.get("flag_count") or 0),
        aml_highest_severity=aml.get("highest_severity"),
    )

    invoice["autonomy_tier"] = tier

    # ----- HARD_BLOCK -----
    if tier == AutonomyTier.HARD_BLOCK.value:
        invoice["awaiting_human_review"] = True
        agent_session_stats["hard_blocked"] = int(agent_session_stats.get("hard_blocked") or 0) + 1
        _log_event(
            "HARD_BLOCKED",
            invoice_id=invoice_id,
            counterparty=counterparty,
            reason=(
                "AML hard-block — pattern consistent with MLR 2017 / NCA typologies; human review required"
                if aml.get("hard_block_required")
                else (
                    "Specter CDD FAILED — Reg.28 review required"
                    if str(specter.get("cdd_status") or "").upper() == "FAILED"
                    else "Material amount with Specter FLAGGED counterparty"
                )
            ),
            framework_references=aml.get("framework_references"),
            decided_event_ts=decided_event["ts"],
        )
        return

    # ----- ESCALATE -----
    human_approved_escalation = bool(
        invoice.get("approved_by") and not invoice.get("awaiting_approval")
    )

    if tier == AutonomyTier.ESCALATE.value and not human_approved_escalation:
        draft = await draft_email(invoice, action)
        verification = verify_outbound_email(invoice, draft, action)
        invoice["draft"] = {
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "confidence_score": draft.get("confidence_score"),
        }
        invoice["pre_send_verification"] = verification
        invoice["awaiting_approval"] = True
        agent_session_stats["escalated"] = int(agent_session_stats.get("escalated") or 0) + 1
        _log_event(
            "AWAITING_APPROVAL",
            invoice_id=invoice_id,
            counterparty=counterparty,
            action=action,
            confidence_score=draft.get("confidence_score"),
            verification_passed=verification["passed"],
            blocked_reason=verification.get("blocked_reason"),
            to=final_to,
        )
        return

    # ----- AUTO (or approved-escalation send) -----
    if human_approved_escalation and invoice.get("draft"):
        # Re-use the human-reviewed draft; only re-run pre-send verification.
        draft = dict(invoice["draft"])
    else:
        draft = await draft_email(invoice, action)
    verification = verify_outbound_email(invoice, draft, action)
    invoice["draft"] = {
        "subject": draft.get("subject"),
        "body": draft.get("body"),
        "confidence_score": draft.get("confidence_score"),
    }
    invoice["pre_send_verification"] = verification

    if not final_to:
        _log_event(
            "BLOCKED",
            invoice_id=invoice_id,
            counterparty=counterparty,
            action=action,
            reason="No routable email address",
        )
        invoice["processed_this_session"] = True
        return

    if verification["passed"]:
        send_result: Dict[str, Any] = {"status": "skipped"}
        try:
            from email_sender import send_chase_email

            send_result = send_chase_email(  # type: ignore[misc]
                to_address=final_to,
                subject=draft["subject"],
                body_text=draft["body"],
                provider=os.getenv("EMAIL_PROVIDER"),
            )
            if asyncio.iscoroutine(send_result):
                send_result = await send_result  # type: ignore[assignment]
        except NotImplementedError:
            send_result = {"status": "stubbed", "note": "email_sender not yet implemented — recorded only"}
        except Exception as exc:
            logger.warning("send_chase_email error suppressed: %s", exc)
            send_result = {"status": "error", "error": str(exc)}

        invoice["last_send_result"] = send_result
        invoice["last_sent_action"] = action
        invoice["chase_count"] = _chase_count(invoice) + 1

        agent_session_stats["emails_sent"] = int(agent_session_stats.get("emails_sent") or 0) + 1
        agent_session_stats["auto_actioned"] = int(agent_session_stats.get("auto_actioned") or 0) + 1

        if action == "paid_pending":
            agent_session_stats["recovered_value"] = round(
                float(agent_session_stats.get("recovered_value") or 0.0) + _amount(invoice), 2
            )

        _log_event(
            "SENT",
            invoice_id=invoice_id,
            counterparty=counterparty,
            action=action,
            to=final_to,
            cc=cc,
            confidence_score=draft.get("confidence_score"),
            provider=os.getenv("EMAIL_PROVIDER"),
            result=send_result,
        )
    else:
        _log_event(
            "BLOCKED",
            invoice_id=invoice_id,
            counterparty=counterparty,
            action=action,
            reason=verification.get("blocked_reason"),
            verification=verification,
        )

    invoice["processed_this_session"] = True


async def run_agent_tick() -> Dict[str, Any]:
    """
    Single tick of the autonomy loop. Honors three-tier rules per invoice and broadcasts state.

    Intended to be scheduled at ~15-second cadence by APScheduler.
    """

    agent_session_stats["total_ticks"] = int(agent_session_stats.get("total_ticks") or 0) + 1
    tick_event = _log_event("TICK_START", invoice_count=len(agent_invoices))

    processed_ids: List[str] = []
    for invoice in list(agent_invoices):
        if not _eligible_for_processing(invoice):
            continue
        try:
            await _process_one_invoice(invoice)
            processed_ids.append(_invoice_id(invoice))
        except Exception as exc:
            logger.exception("Tick processing failed for %s", _invoice_id(invoice))
            _log_event(
                "ERROR",
                invoice_id=_invoice_id(invoice),
                error=str(exc),
                stage="process_one_invoice",
            )

    _log_event(
        "TICK_END",
        invoice_count=len(agent_invoices),
        processed=len(processed_ids),
        started_at=tick_event["ts"],
    )

    summary = _broadcast_state_payload({"processed_this_tick": processed_ids})
    await _safe_broadcast(summary)
    return summary


# Backwards-compat alias used by main.py wiring scaffolding.
def tick_scheduler_callback() -> None:
    """APScheduler-friendly wrapper: schedules :func:`run_agent_tick` on the running loop."""

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(run_agent_tick(), loop=loop)
            return
    except RuntimeError:
        pass
    asyncio.run(run_agent_tick())


def evaluate_tier_for_invoice(
    invoice: Dict[str, Any],
    specter_normalized: Dict[str, Any],
    aml_flags: List[str],
    amount_gbp_threshold: float,
) -> AutonomyTier:
    """
    Backwards-compat helper — uses the same rules as :func:`determine_autonomy_tier`.

    Mutates ``invoice`` only through transient ``specter_signal`` / ``aml_result`` shadows.
    """

    shadow = dict(invoice)
    if specter_normalized:
        shadow["specter_signal"] = specter_normalized
    if aml_flags:
        shadow["aml_result"] = {
            "flag_count": len(aml_flags),
            "highest_severity": "HIGH",
            "hard_block_required": True,
        }
    prior_threshold = autonomy_config.get("threshold_gbp")
    autonomy_config["threshold_gbp"] = float(amount_gbp_threshold)
    try:
        tier_str = determine_autonomy_tier(shadow)
    finally:
        autonomy_config["threshold_gbp"] = prior_threshold
    return AutonomyTier(tier_str)


def compose_chase_body(invoice: Dict[str, Any], tier: AutonomyTier) -> str:
    """
    Backwards-compat: produce a plaintext chase body using the template path.

    HARD_BLOCK never sends — returns an empty string and surfaces the AML framing as a comment.
    """

    if tier == AutonomyTier.HARD_BLOCK:
        return ""
    action = apply_rules(invoice) if invoice.get("aml_result") is not None else "ready"
    return _template_draft(invoice, action)["body"]
