# 🤖 AI review of main..case/py-coupon-checkout

**Verdict:** 🔴 Needs changes · 🟠 1 major

The wiring is clean and fits the project: the code goes through the repository, uses the domain errors and clock.utcnow(), writes to the outbox, and has API tests for the happy path and both error paths. There is one real bug in how the discount is calculated. `percent_off` is a whole percent, but it is passed to `percent_of`, which expects basis points, so customers get about 1/100 of the discount they should. The new test is too loose to catch this.

## 🔍 Findings

### 🟠 Major

🟠 **app/services/orders.py:59** · major · `correctness` — The discount is 100× too small because `coupon.percent_off` (a whole percent, 1–100) is passed to `percent_of`, which expects basis points.

`percent_of` divides by 10_000 ("basis_points / 10_000 of amount_cents"). A SPRING15 coupon on a $50.00 subtotal comes out as 8 cents instead of $7.50, so every coupon order is overcharged, and the CRM gets the wrong `discount_cents` in the `order.created` payload. The new test only checks `discount_cents > 0`, so it passes with the wrong value.

💡 **Suggestion:** Use `percent_of(subtotal_cents, coupon.percent_off * 100)`, and make the test assert the exact numbers: `discount_cents == 750` and `total_cents == 4250`.

<details><summary>📎 Evidence (4)</summary>

- callee: `app/core/money.py:10-16` — percent_of(amount_cents, basis_points) divides by BPS_DENOMINATOR
- sibling: `app/schemas/coupon.py:8` — percent_off: whole percent, e.g. 15 for 15% off
- callee: `app/models/coupon.py:11` — CheckConstraint percent_off BETWEEN 1 AND 100
- diff: `tests/api/test_orders.py:68` — asserts only discount_cents > 0

</details>

🎯 Confidence: 95%

---

<sub>✅ ok · 🧠 strong `claude-opus-5-5`, fast `claude-haiku-4-5`, verifier `claude-opus-5-5` · 🔢 42,895 prompt / 3,114 completion tokens · 💸 $0.1885 · ⏱ 86.3 s · nitless 0.1.0</sub>
