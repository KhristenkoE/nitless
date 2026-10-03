# Contributing

Thanks for working on inventory-service. Please read this before opening a merge request.

## Workflow

- Branch from `main` as `feature/<ticket>-short-name` or `fix/<ticket>-short-name`.
- Keep merge requests small and focused; one ticket per MR.
- Reference the ticket in the MR title, e.g. `INV-123: Add stock receipts endpoint`.
- `./mvnw verify` must pass locally (tests + Checkstyle) before you ask for review.

## API rules

1. All endpoints are versioned under `/api/v1`.
2. Controllers accept and return DTO records from `com.acme.inventory.api.dto`.
   **Never return JPA entities from a controller**, not even for internal endpoints:
   entities are not a stable contract and serialising them leaks internal columns.
3. Request bodies are validated with `jakarta.validation` annotations and `@Valid`.
4. Every new endpoint needs a `@WebMvcTest` in `src/test/java/.../api`.

## Database migrations

1. Schema changes go through Flyway migrations in `src/main/resources/db/migration`.
2. Migrations are additive. **Never modify an existing `V*.sql` file** once it is on `main`:
   it has already run in staging and production and Flyway will fail checksum validation.
   Add a new `V<next>__description.sql` instead.
3. Hibernate runs with `ddl-auto: validate`, so entity changes and migrations must land together.

## Tests

- Unit tests use JUnit 5 and Mockito; controller tests use `@WebMvcTest` with mocked services.
- Name tests after behaviour: `reserve_failsWhenNotEnoughStockAvailable`.

## Code style

Checkstyle enforces formatting (4-space indent, 120-column lines, no star imports).
