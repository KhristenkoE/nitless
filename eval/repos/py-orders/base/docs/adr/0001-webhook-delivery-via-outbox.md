# ADR-0001: Webhook delivery via a transactional outbox; the notifier never raises

- Status: accepted
- Date: 2025-11-04
- Deciders: orders team

## Context

Until v0.6 webhooks to the warehouse and CRM were sent inline from the request
handler after the database commit. This caused two classes of incidents:

1. A slow or failing receiver turned a successful checkout into a 500 or a timeout,
   and clients retried the payment.
2. When the process died between commit and send, the event was lost for good.

## Decision

- Services never call the webhook notifier. They write an `OutboxEvent` row in the
  same transaction as the state change (`OutboxRepository.add`).
- A separate worker (`app/worker.py` -> `services/outbox_relay.py`) picks up due events
  and hands each one to `WebhookNotifier.deliver`.
- **`WebhookNotifier.deliver` never raises.** Any failure while building, signing or
  sending the request (HTTP errors, timeouts, connection errors, serialization bugs,
  anything) is caught with a broad `except Exception`, logged at `warning` level as
  `webhook_delivery_failed`, and reported by returning `False`.
- The relay treats `False` as a failed attempt: it increments `attempts` and schedules
  the next try with exponential backoff. After `outbox_max_attempts` the event is marked
  dead and `outbox_event_dead` is logged at `error` level; that log line is what pages
  on-call.

## Why swallow everything in the notifier

A single poisoned event must not abort the relay batch and block every event behind
it, and an individual delivery failure is an expected, retried condition rather than
an error. Retrying and alerting are the relay's job, so the notifier deliberately
converts every exception into a `False` result. The blind `except` is marked
`# noqa: BLE001` and must not be narrowed or turned into a re-raise.

## Consequences

- Delivery is at-least-once. Receivers deduplicate on the `X-Orders-Event-Id` header.
- Individual failures are only visible as warnings; dashboards track the dead-letter
  count instead.
- Webhook latency is bounded by the relay poll interval (2s by default).
