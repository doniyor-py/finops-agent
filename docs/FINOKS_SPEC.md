# Finoks — Product & Technical Specification (Boilerplate)

## Product

**Finoks** is an autonomous invoice chasing agent that classifies payment risk, applies graduated response rules, detects AML-pattern signals, enriches counterparties via the **Specter** API, and escalates to humans at configurable thresholds.

Finoks is **not** a compliance system, SAR-filing tool, banking app, individual finance app, or memo/chat/export UI. The agent **flags patterns** — humans make compliance decisions.

### User-visible legal framing

- “Pattern consistent with MLR 2017 / NCA typologies — human review required”
- “Consider SAR obligation under POCA 2002 s.330”
- “CDD check (MLR 2017 Reg.28)”
- **Never**: “money laundering detected” or “SAR filed”

## Stack

- **Backend:** FastAPI + SQLAlchemy 2 + SQLite + APScheduler; Anthropic SDK; pandas; JWT (python-jose); passlib/bcrypt (bcrypt 4.0.1); resend 2.0.0; websockets 12.0; httpx (Specter).
- **Frontend:** React 18 + React Router 6 + Vite 5 — **plain CSS only** (no Tailwind or component libraries).

## Routes

| Path       | Purpose                                      |
|-----------|-----------------------------------------------|
| `/`       | Landing                                       |
| `/login`  | Login                                         |
| `/signup` | Signup                                        |
| `/agent`  | Protected agent dashboard — **post-login**   |

Always redirect authenticated users to **`/agent`**. Never `/individual` or `/business`.

## Non-negotiables

1. **Specter enrichment** runs on **every invoice load** (async). If the API is unavailable, show **Specter: UNAVAILABLE** — do not crash.
2. **Three-tier autonomy** (`auto` / `escalate` / `hard_block`) is enforced in `agent.py` **every tick**.
3. **AML pattern flags hard-block** the agent — **no email** until a human clears via **“Override after review”** (agent cannot override AML hard blocks).

## Environment variables

See `backend/.env.example`:  
`ANTHROPIC_API_KEY`, `JWT_SECRET`, `SPECTER_API_KEY`, `SPECTER_API_URL`,  
`GMAIL_USER`, `GMAIL_APP_PASSWORD`, `GMAIL_FROM_NAME`,  
`RESEND_API_KEY`, `RESEND_FROM`, `EMAIL_PROVIDER`, `DEMO_EMAIL`.

## WebSocket

`/ws/agent` is **documented as unauthenticated** — a known limitation for this phase.

## Repository layout

```
finoks/
├── backend/        # FastAPI app, agent, AML, Specter client, auth, DB
├── frontend/       # Vite React app
├── sample_invoices.csv
└── docs/FINOKS_SPEC.md
```

This document accompanies the scaffold; behavior is implemented in later phases.
