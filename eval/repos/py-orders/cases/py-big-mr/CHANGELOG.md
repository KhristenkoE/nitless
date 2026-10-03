# Changelog

All notable changes to the orders service. Versions follow semantic versioning; dates are release dates.

## 0.15.0 — 2026-10-05

### Added
- Coupon codes at checkout: `OrderCreate.coupon_code` (case-insensitive); the discount is applied to the
  item subtotal before tax and `order.created` carries `discount_cents` and `coupon_id` (ORD-231).
- `GET /products/by-sku/{sku}` for SKU-based storefront URLs (ORD-301).
- Partial refunds: `RefundCreate.amount_cents` is optional and `payment.refunded` reports
  `fully_refunded` (ORD-340).
- Signed webhooks: set `ORDERS_WEBHOOK_SIGNING_SECRET` to send `X-Orders-Signature` with every
  delivery (ORD-352).
- Readiness probe `GET /health/ready` (OPS-88).

### Changed
- `relay_pending` is now `relay_pending_events` and `configure_logging` is now `setup_logging`.
- The project is licensed under Apache-2.0; every source file carries the license header.

### Documentation
- Generated API reference in `docs/reference.md`.

## 0.14.2 — 2026-09-14

### Fixed
- Outbox relay backs off exponentially (capped at one hour) instead of retrying every poll.

## 0.14.0 — 2026-08-31

### Added
- Back-office coupons: `POST /admin/coupons` and `GET /admin/coupons`.
- Order shipping from the back office (`POST /admin/orders/{id}/ship`).
