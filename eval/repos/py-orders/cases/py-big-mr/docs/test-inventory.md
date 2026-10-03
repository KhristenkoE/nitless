# Test inventory

The automated tests by file, for the release audit trail; a parameterized test is listed once,
with its placeholders. Regenerate it when tests change. 85 tests are listed.

## `tests/api/test_admin.py` (6)

- test_admin_routes_reject_customers
- test_create_product
- test_create_product_with_duplicate_sku_returns_409
- test_create_coupon_normalises_code
- test_ship_paid_order
- test_ship_pending_order_returns_409

## `tests/api/test_admin_coupons.py` (8)

- test_create_coupon_returns_all_fields
- test_create_coupon_accepts_boundary_values
- test_create_coupon_rejects_invalid_payload
- test_create_coupon_with_existing_code_returns_409
- test_list_coupons_uses_default_page
- test_list_coupons_pages_newest_first
- test_list_coupons_rejects_invalid_paging
- test_list_coupons_requires_admin

## `tests/api/test_authentication.py` (5)

- test_invalid_credentials_return_401
- test_current_customer_id_returns_token_subject
- test_current_customer_id_rejects_tokens_without_customer
- test_require_admin_returns_admin_principal
- test_require_admin_rejects_customers

## `tests/api/test_health.py` (3)

- test_live
- test_ready_when_database_is_reachable
- test_ready_returns_503_when_database_is_down

## `tests/api/test_orders.py` (9)

- test_create_order_prices_items_and_records_event
- test_create_order_with_unknown_product_returns_404
- test_create_order_rejects_duplicate_product_lines
- test_create_order_with_inactive_product_returns_409
- test_create_order_with_coupon_applies_discount
- test_create_order_with_unknown_coupon_returns_404
- test_create_order_with_expired_coupon_returns_409
- test_list_orders_returns_only_own_orders
- test_get_order_of_another_customer_returns_404

## `tests/api/test_payments.py` (8)

- test_pay_order_captures_and_marks_order_paid
- test_pay_order_is_idempotent
- test_declined_payment_leaves_order_pending
- test_paying_a_paid_order_returns_409
- test_refund_requires_admin
- test_refund_refunds_remaining_amount
- test_refund_with_explicit_full_amount
- test_refund_amount_must_be_positive

## `tests/api/test_products.py` (4)

- test_list_products_hides_inactive
- test_get_product
- test_get_unknown_product_returns_404
- test_products_require_authentication

## `tests/services/test_auth.py` (9)

- test_can_access_customer
- test_issued_token_round_trips
- test_hand_built_token_is_accepted
- test_token_is_valid_before_ttl_elapses
- test_token_expires_once_ttl_elapses
- test_token_without_exp_claim_is_expired
- test_token_signed_with_another_secret_is_rejected
- test_token_with_tampered_payload_is_rejected
- test_malformed_token_is_rejected

## `tests/services/test_coupons_service.py` (6)

- test_is_redeemable
- test_get_by_code_is_case_insensitive
- test_get_by_code_returns_none_for_unknown_code
- test_create_coupon_stores_upper_case_code
- test_create_coupon_rejects_duplicate_code_regardless_of_case
- test_list_coupons_pages_newest_first

## `tests/services/test_model_types.py` (7)

- test_bind_converts_aware_datetimes_to_utc
- test_datetimes_are_reloaded_as_utc
- test_flushing_a_naive_datetime_fails
- test_updated_at_follows_the_clock
- test_coupon_percent_off_is_checked
- test_product_check_constraints
- test_order_item_quantity_must_be_positive

## `tests/services/test_money.py` (3)

- test_percent_of_rounds_half_up
- test_format_cents
- test_split_evenly_preserves_total

## `tests/services/test_notifier.py` (5)

- test_deliver_posts_event
- test_deliver_signs_body_with_timestamp
- test_deliver_without_secret_sends_no_signature
- test_deliver_reports_failure_instead_of_raising
- test_deliver_reports_connection_errors_as_failure

## `tests/services/test_outbox_relay.py` (3)

- test_delivered_events_are_marked
- test_failed_delivery_is_retried_with_backoff
- test_event_is_dead_after_max_attempts

## `tests/services/test_outbox_scheduling.py` (6)

- test_backoff_doubles_up_to_one_hour
- test_only_due_events_are_relayed
- test_batch_size_limits_events_in_id_order
- test_returns_only_successful_deliveries
- test_retry_delay_grows_with_attempts
- test_event_dies_on_last_allowed_attempt

## `tests/services/test_pricing.py` (3)

- test_totals_without_discount_or_tax
- test_tax_is_charged_on_discounted_amount
- test_discount_cannot_exceed_subtotal
