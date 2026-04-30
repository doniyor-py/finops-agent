"""
Finoks — Specter API client (httpx).

Enrichment runs on every invoice load for CDD (MLR 2017 Reg.28) inputs and autonomy hints.

Spector-shaped signal (``enrich_counterparty`` return):

- ``available`` (bool): True when Specter HTTP response was used.
- ``company_name``, ``risk_classification`` (LOW | MEDIUM | HIGH | FLAGGED),
  ``payment_velocity_trend``, ``payment_velocity_change_pct``, ``company_health_score``,
  ``cdd_status`` (PASSED | REQUIRES_REVIEW | FAILED), ``cdd_notes``,
  ``raw_specter_data``, ``enriched_at`` (ISO 8601 Z), ``mock`` (True if mocked).
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Mapping, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

RiskClassification = Literal["LOW", "MEDIUM", "HIGH", "FLAGGED"]
VelocityTrend = Literal["IMPROVING", "STABLE", "DETERIORATING", "UNKNOWN"]
AUTONOMY_AUTO = "AUTO"
AUTONOMY_ESCALATE = "ESCALATE"
AUTONOMY_HARD_BLOCK = "HARD_BLOCK"

_AMOUNT_THRESHOLD_GBP_HIGH_REVIEW = 5000.0

# Raw Specter fields only (cdd_status depends on invoice_amount → computed per call).
_specter_raw_cache: Dict[str, Dict[str, Any]] = {}


def _cache_key(company_name: str) -> str:
    return company_name.strip().lower()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _map_keys_from_json(body: Mapping[str, Any]) -> Tuple[RiskClassification, VelocityTrend, Optional[float], Optional[float]]:
    """Map flexible API keys to canonical fields."""

    risk_raw = (
        body.get("risk_classification")
        or body.get("riskClassification")
        or body.get("risk")
        or "MEDIUM"
    )
    vr = str(risk_raw).upper()
    if vr not in ("LOW", "MEDIUM", "HIGH", "FLAGGED"):
        vr = "MEDIUM"
    risk: RiskClassification = vr  # type: ignore[assignment]

    vel_raw = (
        body.get("payment_velocity_trend")
        or body.get("paymentVelocityTrend")
        or body.get("velocity_trend")
        or "UNKNOWN"
    )
    vv = str(vel_raw).upper()
    if vv not in ("IMPROVING", "STABLE", "DETERIORATING", "UNKNOWN"):
        vv = "UNKNOWN"
    velocity: VelocityTrend = vv  # type: ignore[assignment]

    change = body.get("payment_velocity_change_pct")
    if change is None:
        change = body.get("paymentVelocityChangePct")

    health = body.get("company_health_score")
    if health is None:
        health = body.get("companyHealthScore")

    try:
        change_f: Optional[float] = float(change) if change is not None else None
    except (TypeError, ValueError):
        change_f = None

    try:
        health_f: Optional[float] = float(health) if health is not None else None
    except (TypeError, ValueError):
        health_f = None

    if health_f is not None:
        health_f = max(0.0, min(100.0, health_f))

    return risk, velocity, change_f, health_f


def _cdd_status_and_notes(
    risk_classification: RiskClassification,
    payment_velocity_trend: VelocityTrend,
    invoice_amount: float,
) -> Tuple[Literal["PASSED", "REQUIRES_REVIEW", "FAILED"], str]:
    """
    Map Specter-style signals to CDD status (MLR 2017 Reg.28 awareness — not a legal conclusion).

    Rules:
        - FLAGGED → FAILED
        - HIGH + amount > 5000 → REQUIRES_REVIEW
        - MEDIUM + DETERIORATING → REQUIRES_REVIEW
        - else → PASSED
    """
    if risk_classification == "FLAGGED":
        return "FAILED", "Risk classification FLAGGED — CDD must not pass without human review (Reg.28)."

    if risk_classification == "HIGH" and invoice_amount > _AMOUNT_THRESHOLD_GBP_HIGH_REVIEW:
        return "REQUIRES_REVIEW", "HIGH risk with invoice amount above £5,000 — enhanced review recommended."

    if risk_classification == "MEDIUM" and payment_velocity_trend == "DETERIORATING":
        return "REQUIRES_REVIEW", "MEDIUM risk with deteriorating payment velocity — review payment behaviour."

    return "PASSED", "Specter signals within acceptable parameters for automated pass at this amount."


def _build_specter_signal(
    company_name: str,
    invoice_amount: float,
    *,
    available: bool,
    mock: bool,
    risk_classification: RiskClassification,
    payment_velocity_trend: VelocityTrend,
    payment_velocity_change_pct: Optional[float],
    company_health_score: Optional[float],
    raw_specter_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    cdd_status, cdd_notes = _cdd_status_and_notes(
        risk_classification, payment_velocity_trend, invoice_amount
    )
    return {
        "available": available,
        "company_name": company_name.strip(),
        "risk_classification": risk_classification,
        "payment_velocity_trend": payment_velocity_trend,
        "payment_velocity_change_pct": payment_velocity_change_pct,
        "company_health_score": company_health_score,
        "cdd_status": cdd_status,
        "cdd_notes": cdd_notes,
        "raw_specter_data": raw_specter_data,
        "enriched_at": _utc_iso(),
        "mock": mock,
    }


def _mock_raw_for_company(company_name: str) -> Dict[str, Any]:
    """
    Deterministic mock raw payload keyed by company name hash — varied demo personas.
    Ensures demo CSV rows can see PASSED, REQUIRES_REVIEW, and occasional FLAGGED.
    """

    normalized = company_name.strip().lower() or "unknown"
    h = int(hashlib.sha256(normalized.encode("utf-8")).hexdigest(), 16)
    bucket = h % 7

    if bucket == 0:
        return {
            "risk_classification": "FLAGGED",
            "payment_velocity_trend": "DETERIORATING",
            "payment_velocity_change_pct": -22.5,
            "company_health_score": 28.0,
        }
    if bucket == 1:
        return {
            "risk_classification": "HIGH",
            "payment_velocity_trend": "STABLE",
            "payment_velocity_change_pct": -2.1,
            "company_health_score": 52.0,
        }
    if bucket == 2:
        return {
            "risk_classification": "HIGH",
            "payment_velocity_trend": "IMPROVING",
            "payment_velocity_change_pct": 4.0,
            "company_health_score": 62.0,
        }
    if bucket == 3:
        return {
            "risk_classification": "MEDIUM",
            "payment_velocity_trend": "DETERIORATING",
            "payment_velocity_change_pct": -12.0,
            "company_health_score": 48.0,
        }
    if bucket == 4:
        return {
            "risk_classification": "MEDIUM",
            "payment_velocity_trend": "STABLE",
            "payment_velocity_change_pct": 0.5,
            "company_health_score": 71.0,
        }
    if bucket == 5:
        return {
            "risk_classification": "LOW",
            "payment_velocity_trend": "IMPROVING",
            "payment_velocity_change_pct": 8.3,
            "company_health_score": 88.0,
        }
    return {
        "risk_classification": "LOW",
        "payment_velocity_trend": "STABLE",
        "payment_velocity_change_pct": None,
        "company_health_score": 76.0,
    }


async def _http_fetch_raw(company_name: str, invoice_amount: float, base_url: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    POST {base}/enrich with JSON body. Returns normalized raw dict or None on failure.

    Adjust path/shape if your Specter deployment documents a different contract.
    """
    url = f"{base_url.rstrip('/')}/enrich"
    payload = {"company_name": company_name, "invoice_amount": invoice_amount}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, dict):
                return None
            risk, vel, chg, health = _map_keys_from_json(body)
            return {
                "risk_classification": risk,
                "payment_velocity_trend": vel,
                "payment_velocity_change_pct": chg,
                "company_health_score": health,
                "_response_body": body,
            }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.debug("Specter HTTP error: %s", exc)
        return None


def _materialize_from_raw(
    company_name: str,
    invoice_amount: float,
    raw: Dict[str, Any],
    *,
    available: bool,
    mock: bool,
) -> Dict[str, Any]:
    response_copy = raw.pop("_response_body", None)
    raw_specter: Optional[Dict[str, Any]] = None
    if isinstance(response_copy, dict):
        raw_specter = dict(response_copy)
    elif mock:
        raw_specter = {"source": "mock", "seed": _cache_key(company_name)}

    risk: RiskClassification = raw["risk_classification"]
    vel: VelocityTrend = raw["payment_velocity_trend"]
    chg: Optional[float] = raw.get("payment_velocity_change_pct")
    health: Optional[float] = raw.get("company_health_score")

    return _build_specter_signal(
        company_name,
        invoice_amount,
        available=available,
        mock=mock,
        risk_classification=risk,
        payment_velocity_trend=vel,
        payment_velocity_change_pct=chg,
        company_health_score=health,
        raw_specter_data=raw_specter,
    )


async def enrich_counterparty(company_name: str, invoice_amount: float) -> Dict[str, Any]:
    """
    Call Specter API to get counterparty intelligence.

    Returns a SpectorSignal-shaped dict::

        {
            "available": bool,
            "company_name": str,
            "risk_classification": "LOW" | "MEDIUM" | "HIGH" | "FLAGGED",
            "payment_velocity_trend": "IMPROVING" | "STABLE" | "DETERIORATING" | "UNKNOWN",
            "payment_velocity_change_pct": float | None,
            "company_health_score": float | None,
            "cdd_status": "PASSED" | "REQUIRES_REVIEW" | "FAILED",
            "cdd_notes": str,
            "raw_specter_data": dict | None,
            "enriched_at": str,
            "mock": bool,
        }

    Raw Specter fields are cached **per normalized company name**; ``cdd_status`` is recomputed each
    call from ``invoice_amount`` (HIGH above £5000 ⇒ REQUIRES_REVIEW).

    On missing credentials or HTTP failure: logs ``Specter unavailable — using mock enrichment``,
    ``mock=True``, deterministic personas by company-name hash (includes FLAGGED / REQUIRES_REVIEW).
    """
    if not company_name or not company_name.strip():
        empty_raw = _mock_raw_for_company("__empty__")
        logger.warning("Specter unavailable — using mock enrichment")
        sig = _materialize_from_raw("", invoice_amount, {**empty_raw}, available=False, mock=True)
        return sig

    key = _cache_key(company_name)
    cached_raw = _specter_raw_cache.get(key)

    if cached_raw is None:
        base_url = (os.getenv("SPECTER_API_URL") or "").strip()
        api_key = (os.getenv("SPECTER_API_KEY") or "").strip()

        if not base_url or not api_key:
            logger.warning("Specter unavailable — using mock enrichment")
            raw = _mock_raw_for_company(company_name)
            raw_for_cache = {k: v for k, v in raw.items()}
            raw_for_cache["_response_body"] = None
            _specter_raw_cache[key] = raw_for_cache
        else:
            fetched = await _http_fetch_raw(company_name, invoice_amount, base_url, api_key)
            if fetched is None:
                logger.warning("Specter unavailable — using mock enrichment")
                raw = _mock_raw_for_company(company_name)
                _specter_raw_cache[key] = {**raw, "_response_body": None}
            else:
                _specter_raw_cache[key] = fetched

        cached_raw = _specter_raw_cache[key]

    # Copy cached structural fields without mutating cache (cdd applies per-call amount).
    working = dict(cached_raw)
    mock_flag = "_response_body" not in working or working.get("_response_body") is None
    available = bool(working.get("_response_body"))

    # Reconstruct from normalized cache fields always (cdd depends on invoice_amount).
    normalized_cache = {
        "risk_classification": working["risk_classification"],
        "payment_velocity_trend": working["payment_velocity_trend"],
        "payment_velocity_change_pct": working.get("payment_velocity_change_pct"),
        "company_health_score": working.get("company_health_score"),
        "_response_body": working.get("_response_body"),
    }
    sig = _materialize_from_raw(
        company_name,
        invoice_amount,
        normalized_cache,
        available=available and not mock_flag,
        mock=mock_flag,
    )
    return sig


def get_autonomy_recommendation(specter_signal: Dict[str, Any], amount: float, threshold: float) -> str:
    """
    Returns ``AUTO`` | ``ESCALATE`` | ``HARD_BLOCK`` based on Specter signal + amount.

    HARD_BLOCK if: cdd_status FAILED
    ESCALATE if: cdd_status REQUIRES_REVIEW OR amount > threshold
    AUTO if: cdd_status PASSED AND amount <= threshold
    """
    cdd = str(specter_signal.get("cdd_status") or "").upper()
    if cdd == "FAILED":
        return AUTONOMY_HARD_BLOCK
    if cdd == "REQUIRES_REVIEW" or amount > threshold:
        return AUTONOMY_ESCALATE
    if cdd == "PASSED" and amount <= threshold:
        return AUTONOMY_AUTO
    return AUTONOMY_ESCALATE


async def fetch_specter_enrichment(
    counterparty_identifier: str,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compatibility wrapper calling ``enrich_counterparty(identifier, 0.0)``.

    When ``api_key`` / ``api_url`` are set, temporarily overrides ``SPECTER_*`` env vars,
    restores previous values afterward. Note: **cache is keyed by company name**; if this
    counterparty was enriched earlier, call :func:`clear_specter_cache` before switching credentials.
    """
    saved: Dict[str, Optional[str]] = {}
    try:
        if api_key is not None:
            saved["SPECTER_API_KEY"] = os.environ.get("SPECTER_API_KEY")
            os.environ["SPECTER_API_KEY"] = api_key
        if api_url is not None:
            saved["SPECTER_API_URL"] = os.environ.get("SPECTER_API_URL")
            os.environ["SPECTER_API_URL"] = api_url
        return await enrich_counterparty(counterparty_identifier, 0.0)
    finally:
        for var, previous in saved.items():
            if previous is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = previous



def specter_status_label(payload: Dict[str, Any]) -> str:
    """
    UI label per product UX: mock/offline enrichment shows UNAVAILABLE live feed.
    """

    if payload.get("mock"):
        return "Specter: UNAVAILABLE"
    risk = payload.get("risk_classification")
    if payload.get("available") and risk:
        return f"Specter: {risk}"
    return "Specter: UNAVAILABLE"


def clear_specter_cache() -> None:
    """Testing / dev helper — session cache reset."""

    _specter_raw_cache.clear()
