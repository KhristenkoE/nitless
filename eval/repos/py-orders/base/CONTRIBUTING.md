# Contributing

## Workflow

1. Branch from `main`, name it `<ticket>-short-description` (e.g. `ORD-231-coupon-codes`).
2. Keep MRs small and focused; one story per MR.
3. `ruff check . && ruff format --check . && mypy app && pytest` must pass before review.
4. At least one approval from the orders team is required to merge.

## Rules

- **Every new endpoint needs a test in `tests/api`.** At minimum the happy path and one
  error path. Service-level unit tests do not replace this.
- **Public API responses use schemas from `app/schemas`, never ORM objects.** Declare the
  schema as `response_model` or as the endpoint's return annotation.
- **Migrations are never edited after they are merged.** If a merged migration is wrong,
  add a new revision that fixes it. Every model change ships with a migration in the
  same MR.
- **Breaking changes to response schemas need a heads-up in #orders-api** one sprint
  before they are merged; prefer adding fields over renaming or removing them.
- **Secrets never go into `config.py` defaults** other than obviously fake dev values.

## Tests

- `tests/api` uses the FastAPI `TestClient` with an in-memory SQLite database
  (see `tests/conftest.py`). Use the `customer_client` / `admin_client` fixtures.
- Prefer the factories in `conftest.py` over building ORM objects by hand.

## Commit messages

Imperative mood, reference the ticket: `ORD-231: apply coupon codes at checkout`.
