# py-orders

Orders and billing service for the storefront. It owns the order lifecycle
(placement, payment, shipping, refunds), the product catalogue prices used at
checkout, coupons, and the webhook feed consumed by the warehouse and CRM.

## Stack

- FastAPI + pydantic v2 for the HTTP layer
- SQLAlchemy 2.0 (sync) on PostgreSQL, migrations with Alembic
- structlog for JSON logs
- A background worker (`python -m app.worker`) relays outbox events to webhooks

## Layout

```
app/
  api/            FastAPI routers and request dependencies
  services/       business logic, one service per aggregate
  repositories/   SQLAlchemy queries
  models/         ORM models
  schemas/        pydantic request/response models
  core/           config, db, auth, logging, shared helpers
migrations/       Alembic revisions
tests/            pytest suite (tests/api hits the HTTP layer, tests/services is unit level)
docs/adr/         architecture decision records
```

## Running locally

```bash
uv sync --extra dev
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload
```

The worker is started separately:

```bash
python -m app.worker
```

## API

All endpoints except `/health/*` require a bearer token issued by the identity
service. Admin endpoints live under `/admin` and require an admin token.

Public API responses are always pydantic schemas from `app/schemas` (set via
`response_model` or the return annotation). ORM objects are never returned from
a router directly, so that adding a column never leaks it into the API.

List endpoints are paginated with `limit`/`offset` query parameters
(`limit` max 100) and return a `Page[...]` envelope.

## Webhooks

State changes are published as webhook events through a transactional outbox,
see [ADR-0001](docs/adr/0001-webhook-delivery-via-outbox.md).
