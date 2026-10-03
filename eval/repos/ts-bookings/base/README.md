# Bookings

Book meeting rooms and appointment slots. The repository holds two packages:

| Package   | What                                              |
| --------- | ------------------------------------------------- |
| `server/` | Express API (`/api`), PostgreSQL, zod, pino        |
| `web/`    | React 18 + Vite client, TanStack Query for data    |

## Getting started

```sh
npm install
export DATABASE_URL=postgres://localhost/bookings   # also: PORT, LOG_LEVEL
psql "$DATABASE_URL" -f server/migrations/001_init.sql
npm run dev
```

Set `VITE_API_URL` for the web client if the API is not served from `/api` on the same origin.

## Server layout

```
server/src/
  routes.ts        URL -> middleware -> controller wiring
  controllers/     HTTP in/out only
  services/        business rules
  repositories/    SQL
  schemas/         zod schemas for request bodies and query strings
  middleware/      auth, validation
  lib/             shared helpers (db, time, logging, audit, ...)
```

Requests flow `routes -> controllers -> services -> repositories`. There is no DI
container: modules import each other directly and tests use `vi.mock`.

## Web layout

```
web/src/
  api/          API client and data hooks
  components/   presentational + small stateful components
  pages/        route-level components
  lib/          formatting, feature flags
```

## Domain notes

- All times are stored and transported as UTC ISO-8601 strings. Rooms are open
  08:00-20:00 UTC and bookable in 30-minute slots.
- Each room has a `maxDurationMinutes` limit for a single booking.
- Money is stored in integer minor units (`hourlyRateCents`) with an ISO currency code.

## Tests

`npm test` runs vitest in both packages.
