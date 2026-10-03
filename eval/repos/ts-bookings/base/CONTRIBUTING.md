# Contributing

Thanks for helping out! A few rules keep the codebase predictable.

## Workflow

- Branch from `main`, keep merge requests small and focused (one feature or fix).
- Title your MR in the imperative ("Add room search", not "Added room search").
- `npm run lint` and `npm test` must pass before review.
- Add or update tests for behaviour you change.

## Server rules

1. **Validate every request body and query string.** Each endpoint that accepts a
   body or query parameters must declare a zod schema in `server/src/schemas/` and
   wire it with `validateBody(...)` / `validateQuery(...)` in `routes.ts`.
   Controllers must never read an unvalidated `req.body` / `req.query`.
2. **Migrations are append-only.** Add a new numbered file in `server/migrations/`;
   never edit a migration that has been merged.
3. Money is always integer minor units (`...Cents`) plus a currency code. No floats
   in persisted amounts.

## Web rules

1. **List keys come from data.** Every element rendered from a list needs a stable
   `key` derived from the data (an id, a date string, ...). Never use the array
   index as a key, even for lists that "never reorder".
2. **Feature flags are read via `flags.isEnabled()` only** (`web/src/lib/flags.ts`).
   Do not read `import.meta.env.VITE_FLAGS` or hard-code flag checks elsewhere.
3. User-visible dates go through the helpers in `web/src/lib/format.ts` so they
   render consistently.

## Style

Prettier and ESLint configs live in the repo root; do not reformat unrelated code
in a feature MR.
