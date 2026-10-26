# Broker Hub — منصة إدارة الوساطة التأمينية

A production-shaped insurance-brokerage platform: one inbox for every inbound channel (WhatsApp, calls,
email), a sales board with hard per-rep isolation, the client file, the issuing pipeline, and a client
portal that never sees internal data. Arabic RTL is the primary design; English mirrors it.

```
backend/    FastAPI + SQLAlchemy 2 (async) + Celery + Alembic   → see backend/README.md (soon) and app/
frontend/   React 18 + TypeScript strict + Vite + Tailwind tokens
infra/      docker compose: postgres 16, redis, minio, api, worker, beat, nginx SPA
docs/       STATUS.md · runbook.md · decisions/ · ui-parity/ · api/openapi.json
.github/    ci.yml (lint · typecheck · tests · e2e · docker builds)
```

## Run it in three commands

```bash
cp infra/.env.example infra/.env                      # 1
docker compose -f infra/docker-compose.yml up -d --build   # 2 — migrates + creates the bucket on its own
docker compose -f infra/docker-compose.yml exec backend python -m app.seed   # 3 — fictitious demo data
```

Then open <http://localhost:5173> (API on <http://localhost:8000/docs>). The stack runs with
`INTEGRATIONS_DRIVER=sim`, so inbound WhatsApp messages and calls — including a playable voice note and a
call recording — can be produced from <http://localhost:8000/api/v1/dev/sim> without any vendor account.

### Without Docker

```bash
# API (SQLite needs nothing installed)
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && DATABASE_URL="sqlite+aiosqlite:///./dev.db" alembic upgrade head \
  && DATABASE_URL="sqlite+aiosqlite:///./dev.db" python -m app.seed \
  && DATABASE_URL="sqlite+aiosqlite:///./dev.db" uvicorn app.main:app --port 8000

# SPA (proxies /api to 127.0.0.1:8000 — see frontend/vite.config.ts)
cd frontend && npm ci && VITE_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

## Demo logins (seed data, all fictitious)

| Account | Password | Sees |
| --- | --- | --- |
| `sara.elsayed@brokerhub.test` (sales rep) | `Br0kerHub!2026` | only her own leads/clients, Kanban + isolation banner |
| `manager@brokerhub.test` | `Br0kerHub!2026` | the whole office: unassigned queue, rep workload, reassign |
| `cs@brokerhub.test` | `Br0kerHub!2026` | the unified inbox, no sales board |
| `admin@brokerhub.test` | `Br0kerHub!2026` | users, roles, feature flags |
| `owner.mantiq@company.test` | `Br0kerHub!2026` | client portal only — no internal notes, commissions, rep data or recordings |

The seed password is a single demo constant. Override it with `SEED_PASSWORD` before seeding any
environment you do not control (`SEED_PASSWORD='…' python -m app.seed`), and never expose these
accounts publicly — they all share one password by design so the review can switch roles fast.

## Checks

```bash
cd backend  && ruff check . && ruff format --check . && mypy app && pytest -q   # 114 tests on SQLite
cd backend  && coverage run -m pytest -q && coverage report && python scripts/check_core_coverage.py
cd frontend && npm run lint && npm run typecheck && npm test  # eslint(0 warn) · tsc · vitest (42)
cd frontend && npm run e2e                                    # Playwright + the 16 screenshots (needs a browser)
cd backend    && python scripts/export_openapi.py && python scripts/check_openapi_fresh.py
cd frontend   && npm run codegen:api                          # regenerate types from docs/api/openapi.json
```

Ops surfaces: `GET /healthz`, `GET /readyz`, `GET /metrics` (Prometheus; token-gated outside
development — `docs/decisions/011-monitoring-and-mailpit.md`), and `GET /api/v1/dev/sim` as the
in-process simulator panel. Exports are scoped like the lists they mirror:
`POST /api/v1/exports/{requests|clients|insurer-performance}` returns an XLSX workbook and writes an
`audit_logs` row (ADR-010).

Frontend API types are generated (`openapi-typescript`) from the exported OpenAPI document — no
handwritten DTOs. Regenerate after any backend schema change; CI fails if the export is stale.

## Reading order

1. [`docs/STATUS.md`](docs/STATUS.md) — what is done, what is faked, what is left, per milestone.
2. [`docs/runbook.md`](docs/runbook.md) — operations: deploys, migrations, incidents, SLA behaviour.
3. [`docs/ui-parity/`](docs/ui-parity) — screen-by-screen deltas against the design sheets.
4. [`docs/decisions/`](docs/decisions) — ADRs, including why this architecture (001).
5. [`docs/api/openapi.json`](docs/api/openapi.json) — the REST contract.
