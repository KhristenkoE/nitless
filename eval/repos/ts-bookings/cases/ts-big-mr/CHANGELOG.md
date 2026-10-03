# Changelog

All notable changes to the bookings API and web client.

## 0.15.0 — 2026-10-05

### Added
- `GET /api/rooms/:roomId/bookings` is paginated with `page` / `pageSize` and reports the total in
  `X-Total-Count`.
- Weekly schedule panel on the room page for staff (flag `room-schedule`).
- Self check-in button on booking cards during the check-in window (flag `self-check-in`).
- "My bookings" is grouped by UTC day.
- Room updates and archiving are recorded in the audit trail.

### Changed
- `sendError` is now `sendErrorResponse`.
- The project is licensed under Apache-2.0; every source file carries the license header.

### Documentation
- Generated API reference in `docs/reference.md`.

## 0.14.0 — 2026-09-08

### Added
- Room availability grid with 30-minute slots.
- Booking cancellation from the "My bookings" page.
