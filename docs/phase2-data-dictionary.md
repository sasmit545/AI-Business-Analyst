# Phase 2 data dictionary

Each selected fixture contains three tables. One payment row represents one completed payment attempt. It is not an order, settlement or retry chain. Join only within the selected schema. Identical attempt IDs across variants represent alternative fixture outcomes, not additional transactions.

## payments

| Column | Meaning and constraints |
|---|---|
| `attempt_id` | Unique within a fixture; `R` followed by eight digits. Primary key. |
| `attempted_at` | ISO 8601 timestamp with seconds and explicit `+05:30`; October 1-28, 2026. Use local date/hour for grouping. |
| `merchant_id` | Foreign key to `merchants.merchant_id`; M01-M20. |
| `payer_bank_id` | Foreign key to `banks.bank_id`; BANK_A-BANK_E. |
| `payment_method` | `CARD` or `UPI`. |
| `amount_paise` | Integer INR paise, inclusive range 1,000-10,000,000. Divide by 100 for rupees. |
| `currency` | `INR`. |
| `status` | `SUCCESS` or `FAILED`. |
| `failure_reason` | Empty string for success. On failure: `BANK_TIMEOUT`, `INSUFFICIENT_FUNDS`, `AUTHENTICATION_FAILED`, or `LIMIT_EXCEEDED`. |

## merchants

| Column | Meaning |
|---|---|
| `merchant_id` | Primary key, M01-M20. |
| `merchant_name` | Synthetic display name. |
| `category` | `retail`, `grocery`, `dining`, or `services`. |
| `region` | `North`, `South`, `East`, or `West`. |

## banks

| Column | Meaning |
|---|---|
| `bank_id` | Primary key, BANK_A-BANK_E. |
| `bank_name` | Synthetic display name. |

CSV encoding is UTF-8, LF line endings, one header row. No field is missing in a clean Phase 2 fixture; the empty failure reason is intentional. Native PostgreSQL stores fields as text to preserve CSV representations, with clean primary/foreign-key and value constraints. Cast `amount_paise::numeric` for arithmetic and `attempted_at::timestamptz` for time calculations. The session timezone is Asia/Kolkata. Inner joins to both dimension tables must preserve the payment count.

Success rate is successful attempts divided by all completed attempts, multiplied by 100. A percentage-point change subtracts two percentage rates. Check integrity before computing metrics; distinguish counts, rates and amount totals.
