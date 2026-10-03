# Changelog

All notable changes to inventory-service.

## 0.10.0 — 2026-10-05

### Added
- `POST /api/v1/products/{id}/stock/shipments` books shipments that bypass reservations (INV-221).
- `POST /api/v1/products/{id}/discontinue` discontinues a product and writes off unreserved stock (INV-198).
- `POST /api/v1/reservations/{id}/partial-release` gives back part of a reservation (INV-244).
- The reservation expiry job logs one summary line per run (INV-263).

### Changed
- The project is licensed under Apache-2.0; every source file carries the license header.

### Documentation
- Generated API reference in `docs/reference.md`.

## 0.9.0 — 2026-09-10

### Added
- Reservations with automatic expiry.
- Stock receipts and adjustments recorded as stock movements.
