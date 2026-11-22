# Phase 3: Payment lifecycle and relational depth

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisite: [Phase 2](phase-02-realistic-payment-behavior.md)

## Goal and schema

Add purchase intent, retries, settlement and bank observations without changing the meaning of an attempt. Use a new lifecycle_v1 schema and preserve the earlier profiles. Target approximately 200,000 attempts, but report the actual count produced by order/retry rules rather than truncating an order to hit a row target.

| Table | Identity and relationship | Main additions |
|---|---|---|
| orders | order_id; many orders per merchant | merchant_id, created_at, amount_paise, currency |
| payments | attempt_id; many attempts per order | order_id, attempt_number, completed_at, processing_duration_ms, ingested_at; existing fields retained |
| merchants | merchant_id | Existing attributes retained |
| banks | bank_id | Existing fictional payer-bank dimension retained |
| payment_methods | payment_method | Label and documented role |
| failure_reasons | failure_reason | Label and category: technical, authentication, customer |
| settlements | settlement_id; at most one row per successful attempt | attempt_id, due_at, settled_at, settlement_status, gross_amount_paise |
| bank_health | bank_id + payment_method + observed_at | Five-minute observations of availability percentage and p95 latency |

Payment method and failure labels retain their Phase 1 spelling. Bank-health signals are separately generated observations, not columns containing the hidden incident answer.

## Lifecycle rules and metrics

- Generate orders during October 1-28. Set the observation cutoff to November 1, 2026 at 00:00:00+05:30.
- An initial attempt follows order creation. A failed attempt receives a retry with probability 0.30 after five minutes, up to three attempts total. Preserve amount and method; stop after the first success. No in-flight attempts are included in this version.
- Order conversion uses orders created in the selected window with at least 24 hours of observation before cutoff; count an order as paid if it has a success within 24 hours of creation. Keep longer-horizon success as a separately named metric, not a changed denominator.
- Attempt success uses completed attempts whose attempt time is within the requested window. Retries count as separate attempts, not separate orders.
- Settlement is per successful attempt, not a batch. Full gross amount is due 24 hours after successful completion. Settlement may be PENDING or SETTLED; no fees, partial settlement, refunds or reversals in this phase.
- Baseline settlement completes at due_at when observable by cutoff; otherwise it is PENDING. Late settlement is introduced in Phase 4.
- Settlement completion uses successful attempts due by cutoff; backlog includes due-but-unsettled attempts. Settled amounts cannot exceed the attempt amount.
- Match bank health to the attempt's containing five-minute interval. Never join attempts to every observation for their bank.

## Work sequence

1. Add versioned schema/data dictionary and method/reason reference tables.
2. Generate order-to-attempt chains and payment-to-settlement records using stable entity IDs and named random streams.
3. Generate bank-health time buckets and baseline latency with documented synthetic parameters.
4. Create independent SQL for attempt rate, 24-hour order conversion, retry recovery, settlement completion and backlog.
5. Include a small hand-checkable fixture with an initial failure followed by success and a successful but not-yet-due settlement.

## Acceptance and handoff

**Dataset gate:** all relationships validate; attempt numbers are consecutive; completed_at follows attempted_at; attempts match order amount/currency/merchant; at most one successful attempt per order; settlement exists only for successful attempts; temporal joins preserve row counts. SQL counts the two-attempt recovery fixture as one paid order, one successful attempt and one failed attempt.

**Analyst gate:** correctly distinguish attempt success, order conversion and settlement completion; aggregate before joining one-to-many tables; do not claim a pending/not-yet-due settlement is a failed payment.

Deliver the schema version, fixtures, lifecycle definitions, reference SQL and expected answers to Phase 4. Double capture and partial settlement remain excluded rather than implied by the data model.
