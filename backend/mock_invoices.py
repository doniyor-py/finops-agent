"""
Finoks — Demo invoices and CSV helpers.

The demo set covers every rule branch and every autonomy tier:

- AUTO: small overdue, PO expiring soon, and thank-you / paid_pending_confirmation paths.
- ESCALATE: amount above threshold, missing PO routed to procurement, escalated chase count, hold reasons.
- HARD_BLOCK: shell-name + new + large counterparty (AML), and velocity anomaly + Specter HIGH risk.

Every invoice carries a deterministic ``specter_signal`` so demo behaviour is reproducible
even when the live Specter API is unreachable. ``aml_result`` is pre-populated only where
the spec requires SAR consideration to surface (Meridian Holdings International).
"""

from __future__ import annotations

import copy
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

CSV_COLUMNS: Tuple[str, ...] = (
    "invoice_id",
    "client_name",
    "contact_name",
    "email",
    "amount",
    "currency",
    "invoice_number",
    "days_overdue",
    "status",
    "chase_count",
    "po_number",
    "po_status",
    "po_expiry",
    "procurement_email",
    "procurement_contact_name",
    "activity",
    "contract_value",
    "billed_to_date",
    "vat_applicable",
    "vat_number",
    "hold_reason",
    "months_since_last_invoice",
    "dormant_client_return",
    "prior_procurement_email",
)

_DEMO_NAMESPACE = uuid.UUID("8d4a4d5d-4f00-4a32-8f00-f1110ccdeb00")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_iso() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _due_date_for(days_overdue: int) -> str:
    return (_today_iso() - timedelta(days=int(days_overdue))).date().isoformat()


def _stable_uuid(seed: str) -> str:
    return str(uuid.uuid5(_DEMO_NAMESPACE, seed))


def _specter_signal(
    *,
    company_name: str,
    risk_classification: str,
    payment_velocity_trend: str,
    payment_velocity_change_pct: Optional[float],
    company_health_score: Optional[float],
    cdd_status: str,
    cdd_notes: str,
) -> Dict[str, Any]:
    return {
        "available": False,
        "company_name": company_name,
        "risk_classification": risk_classification,
        "payment_velocity_trend": payment_velocity_trend,
        "payment_velocity_change_pct": payment_velocity_change_pct,
        "company_health_score": company_health_score,
        "cdd_status": cdd_status,
        "cdd_notes": cdd_notes,
        "raw_specter_data": {"source": "demo_seed", "seed": company_name.lower()},
        "enriched_at": _now_iso(),
        "mock": True,
    }


def _atlas_aml_result(invoice_uuid: str) -> Dict[str, Any]:
    """Pre-populated AML result for Atlas Infrastructure Group — velocity anomaly CRITICAL."""

    flags = [
        {
            "check_name": "velocity_new_relationship_large",
            "severity": "CRITICAL",
            "description": (
                "Pattern consistent with maiden invoice above £8,000 with no observable AR lineage "
                "for this counterparty — escalate onboarding vigilance; signal suggesting velocity anomaly."
            ),
            "framework_ref": "FCA FCG — unusual velocity",
            "portfolio_level": False,
        },
        {
            "check_name": "identity_reference_pattern",
            "severity": "HIGH",
            "description": (
                "Pattern consistent with reference / entity textual mismatch at material exposure — "
                "consider Reg.28 CDD refresh."
            ),
            "framework_ref": "MLR 2017 Reg.28 CDD (FCG invoice anomalies)",
            "portfolio_level": False,
        },
    ]
    refs: List[str] = []
    for f in flags:
        if f["framework_ref"] not in refs:
            refs.append(f["framework_ref"])
    return {
        "invoice_id": invoice_uuid,
        "flags": flags,
        "flag_count": len(flags),
        "highest_severity": "CRITICAL",
        "hard_block_required": True,
        "framework_references": refs,
        "human_review_note": (
            f"Invoice {invoice_uuid} — human review warranted. "
            "Pattern consistent with first-engagement high-value exposure; "
            "consider SAR obligation under POCA 2002 s.330 if suspicion crystallises — "
            "not an instruction to file a SAR."
        ),
        "sar_consideration": True,
    }


def _meridian_aml_result(invoice_uuid: str) -> Dict[str, Any]:
    """
    Pre-populated AML result for Meridian Holdings International — covers the user spec's
    'HARD_BLOCK + AML flagged + SAR consideration' requirement. The framework references
    use hedged language only.
    """

    flags = [
        {
            "check_name": "identity_shell_descriptor",
            "severity": "HIGH",
            "description": (
                "Pattern consistent with shallow corporate descriptor terms ('Holdings', "
                "'International') in a newly onboarded debtor with material exposure — "
                "consider deeper Reg.28 CDD."
            ),
            "framework_ref": "FCG / MLR 2017 Reg.28 — entity substantiation cues",
            "portfolio_level": False,
        },
        {
            "check_name": "structuring_cluster",
            "severity": "CRITICAL",
            "description": (
                "Pattern consistent with structuring-style clustering signal: invoice amount sits "
                "between £8,500.00 and £10,000.00 (exclusive of £10,000); signal suggesting "
                "deliberate sub-reference spacing (not proof of structuring)."
            ),
            "framework_ref": "NCA Typology: structuring (POCA 2002 ss.327–329 thematic); MLR 2017 Reg.19",
            "portfolio_level": False,
        },
        {
            "check_name": "specter_cdd_failed",
            "severity": "HIGH",
            "description": (
                "Specter classification FLAGGED — CDD failed for this counterparty; "
                "do not proceed without Reg.28 enhanced due diligence."
            ),
            "framework_ref": "MLR 2017 Reg.28 — CDD",
            "portfolio_level": False,
        },
    ]
    framework_refs: List[str] = []
    for f in flags:
        ref = f["framework_ref"]
        if ref not in framework_refs:
            framework_refs.append(ref)
    return {
        "invoice_id": invoice_uuid,
        "flags": flags,
        "flag_count": len(flags),
        "highest_severity": "CRITICAL",
        "hard_block_required": True,
        "framework_references": framework_refs,
        "human_review_note": (
            f"Invoice {invoice_uuid} — human review warranted. "
            "Pattern consistent with shell-style corporate descriptor and clustering signal. "
            "Consider SAR obligation under POCA 2002 s.330 if suspicion crystallises — not an instruction "
            "to file a SAR."
        ),
        "sar_consideration": True,
    }


def _scaffold(
    *,
    seed: str,
    client_name: str,
    contact_name: str,
    email: str,
    amount: float,
    invoice_number: str,
    days_overdue: int,
    status: str,
    chase_count: int = 0,
    po_number: Optional[str] = None,
    po_status: Optional[str] = None,
    po_expiry: Optional[str] = None,
    procurement_email: Optional[str] = None,
    procurement_contact_name: Optional[str] = None,
    activity: str = "",
    contract_value: Optional[float] = None,
    billed_to_date: Optional[float] = None,
    vat_applicable: bool = True,
    vat_number: Optional[str] = None,
    hold_reason: Optional[str] = None,
    specter_signal: Optional[Dict[str, Any]] = None,
    aml_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    invoice_uuid = _stable_uuid(seed)
    invoice: Dict[str, Any] = {
        "id": invoice_uuid,
        "invoice_id": invoice_uuid,
        "client_name": client_name,
        "counterparty": client_name,
        "contact_name": contact_name,
        "accounts_contact_name": contact_name,
        "email": email,
        "accounts_payable_email": email,
        "amount": amount,
        "amount_gbp": amount,
        "currency": "GBP",
        "invoice_number": invoice_number,
        "days_overdue": int(days_overdue),
        "due_date": _due_date_for(days_overdue),
        "status": status,
        "chase_count": int(chase_count),
        "po_number": po_number,
        "po_status": po_status,
        "po_expiry": po_expiry,
        "procurement_email": procurement_email,
        "procurement_contact_name": procurement_contact_name,
        "activity": activity,
        "contract_value": contract_value,
        "billed_to_date": billed_to_date,
        "vat_applicable": vat_applicable,
        "vat_number": vat_number,
        "hold_reason": hold_reason,
        "processed_this_session": False,
        "awaiting_approval": False,
        "awaiting_human_review": False,
        "aml_result": aml_result,
        "specter_signal": specter_signal,
        "autonomy_tier": None,
        "draft": None,
        "late_payment_interest": None,
    }
    if aml_result and aml_result.get("hard_block_required"):
        invoice["status"] = "aml_flagged"
        invoice["awaiting_human_review"] = True
    return invoice


# -----------------------------------------------------------------------------
# Demo invoice templates (10 rows covering every branch)
# -----------------------------------------------------------------------------


def _demo_template() -> List[Dict[str, Any]]:
    invoices: List[Dict[str, Any]] = []

    # 1. AUTO — clean, small overdue
    invoices.append(
        _scaffold(
            seed="demo:1:techflow",
            client_name="TechFlow Solutions Ltd",
            contact_name="Priya Sharma",
            email="ap@techflow-solutions.co.uk",
            amount=320.00,
            invoice_number="INV-TF-1042",
            days_overdue=15,
            status="overdue",
            chase_count=0,
            po_number="PO-TF-91022",
            po_status="expiring_soon",
            po_expiry=(_today_iso() + timedelta(days=10)).date().isoformat(),
            procurement_email="mekhmonovd@gmail.com",
            procurement_contact_name="Daniel Hughes",
            activity="Quarterly DevOps platform retainer (March)",
            contract_value=12000.00,
            billed_to_date=3200.00,
            vat_applicable=True,
            vat_number="GB123456001",
            specter_signal=_specter_signal(
                company_name="TechFlow Solutions Ltd",
                risk_classification="LOW",
                payment_velocity_trend="STABLE",
                payment_velocity_change_pct=2.1,
                company_health_score=86.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 2. HARD_BLOCK — shell descriptor + structuring + Specter FLAGGED → SAR consideration
    meridian_uuid = _stable_uuid("demo:2:meridian")
    invoices.append(
        _scaffold(
            seed="demo:2:meridian",
            client_name="Meridian Holdings International",
            contact_name="Olek Petrov",
            email="finance@meridian-holdings-intl.com",
            amount=9500.00,
            invoice_number="MRD-INV-7741",
            days_overdue=45,
            status="overdue",
            chase_count=0,
            po_number=None,
            po_status="missing",
            po_expiry=None,
            procurement_email="buyer@meridian-holdings-intl.com",
            procurement_contact_name="Olek Petrov",
            activity="Cross-border consultancy and advisory engagement (one-off)",
            contract_value=12500.00,
            billed_to_date=9500.00,
            vat_applicable=False,
            vat_number=None,
            specter_signal=_specter_signal(
                company_name="Meridian Holdings International",
                risk_classification="FLAGGED",
                payment_velocity_trend="DETERIORATING",
                payment_velocity_change_pct=-26.5,
                company_health_score=22.0,
                cdd_status="FAILED",
                cdd_notes="Risk classification FLAGGED — CDD must not pass without human review (Reg.28).",
            ),
            aml_result=_meridian_aml_result(meridian_uuid),
        )
    )

    # 3. ESCALATE — missing PO above threshold, route to procurement
    invoices.append(
        _scaffold(
            seed="demo:3:buildright",
            client_name="BuildRight Contractors",
            contact_name="Helen Mason",
            email="ap@buildright.co.uk",
            amount=2800.00,
            invoice_number="BR-2026-0188",
            days_overdue=30,
            status="overdue",
            chase_count=1,
            po_number=None,
            po_status="missing",
            po_expiry=None,
            procurement_email="procurement@buildright.co.uk",
            procurement_contact_name="Frank Doyle",
            activity="Site survey and phase-1 commercial fit-out works",
            contract_value=42000.00,
            billed_to_date=18800.00,
            vat_applicable=True,
            vat_number="GB223344556",
            specter_signal=_specter_signal(
                company_name="BuildRight Contractors",
                risk_classification="MEDIUM",
                payment_velocity_trend="STABLE",
                payment_velocity_change_pct=-1.2,
                company_health_score=66.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 4. AUTO — small, near-due, future thank-you candidate
    invoices.append(
        _scaffold(
            seed="demo:4:sunrise",
            client_name="Sunrise Media Group",
            contact_name="Aoife Kennedy",
            email="mekhmonovd@icloud.com",
            amount=180.00,
            invoice_number="SMG-2026-0099",
            days_overdue=5,
            status="overdue",
            chase_count=0,
            po_number="PO-SMG-3311",
            po_status="valid",
            po_expiry=(_today_iso() + timedelta(days=60)).date().isoformat(),
            procurement_email=None,
            procurement_contact_name=None,
            activity="Editorial podcast production — episode 14",
            contract_value=4800.00,
            billed_to_date=2400.00,
            vat_applicable=True,
            vat_number="GB334455667",
            specter_signal=_specter_signal(
                company_name="Sunrise Media Group",
                risk_classification="LOW",
                payment_velocity_trend="IMPROVING",
                payment_velocity_change_pct=4.6,
                company_health_score=88.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 5. ESCALATE — high amount, HIGH Specter risk, deteriorating velocity, statutory interest applies
    invoices.append(
        _scaffold(
            seed="demo:5:axiom",
            client_name="Axiom Capital Partners",
            contact_name="Marcus Lee",
            email="ap@axiomcapitalpartners.com",
            amount=7200.00,
            invoice_number="AXIOM-CAP-44217",
            days_overdue=67,
            status="overdue",
            chase_count=2,
            po_number="PO-ACP-771",
            po_status="valid",
            po_expiry=(_today_iso() + timedelta(days=45)).date().isoformat(),
            procurement_email="ops@axiomcapitalpartners.com",
            procurement_contact_name="Diana Reyes",
            activity="Quarterly portfolio analytics and reporting service",
            contract_value=36000.00,
            billed_to_date=18000.00,
            vat_applicable=True,
            vat_number="GB445566778",
            specter_signal=_specter_signal(
                company_name="Axiom Capital Partners",
                risk_classification="HIGH",
                payment_velocity_trend="DETERIORATING",
                payment_velocity_change_pct=-15.2,
                company_health_score=42.0,
                cdd_status="REQUIRES_REVIEW",
                cdd_notes="HIGH risk with invoice amount above £5,000 — enhanced review recommended.",
            ),
        )
    )

    # 6. AUTO — just below threshold, PO expiring soon, route to procurement
    invoices.append(
        _scaffold(
            seed="demo:6:vertex",
            client_name="Vertex Systems",
            contact_name="Naomi Carter",
            email="ap@vertexsystems.co.uk",
            amount=490.00,
            invoice_number="VTX-2026-0214",
            days_overdue=22,
            status="overdue",
            chase_count=0,
            po_number="PO-VTX-22817",
            po_status="expiring_soon",
            po_expiry=(_today_iso() + timedelta(days=8)).date().isoformat(),
            procurement_email="mekhmonovd@gmail.com",
            procurement_contact_name="Bilal Iqbal",
            activity="Monthly SaaS access — analytics platform seat block",
            contract_value=5880.00,
            billed_to_date=2940.00,
            vat_applicable=True,
            vat_number="GB556677889",
            specter_signal=_specter_signal(
                company_name="Vertex Systems",
                risk_classification="LOW",
                payment_velocity_trend="STABLE",
                payment_velocity_change_pct=0.4,
                company_health_score=82.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 7. ESCALATE — round-amount candidate, MEDIUM AML routing flag (does not hard-block)
    invoices.append(
        _scaffold(
            seed="demo:7:northern",
            client_name="Northern Logistics PLC",
            contact_name="Tom Blackwood",
            email="accounts@nl-payments.example.com",
            amount=4900.00,
            invoice_number="NLP-26-08812",
            days_overdue=0,
            status="outstanding",
            chase_count=0,
            po_number="PO-NLP-7745",
            po_status="valid",
            po_expiry=(_today_iso() + timedelta(days=180)).date().isoformat(),
            procurement_email="procurement@northern-logistics.co.uk",
            procurement_contact_name="Sara Whitlock",
            activity="Monthly fulfilment and reverse-logistics service",
            contract_value=58800.00,
            billed_to_date=24500.00,
            vat_applicable=True,
            vat_number="GB667788990",
            specter_signal=_specter_signal(
                company_name="Northern Logistics PLC",
                risk_classification="MEDIUM",
                payment_velocity_trend="STABLE",
                payment_velocity_change_pct=-1.8,
                company_health_score=64.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 8. ESCALATE — chase_count >= 3, deteriorating Specter, 92 days overdue
    invoices.append(
        _scaffold(
            seed="demo:8:quantum",
            client_name="Quantum Retail Ltd",
            contact_name="Rebecca Hall",
            email="ap@quantumretail.co.uk",
            amount=850.00,
            invoice_number="QRL-26-3301",
            days_overdue=92,
            status="overdue",
            chase_count=3,
            po_number="PO-QRL-44120",
            po_status="valid",
            po_expiry=(_today_iso() + timedelta(days=30)).date().isoformat(),
            procurement_email=None,
            procurement_contact_name=None,
            activity="Retail merchandising data feeds (Q1)",
            contract_value=10200.00,
            billed_to_date=4250.00,
            vat_applicable=True,
            vat_number="GB778899001",
            specter_signal=_specter_signal(
                company_name="Quantum Retail Ltd",
                risk_classification="MEDIUM",
                payment_velocity_trend="DETERIORATING",
                payment_velocity_change_pct=-12.4,
                company_health_score=48.0,
                cdd_status="REQUIRES_REVIEW",
                cdd_notes="MEDIUM risk with deteriorating payment velocity — review payment behaviour.",
            ),
        )
    )

    # 9. AUTO — paid_pending_confirmation → thank-you path
    invoices.append(
        _scaffold(
            seed="demo:9:bright_events",
            client_name="Bright Events Co",
            contact_name="Hannah Walsh",
            email="zaripboyevdiyor587@gmail.com",
            amount=250.00,
            invoice_number="BEC-2026-0124",
            days_overdue=2,
            status="paid_pending_confirmation",
            chase_count=1,
            po_number="PO-BEC-118",
            po_status="valid",
            po_expiry=(_today_iso() + timedelta(days=90)).date().isoformat(),
            procurement_email=None,
            procurement_contact_name=None,
            activity="Conference branding kit — Spring summit",
            contract_value=2500.00,
            billed_to_date=2500.00,
            vat_applicable=True,
            vat_number="GB889900112",
            specter_signal=_specter_signal(
                company_name="Bright Events Co",
                risk_classification="LOW",
                payment_velocity_trend="STABLE",
                payment_velocity_change_pct=1.7,
                company_health_score=80.0,
                cdd_status="PASSED",
                cdd_notes="Specter signals within acceptable parameters for automated pass at this amount.",
            ),
        )
    )

    # 10. HARD_BLOCK — large amount + HIGH Specter + velocity anomaly (new + > £8,000)
    atlas_uuid = _stable_uuid("demo:10:atlas")
    invoices.append(
        _scaffold(
            seed="demo:10:atlas",
            client_name="Atlas Infrastructure Group",
            contact_name="Ravi Khanna",
            email="ap@atlas-infrastructure-group.com",
            amount=15000.00,
            invoice_number="AIG-26-0044",
            days_overdue=38,
            status="overdue",
            chase_count=0,
            po_number=None,
            po_status="missing",
            po_expiry=None,
            procurement_email="procurement@atlas-infrastructure-group.com",
            procurement_contact_name="Lina Park",
            activity="One-off infrastructure assessment (single SOW)",
            contract_value=15000.00,
            billed_to_date=15000.00,
            vat_applicable=True,
            vat_number="GB990011223",
            specter_signal=_specter_signal(
                company_name="Atlas Infrastructure Group",
                risk_classification="HIGH",
                payment_velocity_trend="DETERIORATING",
                payment_velocity_change_pct=-18.0,
                company_health_score=38.0,
                cdd_status="REQUIRES_REVIEW",
                cdd_notes="HIGH risk with invoice amount above £5,000 — enhanced review recommended.",
            ),
            aml_result=_atlas_aml_result(atlas_uuid),
        )
    )

    return invoices


def get_demo_invoices() -> List[Dict[str, Any]]:
    """Return a deep copy of the curated demo set so callers can mutate freely."""

    return copy.deepcopy(_demo_template())


# -----------------------------------------------------------------------------
# CSV helpers
# -----------------------------------------------------------------------------


def _coerce_float(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _coerce_int(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return value


def _coerce_bool(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "t"}:
        return True
    if s in {"0", "false", "no", "n", "f"}:
        return False
    return value


_NUMERIC_COLS = {"amount", "amount_gbp", "contract_value", "billed_to_date", "months_since_last_invoice"}
_INT_COLS = {"chase_count", "days_overdue"}
_BOOL_COLS = {"po_required", "vat_applicable", "dormant_client_return"}


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, raw in row.items():
        if raw is None:
            continue
        if isinstance(raw, str) and raw.strip() == "":
            continue
        if key in _NUMERIC_COLS:
            normalized[key] = _coerce_float(raw)
        elif key in _INT_COLS:
            normalized[key] = _coerce_int(raw) or 0
        elif key in _BOOL_COLS:
            normalized[key] = _coerce_bool(raw)
        else:
            normalized[key] = raw if not isinstance(raw, str) else raw.strip()
    if "currency" not in normalized:
        normalized["currency"] = "GBP"
    if "status" not in normalized:
        normalized["status"] = "overdue"
    if "chase_count" not in normalized:
        normalized["chase_count"] = 0
    if "amount_gbp" not in normalized and "amount" in normalized:
        normalized["amount_gbp"] = normalized["amount"]
    return normalized


def load_invoices_from_csv(path: Path) -> List[Dict[str, Any]]:
    """Parse a CSV file from disk into normalized invoice dicts."""

    with Path(path).open("r", newline="", encoding="utf-8") as fh:
        return load_invoices_from_csv_text(fh.read())


def load_invoices_from_csv_text(text: str) -> List[Dict[str, Any]]:
    """Parse CSV text into normalized invoice dicts (lenient — extra columns are kept)."""

    if not text or not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict[str, Any]] = []
    for raw in reader:
        if not any((v or "").strip() for v in raw.values()):
            continue
        rows.append(_normalize_row(raw))
    return rows


def csv_template_text() -> str:
    """Return CSV with header + a single example row covering every recognised column."""

    example: Dict[str, Any] = {
        "invoice_id": "INV-001",
        "client_name": "Acme Ltd",
        "contact_name": "Pat Finance",
        "email": "ap@acme.com",
        "amount": "1250.00",
        "currency": "GBP",
        "invoice_number": "INV-001",
        "days_overdue": "35",
        "status": "overdue",
        "chase_count": "0",
        "po_number": "PO-9001",
        "po_status": "valid",
        "po_expiry": (_today_iso() + timedelta(days=60)).date().isoformat(),
        "procurement_email": "procurement@acme.com",
        "procurement_contact_name": "Sam Procurement",
        "activity": "Quarterly retainer — accounting services",
        "contract_value": "12000.00",
        "billed_to_date": "3000.00",
        "vat_applicable": "true",
        "vat_number": "GB123456789",
        "hold_reason": "",
        "months_since_last_invoice": "2",
        "dormant_client_return": "false",
        "prior_procurement_email": "",
    }
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS))
    writer.writeheader()
    writer.writerow({k: example.get(k, "") for k in CSV_COLUMNS})
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Stats aggregator
# -----------------------------------------------------------------------------


_AT_RISK_TIERS = {"ESCALATE", "HARD_BLOCK"}
_TERMINAL_STATUSES = {"paid", "cancelled", "written_off"}
_PAID_PENDING_STATUSES = {"paid_pending", "paid_pending_confirmation"}
_READY_STATUSES = {"outstanding", "ready"}


def _amount_of(invoice: Dict[str, Any]) -> float:
    raw = invoice.get("amount_gbp", invoice.get("amount", 0.0))
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _confidence_of(invoice: Dict[str, Any]) -> Optional[float]:
    draft = invoice.get("draft") or {}
    score = draft.get("confidence_score")
    try:
        return float(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def get_invoice_stats(invoices: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute portfolio-level statistics from the live invoice list.

    Returns counts and totals for the dashboard plus an average confidence score
    over invoices that have a draft.
    """

    total_count = 0
    total_value = 0.0
    at_risk_count = 0
    at_risk_value = 0.0
    actioned_count = 0
    auto_actioned_count = 0
    escalated_count = 0
    hard_blocked_count = 0
    aml_flagged_count = 0
    sar_considerations = 0
    paid_count = 0
    paid_value = 0.0
    ready_count = 0
    late_payment_interest_total = 0.0
    confidence_scores: List[float] = []

    for inv in invoices:
        total_count += 1
        amount = _amount_of(inv)
        total_value += amount

        tier = str(inv.get("autonomy_tier") or "").upper()
        status = str(inv.get("status") or "").lower()
        aml_result = inv.get("aml_result") or {}

        if tier in _AT_RISK_TIERS:
            at_risk_count += 1
            at_risk_value += amount
        if tier == "AUTO" and inv.get("processed_this_session"):
            auto_actioned_count += 1
        if tier == "ESCALATE":
            escalated_count += 1
        if tier == "HARD_BLOCK":
            hard_blocked_count += 1

        if inv.get("processed_this_session"):
            actioned_count += 1

        if aml_result.get("hard_block_required") or status == "aml_flagged":
            aml_flagged_count += 1
        if aml_result.get("sar_consideration"):
            sar_considerations += 1

        if status in _PAID_PENDING_STATUSES or status == "paid":
            paid_count += 1
            paid_value += amount

        if status in _READY_STATUSES:
            ready_count += 1

        try:
            late_payment_interest_total += float(inv.get("late_payment_interest") or 0.0)
        except (TypeError, ValueError):
            pass

        score = _confidence_of(inv)
        if score is not None:
            confidence_scores.append(score)

    avg_confidence_score = (
        round(sum(confidence_scores) / len(confidence_scores), 2) if confidence_scores else None
    )

    return {
        "total_count": total_count,
        "total_value": round(total_value, 2),
        "at_risk_count": at_risk_count,
        "at_risk_value": round(at_risk_value, 2),
        "actioned_count": actioned_count,
        "auto_actioned_count": auto_actioned_count,
        "escalated_count": escalated_count,
        "hard_blocked_count": hard_blocked_count,
        "aml_flagged_count": aml_flagged_count,
        "sar_considerations": sar_considerations,
        "paid_count": paid_count,
        "paid_value": round(paid_value, 2),
        "ready_count": ready_count,
        "late_payment_interest_total": round(late_payment_interest_total, 2),
        "avg_confidence_score": avg_confidence_score,
    }
