# Finoks

An autonomous AR/AP agent for UK SMEs. It chases late invoices, screens
counterparties for AML risk, applies UK Late Payment Act statutory interest,
and routes every action through a three-tier autonomy gate (`AUTO` /
`ESCALATE` / `HARD_BLOCK`).

## Stack

- **Backend**: FastAPI · SQLAlchemy 2 · SQLite · APScheduler · Anthropic
  (Claude) · httpx · python-jose · passlib/bcrypt · resend
- **Frontend**: React 18 · React Router 6 · Vite 5 · plain CSS
- **Compliance framing**: POCA 2002, MLR 2017, FCA FCG, NCA typologies, UK
  Late Payment of Commercial Debts (Interest) Act 1998

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# create your .env from the template and fill in secrets locally
cp .env.example .env
# edit .env with your editor

uvicorn main:app --reload --port 8000
```

The API serves on `http://localhost:8000`. WebSocket at `/ws/agent`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The app serves on `http://localhost:5173` and proxies API calls to the
backend.

## Environment variables

See [`backend/.env.example`](backend/.env.example) for the full list. Minimum
required for full functionality:

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Auth token signing |
| `ANTHROPIC_API_KEY` | Email drafting (template fallback if absent) |
| `SPECTER_API_KEY` + `SPECTER_API_URL` | Counterparty enrichment (mock fallback if absent) |
| `EMAIL_PROVIDER` | `gmail` or `resend` (stub if absent) |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` | Required if provider = gmail |
| `RESEND_API_KEY` + `RESEND_FROM` | Required if provider = resend |

## Repository layout

```
finoks/
├── backend/        FastAPI app, agent loop, AML detector, Specter client
├── frontend/       React 18 + Vite SPA
├── docs/           Spec & design docs
└── sample_invoices.csv
```

## Demo

After signing up and logging in, hit **Load Demo** on the `/agent` page to
seed 10 deterministic invoices that exercise every rule branch and autonomy
tier. The activity feed and pipeline stats bar update in real time over the
WebSocket.

## Security

- `.env` is gitignored — never commit live keys.
- If a key is ever pushed by mistake, **rotate it immediately** at the
  provider (Google App Passwords / Resend / Anthropic) — git history is
  forever.
