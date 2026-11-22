# Phase 1 data dictionary

All entities and records are fictional. Each CSV has one header row, UTF-8 encoding without BOM, and LF line endings. Empty `failure_reason` represents no failure reason. Each scenario is a separate three-table dataset, with one completed payment attempt per payment row. Do not combine scenario folders into a single comparison.

## payments.csv

| Field | Representation | Meaning and clean constraint |
|---|---|---|
| `attempt_id` | String | Unique, nonempty synthetic key: scenario letter A or B and six digits; each clean scenario has 20,000 keys. Dirty A deliberately repeats 20 keys once each. |
| `attempted_at` | ISO 8601 string | `YYYY-MM-DDTHH:MM:SS+05:30`, October 1–28, 2026 inclusive. Explicit fixed offset. Dirty A blanks 10 timestamps. |
| `merchant_id` | String | Foreign key to `merchants.merchant_id`, M01–M20. Dirty A substitutes M_ORPHAN on 10 other original records. |
| `payer_bank_id` | String | Foreign key to `banks.bank_id`, BANK_A–BANK_E. Payer/remitter bank for UPI; issuer for CARD. |
| `payment_method` | Enum | CARD or UPI. |
| `amount_paise` | Decimal integer text | Positive INR minor units. Generated uniformly over integers 100–500,000 inclusive (INR 1.00–5,000.00); validation requires a positive integer. Synthetic design assumption. |
| `currency` | Enum | INR only. |
| `status` | Enum | SUCCESS or FAILED; no pending attempts or retries. |
| `failure_reason` | Enum or empty | Empty only for SUCCESS. FAILED has BANK_TIMEOUT, INSUFFICIENT_FUNDS, AUTHENTICATION_FAILED, or LIMIT_EXCEEDED. Internal synthetic labels, not bank response codes. |

The generator assigns exact outcome totals before shuffling. Amounts and time of day vary by seeded pseudorandom draws. Dates have equal period-wide integer quotas: the first four dates of each 14-day period receive 715 attempts each; the other ten receive 714 each. Time of day is independently drawn over 86,400 seconds and timestamps need not be unique or sorted within a date.

## merchants.csv

| Field | Representation | Meaning and clean constraint |
|---|---|---|
| `merchant_id` | String | Unique primary key M01–M20. |
| `merchant_name` | String | Fictional Merchant 01 through Fictional Merchant 20. |
| `category` | Enum | Cycles retail, grocery, dining, services in merchant-number order. |
| `region` | Enum | M01–M05 North; M06–M10 South; M11–M15 East; M16–M20 West. Describes merchant location, not payer location. |

## banks.csv

| Field | Representation | Meaning and clean constraint |
|---|---|---|
| `bank_id` | String | Unique primary key BANK_A–BANK_E. |
| `bank_name` | String | Fictional Bank A through Fictional Bank E. |

Many payment attempts reference one merchant and one bank. Both inner joins individually, and the combined join, preserve 20,000 clean rows. No hidden order, customer, settlement, or retry keys exist.

The generation manifest records profile `synthetic-payments-phase1-v1`, schema and generator versions `1.0.0`, seed, row counts, SHA-256 content hashes, encoding, timestamp offset, and amount/date configuration. Defect IDs and expected analytical answers appear only in evaluation files.
