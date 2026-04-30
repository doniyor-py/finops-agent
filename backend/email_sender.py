"""
Finoks — Email dispatch via configurable provider (Gmail SMTP or Resend).

Caller (``agent.run_agent_tick``) only invokes this for AUTO sends and approved
ESCALATIONs that have already passed Finoks pre-send verification. No fake
third-party verifier names appear in any template.

Environment configuration:

* ``EMAIL_PROVIDER`` — ``gmail`` or ``resend``. If unset, the function picks
  ``gmail`` when GMAIL credentials are present, otherwise ``resend`` when an
  API key is present, otherwise raises :class:`NotImplementedError` so the
  caller falls back to the stubbed behaviour.

* Gmail SMTP: ``GMAIL_USER`` (the sending Gmail address), ``GMAIL_APP_PASSWORD``
  (a 16-character Google App Password, NOT the account password — see
  https://myaccount.google.com/apppasswords). Optional ``GMAIL_FROM_NAME``.

* Resend: ``RESEND_API_KEY`` and ``RESEND_FROM`` (verified sender).
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, Optional

_WHITESPACE_RE = re.compile(r"\s+")

logger = logging.getLogger(__name__)


def send_chase_email(
    to_address: str,
    subject: str,
    body_text: str,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch a chase email via the configured provider.

    Args:
        to_address: Recipient email (already routed to AP or procurement by the agent).
        subject: Email subject (already drafted + verified upstream).
        body_text: Plain-text body.
        provider: Optional override for ``EMAIL_PROVIDER`` env var.

    Returns:
        ``{status, provider, ...}`` for the audit trail. Never raises on
        recoverable runtime errors — the agent treats unexpected exceptions as
        suppressible warnings, but missing config raises ``NotImplementedError``
        so the caller logs a clear "stubbed" event.
    """

    if not to_address or "@" not in to_address:
        return {"status": "skipped", "reason": "missing or invalid recipient"}

    selected = (provider or os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    if not selected:
        if os.getenv("GMAIL_USER") and os.getenv("GMAIL_APP_PASSWORD"):
            selected = "gmail"
        elif os.getenv("RESEND_API_KEY"):
            selected = "resend"

    if selected == "gmail":
        return _send_gmail(to_address, subject, body_text)
    if selected == "resend":
        return _send_resend(to_address, subject, body_text)

    raise NotImplementedError(
        "No email provider configured. Set EMAIL_PROVIDER=gmail with "
        "GMAIL_USER + GMAIL_APP_PASSWORD, or EMAIL_PROVIDER=resend with "
        "RESEND_API_KEY (and a verified RESEND_FROM)."
    )


# -----------------------------------------------------------------------------
# Gmail SMTP
# -----------------------------------------------------------------------------


def _send_gmail(to_address: str, subject: str, body_text: str) -> Dict[str, Any]:
    user = (os.getenv("GMAIL_USER") or "").strip()
    # Google prints App Passwords as "abcd efgh ijkl mnop" for readability;
    # the actual credential is a 16-char string with no whitespace, so strip
    # every space/tab the user pasted in.
    raw_password = os.getenv("GMAIL_APP_PASSWORD") or ""
    password = _WHITESPACE_RE.sub("", raw_password)
    if not user or not password:
        raise NotImplementedError(
            "Gmail provider selected but GMAIL_USER / GMAIL_APP_PASSWORD are missing."
        )

    from_name = (os.getenv("GMAIL_FROM_NAME") or "Finoks").strip()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{user}>" if from_name else user
    msg["To"] = to_address
    msg["Reply-To"] = user
    msg.set_content(body_text)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("Gmail SMTP auth failed: %s", exc)
        return {
            "status": "error",
            "provider": "gmail",
            "error": "auth_failed",
            "detail": str(exc),
            "to": to_address,
        }
    except smtplib.SMTPException as exc:
        logger.warning("Gmail SMTP error: %s", exc)
        return {
            "status": "error",
            "provider": "gmail",
            "error": "smtp_error",
            "detail": str(exc),
            "to": to_address,
        }
    except OSError as exc:  # network / DNS issues
        logger.warning("Gmail SMTP network error: %s", exc)
        return {
            "status": "error",
            "provider": "gmail",
            "error": "network_error",
            "detail": str(exc),
            "to": to_address,
        }

    logger.info("Gmail SMTP delivered → %s (subject=%r)", to_address, subject)
    return {
        "status": "sent",
        "provider": "gmail",
        "to": to_address,
        "from": user,
    }


# -----------------------------------------------------------------------------
# Resend (HTTP API)
# -----------------------------------------------------------------------------


def _send_resend(to_address: str, subject: str, body_text: str) -> Dict[str, Any]:
    try:
        import resend  # type: ignore
    except ImportError as exc:  # pragma: no cover — documented setup step
        raise NotImplementedError(
            "Resend provider selected but the `resend` package is not installed."
        ) from exc

    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise NotImplementedError("RESEND_API_KEY missing for Resend provider.")
    from_address = (os.getenv("RESEND_FROM") or "").strip()
    if not from_address:
        raise NotImplementedError(
            "RESEND_FROM missing — Resend requires a verified sender domain."
        )

    resend.api_key = api_key
    try:
        result = resend.Emails.send(
            {
                "from": from_address,
                "to": [to_address],
                "subject": subject,
                "text": body_text,
            }
        )
    except Exception as exc:  # pragma: no cover — network / API error
        logger.warning("Resend error: %s", exc)
        return {
            "status": "error",
            "provider": "resend",
            "error": "api_error",
            "detail": str(exc),
            "to": to_address,
        }

    logger.info("Resend delivered → %s (id=%s)", to_address, result.get("id") if isinstance(result, dict) else "?")
    return {
        "status": "sent",
        "provider": "resend",
        "to": to_address,
        "from": from_address,
        "id": result.get("id") if isinstance(result, dict) else None,
    }
