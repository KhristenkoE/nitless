# ADR 0001: Pessimistic row locks instead of optimistic locking for stock levels

- Status: Accepted
- Date: 2024-03-12
- Deciders: inventory team

## Context

A stock level (`stock_levels`, one row per product and warehouse) is the hottest row in the
system: during a sale, dozens of checkout requests per second reserve stock of the same SKU in
the same warehouse, while receipts, adjustments and the reservation expiry job write to it too.

We prototyped optimistic locking with a JPA `@Version` column. Under load tests about 30% of
reservations for a hot SKU failed with `OptimisticLockException`, and retrying them in the
service layer made latency worse and turned every call site into a retry loop.

## Decision

- `StockLevel` deliberately has **no `@Version` column**. Do not add one.
- Every code path that changes a stock level first acquires a row lock with
  `SELECT ... FOR UPDATE` through `StockLedger.lock(...)` / `StockLedger.lockOrCreate(...)`
  (backed by `StockLevelRepository.findForUpdate`), inside the service transaction, and only
  then reads and modifies the row. Concurrent writers queue on the row lock instead of failing.
- Once the lock is held, a check-then-write sequence on the locked row is safe; no extra
  re-read or version check is needed.
- Changes to the locked entity are flushed by JPA dirty checking at commit; there is no need
  to call `save()` on a locked `StockLevel`.
- When one transaction must lock more than one stock level, it locks them in a stable order
  (by warehouse code) so two transactions cannot deadlock.
- Plain reads that do not modify stock (e.g. `GET /products/{id}/stock`) use the non-locking
  finder methods.

## Consequences

- Correctness relies on every writer taking the row lock. A writer that reads a stock level
  through a non-locking finder and then modifies it can silently overwrite a concurrent change,
  because nothing (no version column) would detect the conflict.
- Hot SKUs are serialised at the database; throughput per SKU is bounded by lock hold time, so
  transactions that lock stock levels must stay short and must not call external systems.
