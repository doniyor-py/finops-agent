"""
Finoks — AML-pattern signal detection for guardrails.

Surfaces hedged **patterns** for human escalation only — never conclusive laundering findings.

Embedded frameworks referenced in rationales:

- **POCA 2002** — suspicion / prohibited-act themes (especially **ss.327–329**, **s.330** SAR governance).
- **MLR 2017** — **Reg.28** CDD diligence, **Reg.19** ongoing monitoring.
- **FCA Financial Crime Guide (FCG)** — invoice / payment anomaly red-flag thinking.
- **NCA typologies** — structuring, layering, routing, identity-drift motifs.

Descriptions use hedged wording (“pattern consistent with…”, “signal suggesting…”).
Never “evidence/proof”; never instruct to file — only surface **consider** SAR framing for humans.

"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

AmlFlag = Dict[str, Any]
AmlResult = Dict[str, Any]

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

_SHELL_TERMS_RE = re.compile(r"\b(holdings|international|global|trading)\b", re.IGNORECASE)


def _amount_gbp(inv: dict) -> float:
    raw = inv.get("amount_gbp")
    if raw is None:
        raw = inv.get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _client_key(inv: dict) -> str:
    key = (
        inv.get("client_id")
        or inv.get("counterparty")
        or inv.get("counterpart")
        or inv.get("client_name")
        or ""
    )
    return str(key).strip().lower()


def _invoice_number(inv: dict) -> str:
    return str(inv.get("invoice_number") or inv.get("reference") or inv.get("invoice_ref") or "").strip()


def _vat(inv: dict) -> Optional[str]:
    v = inv.get("vat_number") or inv.get("vat") or inv.get("vat_no")
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip()


def _chase_count(inv: dict) -> int:
    try:
        return int(inv.get("chase_count") or 0)
    except (TypeError, ValueError):
        return 0


def _invoice_id(inv: dict) -> str:
    return str(inv.get("invoice_id") or inv.get("id") or "").strip()


def _procurement_email(inv: dict) -> str:
    return str(
        inv.get("procurement_email")
        or inv.get("supplier_email")
        or inv.get("billing_email_procurement")
        or ""
    ).strip().lower()


def _accounts_email(inv: dict) -> str:
    return str(
        inv.get("accounts_payable_email")
        or inv.get("ap_email")
        or inv.get("billing_email")
        or inv.get("email")
        or ""
    ).strip().lower()


def _contact_name(inv: dict, role: str) -> str:
    if role == "procurement":
        return str(
            inv.get("procurement_contact_name") or inv.get("buyer_contact_name") or ""
        ).strip().lower()
    return str(inv.get("accounts_contact_name") or inv.get("ap_contact_name") or "").strip().lower()


def _uk_vat_valid_gb_nine_digits(val: str) -> bool:
    """UK VAT heuristic: `GB` + exactly nine numeric digits after normalisation."""

    compact = "".join(ch for ch in val.upper().replace(" ", "") if ch not in "-/")
    if not compact.startswith("GB"):
        return False
    digits = "".join(ch for ch in compact[2:] if ch.isdigit())
    return len(digits) == 9


def _in_structuring_band(amount: float, threshold: float) -> bool:
    if threshold <= 0:
        return False
    return threshold * 0.85 <= amount < threshold


def _parse_email_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def _organisation_slug(hostname: str) -> str:
    labels = [p for p in hostname.split(".") if p]
    if len(labels) < 2:
        return hostname.lower()
    if ".".join(labels[-2:]).lower() in ("co.uk", "gov.uk", "org.uk", "ac.uk") and len(labels) >= 3:
        return labels[-3].lower()
    return labels[-2].lower()


def _same_org_relaxed(proc_host: str, ap_host: str) -> bool:
    """Same organisational slug → treat divergence as plausible TLD / DNS sibling only."""

    if proc_host == ap_host:
        return True
    slug_a = _organisation_slug(proc_host)
    slug_b = _organisation_slug(ap_host)
    return bool(slug_a and slug_a == slug_b)


def _routing_diff_more_than_probable_tld_only(proc_email: str, accounts_email_str: str) -> bool:
    proc_host = _parse_email_domain(proc_email)
    ap_host = _parse_email_domain(accounts_email_str)
    if not proc_host or not ap_host:
        return False
    if proc_host == ap_host:
        return False
    if _same_org_relaxed(proc_host, ap_host):
        return False
    return True


def _round_cluster_candidate(amount_gbp: float) -> bool:
    """Eligible if whole pounds ending …00 AND (multiple of £100 or £1000) per briefing."""

    cents = round(amount_gbp * 100)
    if cents < 10000 or cents % 100 != 0:
        return False
    pounds_int = cents // 100
    ending_00 = pounds_int % 100 == 0
    ending_000 = pounds_int % 1000 == 0
    return ending_00 or ending_000


def _within_10pct_span(amounts: List[float]) -> bool:
    positives = [a for a in amounts if a and a > 0]
    if len(positives) < 2:
        return True
    return (max(positives) / min(positives) - 1.0) <= 0.10 + 1e-9


def _invoice_in_band_set(in_band: List[dict], current: dict) -> bool:
    ids = {_invoice_id(x) for x in in_band}
    cid_curr = _invoice_id(current)
    if cid_curr and cid_curr in ids:
        return True
    return any(x is current for x in in_band)


def check_structuring(invoices: list, current_invoice: dict) -> List[AmlFlag]:
    """
    NCA typology cue: clustered invoices nominally beneath reference thresholds (+ MLR Reg.19 monitoring).

    GBP bands at **10 000 / 5 000 / 3 000 / 1 000** counting amounts in ``[0.85·T, T)``.

    Severity: **HIGH** for 2–3 clustered rows; **CRITICAL** once **≥4**.
    """

    thresholds = (10000.0, 5000.0, 3000.0, 1000.0)
    cid = _client_key(current_invoice)
    if not cid:
        return []

    peers = [i for i in invoices if _client_key(i) == cid]
    flags: List[AmlFlag] = []

    for t in thresholds:
        in_band = [i for i in peers if _in_structuring_band(_amount_gbp(i), t)]
        if len(in_band) < 2:
            continue
        if not _invoice_in_band_set(in_band, current_invoice):
            continue
        sev = "CRITICAL" if len(in_band) >= 4 else "HIGH"
        flags.append(
            {
                "check_name": "structuring_cluster",
                "severity": sev,
                "description": (
                    f"Pattern consistent with structuring-style clustering signal: "
                    f"{len(in_band)} invoices for this client occupy the band "
                    f"£{t * 0.85:,.2f}–£{t:,.2f} (exclusive of £{t:,.0f}); "
                    "signal suggesting deliberate sub-reference spacing (not proof of structuring) "
                    "(POCA 2002 thematic; MLR 2017 Reg.19 monitoring)."
                ),
                "framework_ref": "NCA Typology: structuring (POCA 2002 ss.327–329 thematic); MLR 2017 Reg.19",
                "portfolio_level": False,
            }
        )

    return flags


def check_identity_consistency(invoice: dict) -> List[AmlFlag]:
    """
    MLR 2017 **Reg.28** CDD cues on references, VAT morphology, shallow corporate naming.

    **MEDIUM** default; escalate to **HIGH** when GBP amount > £5 000 (reference / VAT).
    Shell-term cue with new relationship (>£5 000) emits **HIGH** directly.
    """

    flags: List[AmlFlag] = []
    amount = _amount_gbp(invoice)
    material_high = amount > 5000.0
    counterparty = str(
        invoice.get("counterparty")
        or invoice.get("counterpart")
        or invoice.get("client_name")
        or ""
    ).strip()

    inv_no = _invoice_number(invoice)
    if inv_no:
        tokens = [
            re.sub(r"[^a-z0-9]+", "", t) for t in re.findall(r"[A-Za-z0-9]{2,}", counterparty.lower())
        ]
        inv_norm = re.sub(r"[^a-z0-9]+", "", inv_no.lower())
        overlap = tokens and inv_norm and any(
            len(t) >= 2 and (t in inv_norm or inv_norm.startswith(t[: min(3, len(t))])) for t in tokens
        )
        if not overlap:
            flags.append(
                {
                    "check_name": "identity_reference_pattern",
                    "severity": "HIGH" if material_high else "MEDIUM",
                    "description": (
                        "Pattern consistent with inconsistent invoice vs entity textual cues "
                        "(Reg.28 CDD depth suggested)."
                    ),
                    "framework_ref": "MLR 2017 Reg.28 — CDD; FCG invoice anomalies",
                    "portfolio_level": False,
                }
            )

    vat_raw = _vat(invoice)
    if vat_raw is not None and vat_raw != "":
        if not _uk_vat_valid_gb_nine_digits(vat_raw):
            flags.append(
                {
                    "check_name": "identity_vat_format",
                    "severity": "HIGH" if material_high else "MEDIUM",
                    "description": (
                        "Signal suggesting VAT token shape diverges from expected UK-format GB plus "
                        "nine digits — verify Companies House VAT alignment."
                    ),
                    "framework_ref": "MLR 2017 Reg.28 — CDD",
                    "portfolio_level": False,
                }
            )

    if _SHELL_TERMS_RE.search(counterparty) and _chase_count(invoice) == 0 and amount > 5000.0:
        flags.append(
            {
                "check_name": "identity_shell_descriptor",
                "severity": "HIGH",
                "description": (
                    "Pattern consistent with shallow corporate wording in a newly onboarded debtor "
                    "plus material GBP exposure — consider deeper Reg.28 CDD."
                ),
                "framework_ref": "FCG / MLR 2017 Reg.28 — entity substantiation cues",
                "portfolio_level": False,
            }
        )

    return flags


def check_velocity_anomaly(invoices: list, current_invoice: dict) -> List[AmlFlag]:
    """
    **FCG** velocity anomalies: maiden high-value exposures and dormancy-contact drift.

    Emits **HIGH** severity cues when triggered (per brief).
    """

    flags: List[AmlFlag] = []
    cid = _client_key(current_invoice)
    if not cid:
        return flags

    curr_id = _invoice_id(current_invoice)
    prior_same = [
        i for i in invoices if _client_key(i) == cid and (not curr_id or _invoice_id(i) != curr_id)
    ]
    amount = _amount_gbp(current_invoice)

    if not prior_same and amount > 8000.0:
        flags.append(
            {
                "check_name": "velocity_new_relationship_large",
                "severity": "HIGH",
                "description": (
                    "Pattern consistent with maiden invoice above £8,000 with no observable AR lineage "
                    "for this counterparty — escalate onboarding vigilance."
                ),
                "framework_ref": "FCA FCG — unusual velocity",
                "portfolio_level": False,
            }
        )

    months_gap = current_invoice.get("months_since_last_invoice")
    try:
        months_f = float(months_gap) if months_gap is not None else 0.0
    except (TypeError, ValueError):
        months_f = 0.0

    prior_proc = str(current_invoice.get("prior_procurement_email") or "").strip().lower()
    proc_now = _procurement_email(current_invoice)
    dormant_flag = bool(current_invoice.get("dormant_client_return"))
    if (dormant_flag or months_f >= 12.0) and prior_proc and proc_now and prior_proc != proc_now:
        flags.append(
            {
                "check_name": "velocity_dormant_contact_change",
                "severity": "HIGH",
                "description": (
                    "Signal suggesting dormant / long-gap counterparty return with altered procurement "
                    "email — pattern consistent with mandate uncertainty; verify contacts."
                ),
                "framework_ref": "FCA FCG — dormancy & contact drift",
                "portfolio_level": False,
            }
        )

    return flags


def check_routing_anomaly(invoice: dict) -> List[AmlFlag]:
    """
    NCA layering / routing inconsistency **signals** between procurement and AP channels.

    **MEDIUM** severity when triggered.
    """

    flags: List[AmlFlag] = []
    proc_e = _procurement_email(invoice)
    ap_e = _accounts_email(invoice)

    if proc_e and ap_e and _routing_diff_more_than_probable_tld_only(proc_e, ap_e):
        flags.append(
            {
                "check_name": "routing_domain_divergence",
                "severity": "MEDIUM",
                "description": (
                    "Pattern consistent with procurement vs accounts domains diverging beyond "
                    "plausible same-organisation sibling TLDs — revisit payment-route assurance."
                ),
                "framework_ref": "NCA Typology: routing / layering (POCA thematic)",
                "portfolio_level": False,
            }
        )

    proc_host = _parse_email_domain(proc_e)
    ap_host = _parse_email_domain(ap_e)
    name_p = _contact_name(invoice, "procurement")
    name_a = _contact_name(invoice, "accounts")
    if proc_host and ap_host and proc_host == ap_host and name_p and name_a and name_p != name_a:
        flags.append(
            {
                "check_name": "routing_shared_domain_different_names",
                "severity": "MEDIUM",
                "description": (
                    "Signal suggesting identical email domain contacts with disparate human names "
                    "— pattern consistent with possible internal redirection or BEC uncertainty; "
                    "manual confirmation recommended."
                ),
                "framework_ref": "NCA Typology: identity-collusion heuristic",
                "portfolio_level": False,
            }
        )

    return flags


def check_round_number_clustering(invoices: list) -> List[AmlFlag]:
    """
    Portfolio NCA clustering: distinct counterparties posting round-aligned invoices within ±10 %.

    **CRITICAL** severity if **≥3** qualifying invoices spanning **≥3** clients.
    """

    rows: List[Tuple[str, float]] = []
    for inv in invoices:
        amt = _amount_gbp(inv)
        key = _client_key(inv)
        if not key or not _round_cluster_candidate(amt):
            continue
        rows.append((key, amt))

    if len(rows) < 3:
        return []

    rows.sort(key=lambda x: x[1])
    flags: List[AmlFlag] = []
    n = len(rows)
    for i in range(n):
        cluster: List[Tuple[str, float]] = []
        j = i
        while j < n:
            trial = cluster + [rows[j]]
            amts = [t[1] for t in trial]
            if _within_10pct_span(amts):
                cluster = trial
                j += 1
            else:
                break
        clients = {c for c, _ in cluster}
        if len(cluster) >= 3 and len(clients) >= 3:
            flags.append(
                {
                    "check_name": "portfolio_round_amount_cluster",
                    "severity": "CRITICAL",
                    "description": (
                        f"Pattern consistent with cross-portfolio round-amount alignment: "
                        f"{len(cluster)} invoices across {len(clients)} counterparties within 10% "
                        "value proximity — portfolio governance review suggested."
                    ),
                    "framework_ref": "NCA Typology: portfolio round-number clustering",
                    "portfolio_level": True,
                }
            )
            break

    return flags


def _merge_flags(*flag_lists: Sequence[AmlFlag]) -> List[AmlFlag]:
    out: List[AmlFlag] = []
    for fl in flag_lists:
        out.extend(fl)
    return out


def _highest_severity(flags: Sequence[AmlFlag]) -> str:
    best = "LOW"
    for f in flags:
        sev = str(f.get("severity") or "LOW").upper()
        if sev in SEVERITY_ORDER and SEVERITY_ORDER[sev] > SEVERITY_ORDER[best]:
            best = sev
    return best


def _framework_refs(flags: Sequence[AmlFlag]) -> List[str]:
    refs: List[str] = []
    seen: Set[str] = set()
    for f in flags:
        r = str(f.get("framework_ref") or "").strip()
        if r and r not in seen:
            seen.add(r)
            refs.append(r)
    return refs


def _human_review_note(flags: Sequence[AmlFlag], invoice_id: str) -> str:
    if not flags:
        return (
            "No AML-pattern flags were produced for human triage — continue MLR Reg.19-style monitoring cadence."
        )
    snippets = [str(f.get("description", "")) for f in flags[:4]]
    extra = ""
    if len(flags) > 4:
        extra = " Additional signals suppressed for brevity."
    bullets = " ".join(f"Signal: {s}" for s in snippets if s)
    return (
        f"Invoice {invoice_id} — human review warranted. {bullets}{extra} "
        "Consider SAR obligation under **POCA 2002 s.330** if suspicion crystallises — not an instruction "
        "to file a SAR."
    )


def run_aml_checks(invoice: dict, all_invoices: list) -> AmlResult:
    """
    Executes every detector and aggregates into ``AmlResult``.

    ``hard_block_required`` when any flag severity is **HIGH** or **CRITICAL**.

    ``sar_consideration`` when **≥2** total flags **and** at least **one CRITICAL**.
    """

    merged: Dict[str, dict] = {}
    for inv in list(all_invoices) + [invoice]:
        oid = inv.get("invoice_id") or id(inv)
        merged[str(oid)] = inv
    unified = list(merged.values())

    flags = _merge_flags(
        check_structuring(unified, invoice),
        check_identity_consistency(invoice),
        check_velocity_anomaly(unified, invoice),
        check_routing_anomaly(invoice),
        check_round_number_clustering(unified),
    )
    fid = _invoice_id(invoice) or "unknown"

    fc = len(flags)
    highest = _highest_severity(flags)
    hard_block = any(str(f.get("severity")).upper() in ("HIGH", "CRITICAL") for f in flags)
    critical_any = any(str(f.get("severity")).upper() == "CRITICAL" for f in flags)
    sar = fc >= 2 and critical_any

    return {
        "invoice_id": fid,
        "flags": flags,
        "flag_count": fc,
        "highest_severity": highest,
        "hard_block_required": hard_block,
        "framework_references": _framework_refs(flags),
        "human_review_note": _human_review_note(flags, fid),
        "sar_consideration": sar,
    }


def detect_aml_patterns(invoice: Dict[str, Any], specter_payload: Dict[str, Any]) -> List[str]:
    """
    Back-compat helper yielding stable textual codes drawn from AML checks plus optional Specter CDD linkage.
    """

    result = run_aml_checks(invoice, [invoice])
    codes = [str(f["check_name"]) for f in result["flags"] if f.get("check_name")]
    if isinstance(specter_payload, dict) and str(specter_payload.get("cdd_status")).upper() == "FAILED":
        codes.append("specter_cdd_failed")
    return sorted(set(codes))


def summarize_flags_for_ui(flags: List[str]) -> str:
    """Single-line synopsis when only abbreviated codes propagate to UI adapters."""

    if not flags:
        return "Pattern review: queue clear — MLR Reg.19 monitoring cadence may continue."
    return (
        "Pattern consistent with behaviours occasionally referenced across POCA 2002 ss.327–329 & s.330, "
        "MLR 2017 Reg.28/19 and FCG / NCA typologies — escalate for human adjudication "
        "(consider SAR obligation under POCA 2002 s.330)."
    )

