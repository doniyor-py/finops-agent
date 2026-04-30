"""
Finoks — Pydantic request/response schemas (API contracts).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Signup payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Login payload."""

    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Public user representation."""

    id: int
    email: EmailStr
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT access token response."""

    access_token: str
    token_type: str = "bearer"


class AgentConfigUpdate(BaseModel):
    """PATCH-style agent config update."""

    mode: Optional[str] = None
    threshold_gbp: Optional[float] = None
    specter_enrichment: Optional[bool] = None
    aml_checks: Optional[bool] = None
    uk_late_payment_act: Optional[bool] = None
    demo_redirect_enabled: Optional[bool] = None
    redirect_to: Optional[str] = None
    cc: Optional[str] = None


class AddInvoiceIn(BaseModel):
    """Append invoice payload (loose schema; only invoice_id required)."""

    invoice_id: str
    counterparty: Optional[str] = None
    amount_gbp: Optional[float] = None
    due_date: Optional[str] = None
    status: Optional[str] = "overdue"
    currency: Optional[str] = "GBP"

    model_config = {"extra": "allow"}


class AmlOverrideIn(BaseModel):
    """Body required for human override of an AML hard-block."""

    reviewer_name: str = Field(min_length=2, max_length=120)
    review_note: str = Field(min_length=4, max_length=2000)


class GenericMessage(BaseModel):
    """Simple acknowledgement payload."""

    ok: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None


class CsvLoadResult(BaseModel):
    """Result of CSV ingestion."""

    loaded: int
    errors: List[str] = []
    warnings: List[str] = []
    aml_flagged_count: int = 0


class InvoiceOut(BaseModel):
    """Invoice row for dashboard (placeholder)."""

    id: int

    class Config:
        from_attributes = True
