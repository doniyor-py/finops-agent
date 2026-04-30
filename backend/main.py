"""
Finoks — FastAPI application entrypoint.

Routes:

- Auth: ``POST /users/register``, ``POST /users/login``, ``GET /users/me``.
- Health: ``GET /health``.
- Agent (JWT-protected): config / status / invoices / events / load-demo / reset /
  add-invoice / csv-template / load-csv / per-invoice actions / simulate-payment.
- WebSocket: ``/ws/agent`` (unauthenticated — known limitation, documented in spec).

Lifespan:

- Initialise SQLite database (auth users only).
- Start an ``AsyncIOScheduler`` running ``run_agent_tick`` every 15 seconds.
- Wire :func:`agent.register_broadcaster` to the WebSocket :class:`ConnectionManager`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load `.env` BEFORE importing any module that reads env at import time
# (auth.py reads JWT_SECRET, specter_client.py reads SPECTER_API_KEY, etc.).
# python-dotenv ships with uvicorn[standard]; if it's missing we no-op so the
# app still boots when env vars are exported manually in the shell.
try:
    from dotenv import load_dotenv as _load_dotenv  # type: ignore

    _ENV_PATH = Path(__file__).resolve().parent / ".env"
    if _ENV_PATH.is_file():
        _load_dotenv(dotenv_path=_ENV_PATH, override=False)
except Exception:  # pragma: no cover — dotenv missing or unreadable
    pass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import agent
import mock_invoices
from auth import create_access_token, decode_token, hash_password, verify_password
from database import get_db, init_db
from models import User
from schemas import (
    AddInvoiceIn,
    AgentConfigUpdate,
    AmlOverrideIn,
    CsvLoadResult,
    GenericMessage,
    Token,
    UserCreate,
    UserLogin,
    UserOut,
)

logger = logging.getLogger("finoks")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("FINOKS_LOG_LEVEL", "INFO"))


# -----------------------------------------------------------------------------
# WebSocket connection manager
# -----------------------------------------------------------------------------


class ConnectionManager:
    """
    Tracks active WebSocket clients on ``/ws/agent`` and broadcasts JSON payloads.

    All sends are wrapped: a slow / dropped client is removed, never crashes the broadcaster.
    """

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast_json(self, payload: Dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections)
        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 — broadcaster never crashes
                logger.debug("WebSocket send failed; dropping connection", exc_info=True)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)


manager = ConnectionManager()


# -----------------------------------------------------------------------------
# Lifespan: DB init + scheduler + broadcaster wiring
# -----------------------------------------------------------------------------


_scheduler: Optional[AsyncIOScheduler] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialise DB, start scheduler, wire broadcaster."""

    try:
        init_db()
    except Exception:
        logger.exception("init_db failed at startup")

    agent.register_broadcaster(_broadcast_state)

    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        agent.run_agent_tick,
        "interval",
        seconds=15,
        id="finoks_agent_tick",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    agent.agent_running = True
    logger.info("Finoks scheduler started — tick every 15s")

    try:
        yield
    finally:
        agent.agent_running = False
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception:
                logger.exception("scheduler shutdown failed")


app = FastAPI(
    title="Finoks",
    description="Autonomous AR / Invoice Chasing Agent with Financial Guardrails",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("FINOKS_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _state_payload() -> Dict[str, Any]:
    """Snapshot suitable for ``GET /agent/status`` and WebSocket broadcasts."""

    invoices = list(agent.agent_invoices)
    aml_flagged = sum(1 for inv in invoices if str(inv.get("status") or "").lower() == "aml_flagged")
    awaiting_approval = sum(1 for inv in invoices if inv.get("awaiting_approval"))
    awaiting_review = sum(1 for inv in invoices if inv.get("awaiting_human_review"))
    paid_pending = sum(1 for inv in invoices if str(inv.get("status") or "").lower() == "paid_pending")
    auto_count = sum(1 for inv in invoices if inv.get("autonomy_tier") == "AUTO")
    escalate_count = sum(1 for inv in invoices if inv.get("autonomy_tier") == "ESCALATE")
    hard_block_count = sum(1 for inv in invoices if inv.get("autonomy_tier") == "HARD_BLOCK")

    portfolio_total = round(sum(float(i.get("amount_gbp") or i.get("amount") or 0.0) for i in invoices), 2)

    return {
        "running": agent.agent_running,
        "stats": {
            "invoice_count": len(invoices),
            "aml_flagged_count": aml_flagged,
            "awaiting_approval_count": awaiting_approval,
            "awaiting_human_review_count": awaiting_review,
            "paid_pending_count": paid_pending,
            "autonomy_distribution": {
                "AUTO": auto_count,
                "ESCALATE": escalate_count,
                "HARD_BLOCK": hard_block_count,
            },
            "portfolio_total_gbp": portfolio_total,
        },
        "session_stats": dict(agent.agent_session_stats),
        "autonomy_config": dict(agent.autonomy_config),
        "events": agent.agent_events[-200:],
        "invoices": invoices,
        "provider": {
            "email_provider": os.getenv("EMAIL_PROVIDER") or "unset",
            "specter_configured": bool(os.getenv("SPECTER_API_KEY") and os.getenv("SPECTER_API_URL")),
            "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        },
    }


async def _broadcast_state(_optional_extra: Optional[Dict[str, Any]] = None) -> None:
    """Broadcaster used by ``agent.register_broadcaster`` and per-state-change endpoints."""

    payload = {"type": "STATE_UPDATE", **_state_payload()}
    if _optional_extra:
        payload["meta"] = _optional_extra
    await manager.broadcast_json(payload)


def _find_invoice(invoice_id: str) -> Dict[str, Any]:
    for inv in agent.agent_invoices:
        if str(inv.get("invoice_id") or inv.get("id") or "") == invoice_id:
            return inv
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")


def _reset_session_stats() -> None:
    agent.agent_session_stats.update(
        {
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
    )


# -----------------------------------------------------------------------------
# Auth dependencies
# -----------------------------------------------------------------------------


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer_token(authorization)
    claims = decode_token(token) if token else None
    if not claims or "sub" not in claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")
    subject = claims["sub"]
    user: Optional[User] = None
    try:
        user_id = int(subject)
        user = db.get(User, user_id)
    except (TypeError, ValueError):
        user = db.query(User).filter(User.email == str(subject).lower()).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "finoks"}


# -----------------------------------------------------------------------------
# Auth routes
# -----------------------------------------------------------------------------


@app.post("/users/register", response_model=Token)
async def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    email = payload.email.lower().strip()
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=email, hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    db.refresh(user)
    return Token(access_token=create_access_token(str(user.id)))


@app.post("/users/login", response_model=Token)
async def login_user(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    return Token(access_token=create_access_token(str(user.id)))


@app.get("/users/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


# -----------------------------------------------------------------------------
# Agent routes
# -----------------------------------------------------------------------------


@app.get("/agent/config")
async def agent_config(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "autonomy_config": dict(agent.autonomy_config),
        "provider": {
            "email_provider": os.getenv("EMAIL_PROVIDER") or "unset",
            "specter_configured": bool(os.getenv("SPECTER_API_KEY") and os.getenv("SPECTER_API_URL")),
            "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        },
    }


@app.post("/agent/config")
async def update_agent_config(
    update: AgentConfigUpdate,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    allowed_modes = {"guided", "full_auto", "human_all"}
    payload = update.model_dump(exclude_unset=True)
    if "mode" in payload:
        if str(payload["mode"]).lower() not in allowed_modes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"mode must be one of {sorted(allowed_modes)}",
            )
        payload["mode"] = str(payload["mode"]).lower()
    if "threshold_gbp" in payload:
        try:
            payload["threshold_gbp"] = float(payload["threshold_gbp"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="threshold_gbp must be numeric"
            )
        if payload["threshold_gbp"] < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="threshold_gbp must be >= 0"
            )

    agent.autonomy_config.update(payload)
    agent._log_event("CONFIG_UPDATED", changes=payload, framing="Operator-initiated config change")
    await _broadcast_state({"reason": "config_updated"})
    return {"autonomy_config": dict(agent.autonomy_config)}


@app.get("/agent/status")
async def agent_status(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    payload = _state_payload()
    return {
        "running": payload["running"],
        "stats": payload["stats"],
        "session_stats": payload["session_stats"],
        "autonomy_config": payload["autonomy_config"],
        "provider": payload["provider"],
    }


@app.get("/agent/invoices")
async def agent_invoices(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {"invoices": list(agent.agent_invoices), "count": len(agent.agent_invoices)}


@app.get("/agent/events")
async def agent_events(
    _user: User = Depends(get_current_user),
    limit: int = 500,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 500), 5000))
    return {"events": agent.agent_events[-limit:], "total": len(agent.agent_events)}


@app.post("/agent/load-demo")
async def load_demo(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    invoices = mock_invoices.get_demo_invoices()
    agent.agent_invoices.clear()
    agent.agent_events.clear()
    _reset_session_stats()
    agent.agent_invoices.extend(invoices)

    for inv in agent.agent_invoices:
        if agent.autonomy_config.get("specter_enrichment", True) and not inv.get("specter_signal"):
            await agent.enrich_invoice_specter(inv)
    for inv in agent.agent_invoices:
        if agent.autonomy_config.get("aml_checks", True) and not inv.get("aml_result"):
            agent.run_aml_check_invoice(inv)

    agent._log_event("SYSTEM", message="Demo invoices loaded", count=len(invoices), source="load-demo")

    try:
        await agent.run_agent_tick()
    except Exception:
        logger.exception("First tick after load-demo failed")

    await _broadcast_state({"reason": "load_demo"})
    return {"loaded": len(invoices), "invoices": list(agent.agent_invoices)}


@app.post("/agent/reset")
async def reset_agent(_user: User = Depends(get_current_user)) -> GenericMessage:
    agent.agent_invoices.clear()
    agent.agent_events.clear()
    _reset_session_stats()
    try:
        from specter_client import clear_specter_cache

        clear_specter_cache()
    except Exception:
        logger.debug("specter cache clear skipped", exc_info=True)
    agent._log_event("SYSTEM", message="Agent state cleared", source="reset")
    await _broadcast_state({"reason": "reset"})
    return GenericMessage(message="Agent state reset")


@app.post("/agent/add-invoice")
async def add_invoice(
    payload: AddInvoiceIn,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    data = payload.model_dump()
    if not data.get("invoice_id"):
        raise HTTPException(status_code=400, detail="invoice_id is required")
    if any(str(i.get("invoice_id")) == str(data["invoice_id"]) for i in agent.agent_invoices):
        raise HTTPException(status_code=409, detail="invoice_id already exists")

    invoice: Dict[str, Any] = {k: v for k, v in data.items() if v is not None}
    invoice.setdefault("currency", "GBP")
    invoice.setdefault("status", "overdue")
    invoice.setdefault("chase_count", 0)

    agent.agent_invoices.append(invoice)

    if agent.autonomy_config.get("specter_enrichment", True) and not invoice.get("specter_signal"):
        await agent.enrich_invoice_specter(invoice)
    if agent.autonomy_config.get("aml_checks", True) and not invoice.get("aml_result"):
        agent.run_aml_check_invoice(invoice)

    agent._log_event("SYSTEM", message="Invoice added", invoice_id=invoice["invoice_id"], source="add-invoice")

    try:
        await agent.run_agent_tick()
    except Exception:
        logger.exception("Tick after add-invoice failed")

    await _broadcast_state({"reason": "invoice_added"})
    return {"invoice": invoice}


@app.get("/agent/csv-template")
async def csv_template(_user: User = Depends(get_current_user)) -> PlainTextResponse:
    return PlainTextResponse(
        content=mock_invoices.csv_template_text(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="finoks_invoices_template.csv"'},
    )


@app.post("/agent/load-csv", response_model=CsvLoadResult)
async def load_csv(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> CsvLoadResult:
    name = (file.filename or "").lower()
    if not (name.endswith(".csv") or (file.content_type or "").startswith("text/")):
        raise HTTPException(status_code=400, detail="Expected a CSV file upload")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    parsed = mock_invoices.load_invoices_from_csv_text(text)
    if not parsed:
        return CsvLoadResult(loaded=0, errors=["No valid invoice rows detected"], warnings=[], aml_flagged_count=0)

    errors: List[str] = []
    warnings: List[str] = []
    accepted: List[Dict[str, Any]] = []

    existing_ids = {str(i.get("invoice_id")) for i in agent.agent_invoices}
    for index, row in enumerate(parsed, start=2):  # +1 header, +1 1-indexed
        rid = str(row.get("invoice_id") or "").strip()
        if not rid:
            errors.append(f"Row {index}: missing invoice_id")
            continue
        if rid in existing_ids:
            warnings.append(f"Row {index}: invoice_id {rid} already loaded — skipped")
            continue
        try:
            amt = row.get("amount_gbp")
            if amt is not None and not isinstance(amt, (int, float)):
                errors.append(f"Row {index}: amount_gbp must be numeric")
                continue
        except Exception:
            errors.append(f"Row {index}: amount_gbp parse error")
            continue
        existing_ids.add(rid)
        accepted.append(row)

    for inv in accepted:
        agent.agent_invoices.append(inv)
        if agent.autonomy_config.get("specter_enrichment", True) and not inv.get("specter_signal"):
            await agent.enrich_invoice_specter(inv)
        if agent.autonomy_config.get("aml_checks", True) and not inv.get("aml_result"):
            agent.run_aml_check_invoice(inv)

    if accepted:
        try:
            await agent.run_agent_tick()
        except Exception:
            logger.exception("Tick after load-csv failed")

    aml_flagged_count = sum(
        1 for inv in accepted if str(inv.get("status") or "").lower() == "aml_flagged"
    )

    agent._log_event(
        "SYSTEM",
        message="CSV import complete",
        loaded=len(accepted),
        errors=len(errors),
        warnings=len(warnings),
        aml_flagged=aml_flagged_count,
        source="load-csv",
    )
    await _broadcast_state({"reason": "csv_loaded"})

    return CsvLoadResult(
        loaded=len(accepted),
        errors=errors,
        warnings=warnings,
        aml_flagged_count=aml_flagged_count,
    )


@app.post("/agent/invoices/{invoice_id}/mark-paid")
async def mark_paid(invoice_id: str, _user: User = Depends(get_current_user)) -> Dict[str, Any]:
    invoice = _find_invoice(invoice_id)
    invoice["status"] = "paid_pending_confirmation"
    invoice["processed_this_session"] = False
    invoice["awaiting_approval"] = False
    agent._log_event(
        "SYSTEM",
        message="Marked paid pending confirmation",
        invoice_id=invoice_id,
        source="mark-paid",
    )
    await _broadcast_state({"reason": "mark_paid", "invoice_id": invoice_id})
    return {"invoice": invoice}


@app.post("/agent/invoices/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: str, current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    invoice = _find_invoice(invoice_id)
    if invoice.get("autonomy_tier") == "HARD_BLOCK" or invoice.get("awaiting_human_review"):
        raise HTTPException(
            status_code=409,
            detail="Invoice is hard-blocked. Use /aml-override after review to unblock.",
        )
    invoice["awaiting_approval"] = False
    invoice["processed_this_session"] = False
    invoice["approved_by"] = current_user.email
    agent._log_event(
        "APPROVED_BY_USER",
        invoice_id=invoice_id,
        approver=current_user.email,
        framing="Human approved escalated draft for next-tick send",
    )
    await _broadcast_state({"reason": "approved", "invoice_id": invoice_id})
    return {"invoice": invoice}


@app.post("/agent/invoices/{invoice_id}/block")
async def block_invoice(
    invoice_id: str, current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    invoice = _find_invoice(invoice_id)
    invoice["awaiting_approval"] = False
    invoice["processed_this_session"] = True
    invoice["blocked_by"] = current_user.email
    agent._log_event(
        "BLOCKED_BY_USER",
        invoice_id=invoice_id,
        blocker=current_user.email,
        framing="Human blocked escalated draft — agent will skip this invoice",
    )
    await _broadcast_state({"reason": "blocked", "invoice_id": invoice_id})
    return {"invoice": invoice}


@app.post("/agent/invoices/{invoice_id}/aml-override")
async def aml_override(
    invoice_id: str,
    payload: AmlOverrideIn,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    invoice = _find_invoice(invoice_id)
    aml_result = invoice.get("aml_result") or {}
    if not (
        invoice.get("awaiting_human_review")
        or aml_result.get("hard_block_required")
        or str(invoice.get("status") or "").lower() == "aml_flagged"
    ):
        raise HTTPException(
            status_code=409, detail="Invoice is not under AML hard-block; override is not required"
        )
    invoice["aml_override"] = True
    invoice["aml_override_note"] = payload.review_note
    invoice["aml_override_reviewer"] = payload.reviewer_name
    invoice["aml_override_reviewer_user"] = current_user.email
    invoice["awaiting_human_review"] = False
    if str(invoice.get("status") or "").lower() == "aml_flagged":
        invoice["status"] = "overdue"
    invoice["processed_this_session"] = False
    if isinstance(invoice.get("aml_result"), dict):
        invoice["aml_result"] = {
            **invoice["aml_result"],
            "hard_block_required": False,
            "human_override": True,
        }
    agent._log_event(
        "AML_OVERRIDE",
        invoice_id=invoice_id,
        reviewer_name=payload.reviewer_name,
        reviewer_user=current_user.email,
        review_note=payload.review_note,
        framing=(
            "Human override after review — pattern signals retained for audit; "
            "consider SAR obligation under POCA 2002 s.330 if suspicion crystallises."
        ),
    )
    await _broadcast_state({"reason": "aml_override", "invoice_id": invoice_id})
    return {"invoice": invoice}


@app.post("/agent/simulate-payment")
async def simulate_payment(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eligible = [
        inv
        for inv in agent.agent_invoices
        if str(inv.get("status") or "").lower() not in {"paid", "paid_pending", "cancelled", "written_off"}
    ]
    if not eligible:
        raise HTTPException(status_code=404, detail="No eligible invoices to simulate payment for")
    invoice = random.choice(eligible)
    invoice["status"] = "paid_pending"
    invoice["processed_this_session"] = False
    agent._log_event(
        "SYSTEM",
        message="Simulated payment received",
        invoice_id=invoice.get("invoice_id"),
        source="simulate-payment",
    )
    await _broadcast_state({"reason": "simulate_payment", "invoice_id": invoice.get("invoice_id")})
    return {"invoice": invoice}


# -----------------------------------------------------------------------------
# WebSocket
# -----------------------------------------------------------------------------


@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket) -> None:
    """
    Unauthenticated WebSocket — known limitation. Streams agent state on connect, every tick, and every
    human / system state-change broadcast.
    """

    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "INITIAL_STATE", **_state_payload()})
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                logger.debug("WebSocket receive error suppressed", exc_info=True)
                break
    finally:
        await manager.disconnect(websocket)


def create_app() -> FastAPI:
    """Factory accessor for tests / ASGI runners."""

    return app
