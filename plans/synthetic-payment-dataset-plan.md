# Synthetic payment dataset for the business-analyst demo

## Summary

Create an original synthetic dataset inspired by the strengths described in the [trade-offs research](../notes/payment_datasets_tradeoffs.md):

- **UPI examples:** bank, payment-method, and merchant-category segmentation.
- **Payment Funnel:** explicit outcomes and failure reasons.
- **Adyen:** payment identifiers, time fields, and transaction-level evidence.
- **SETTLEMENTIQ:** meaningful relational joins and deliberate data-quality failures.

Generate our own records; do not combine those sources or copy their rows. Target one hour for generation, validation, and documentation.

## Dataset structure

Use three tables. Three is slightly above the required minimum but supports both merchant and bank analysis without significant extra work.

| Table | Size | Fields |
|---|---:|---|
| `payments` | 20,000 attempts per scenario | `attempt_id`, `attempted_at`, `merchant_id`, `payer_bank_id`, `payment_method`, `amount_paise`, `currency`, `status`, `failure_reason` |
| `merchants` | 20 merchants | `merchant_id`, `merchant_name`, `category`, `region` |
| `banks` | 5 banks | `bank_id`, `bank_name` |

**Definitions and defaults:**

- One row represents one completed payment attempt, not an order or settlement.
- Outcomes are `SUCCESS` and `FAILED`; no pending attempts or retries in this version.
- Success rate is successful attempts divided by all valid attempts.
- Methods are `UPI` and `CARD`. The bank field means payer/remitter bank for UPI and issuer for cards.
- Success means the synthetic payment service recorded a successful attempt; it does not establish settlement.
- Failure reasons are internal synthetic labels: `BANK_TIMEOUT`, `INSUFFICIENT_FUNDS`, `AUTHENTICATION_FAILED`, and `LIMIT_EXCEEDED`. Successful attempts have no failure reason.
- Currency is INR; amounts are positive integer paise.
- Dates cover **1–28 October 2026**, with explicit `+05:30` timestamps. Compare October 1–14 against October 15–28.
- Use fictional merchant and bank names. Four merchant categories and four merchant regions support joins and segmentation; region describes the merchant, not the customer.
- Use a fixed generation seed, `42`.

## Two separate analytical scenarios

Keep scenarios in separate folders with the same schema. Load only one at a time so their explanations do not interfere.

### Scenario A: a real decline within a segment

Generate 10,000 attempts per period. Each of the five-bank × two-method combinations receives 1,000 attempts per period.

| Population | Baseline success rate | Comparison success rate |
|---|---:|---:|
| Bank B, UPI | 98% | 80% |
| Each other bank/method combination | 98% | 98% |
| **Overall** | **98%** | **96.2%** |

Keep merchant shares stable. Assign the 180 additional failures in Bank B’s UPI segment to `BANK_TIMEOUT`; preserve the baseline failure counts elsewhere.

**Expected explanation:** overall success falls by **1.8 percentage points**, entirely attributable to the Bank B/UPI segment. Timeout-labelled failures increase, but the data does not prove an infrastructure outage.

### Scenario B: a transaction-mix shift

Generate another 20,000 attempts, split equally across the periods. Keep bank shares equal and distribute merchants evenly.

| Method | Success rate in both periods | Baseline volume share | Comparison volume share |
|---|---:|---:|---:|
| CARD | 98% | 80% | 20% |
| UPI | 90% | 20% | 80% |
| **Overall** | **96.4% → 91.6%** | | |

**Expected explanation:** success falls by **4.8 percentage points**, although neither method deteriorates. More attempts use the lower-success method.

These percentages are deliberately constructed test conditions, not claims about real UPI or card performance.

Assign exact outcome counts before seeded shuffling. Random sampling must not make the expected answers drift.

## Failure demonstration and verification

Create a separate dirty copy of Scenario A:

- Append 20 exact duplicate rows.
- Remove timestamps from 10 other records.
- Replace merchant IDs on another 10 records with nonexistent IDs.
- Keep these defect groups separate and record their IDs in a test-only manifest.

The validator should report all three defect types and block the affected analysis rather than silently dropping records.

Verify:

- Unique attempt IDs and valid merchant/bank joins in clean data.
- Exactly 20,000 attempts per clean scenario and 10,000 per period.
- Exact numerators, denominators, rates, and segment counts shown above.
- No contradictory outcome/reason combinations.
- Merchant/bank joins preserve transaction counts.
- Scenario B has unchanged within-method rates.
- Dirty-copy counts match the injected defects.
- Regeneration with the same seed produces identical files.

Calculate expected answers from generated records using independent SQL, and compare them with the scenario specifications.

## Deliverables and boundaries

Deliver CSV files, a standard-library Python generator, reference SQL, machine-readable expected answers, a validation report, and a short data dictionary.

Keep expected answers and defect manifests outside the analyst’s queryable tables. The analyst should discover findings from payment records, not read the scenario’s answer.

Exclude settlement, refunds, fraud modelling, customer identities, external downloads, and access-control simulation from this one-hour package. The data-quality scenario satisfies the brief’s requirement for at least one demonstrated failure.

This package supplies the data needed for multi-table queries, period comparisons, segmented charts, evidence-backed explanations, and failure handling. It does not itself implement the analyst application or prove performance on real payment data.
