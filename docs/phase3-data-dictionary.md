# lifecycle_v1 data dictionary — schema 1.0.0

One database row in `payments` represents one completed attempt. One `orders` row
represents a purchase intention. IDs are fictional and stable within this profile.
CSV encoding is UTF-8 with a header and LF endings. PostgreSQL retains fields as
text to preserve exact representations; cast validated numbers/timestamps for
arithmetic. All timestamps use `YYYY-MM-DDTHH:MM:SS.sss+05:30`. Blank is the empty
string, not SQL NULL. Amounts are integer INR paise (100 paise = INR 1).

| Table | Key | Fields and meaning |
|---|---|---|
| merchants | merchant_id | merchant_name, category (retail/grocery/dining/services), region (North/South/East/West) |
| banks | bank_id | bank_name: fictional payer bank label |
| payment_methods | payment_method | CARD or UPI; label, role describe the instrument |
| failure_reasons | failure_reason | label and category (technical/authentication/customer); successful attempts use blank and have no failure-dimension match |
| orders | order_id | merchant_id references merchants; created_at starts the purchase intention; amount_paise and currency are the requested amount |
| payments | attempt_id | order_id references orders; attempted_at, completed_at and ingested_at describe attempt start, completion and observation; processing_duration_ms equals completion minus start |
| payments | order_id + attempt_number (unique) | attempt_number is 1–3; merchant_id, amount_paise and currency match the order; payer_bank_id references banks; payment_method references payment_methods |
| payments | at most one SUCCESS per order | status is SUCCESS or FAILED; failure_reason is blank for success and matches failure_reasons for failure; no in-flight states |
| settlements | settlement_id; attempt_id unique | attempt_id references a successful attempt; due_at is completion +24 hours; settlement_status is PENDING or SETTLED; settled_at is blank for pending; gross_amount_paise is the full attempt amount |
| bank_health | bank_id + payment_method + observed_at | observed_at starts a five-minute interval; availability_pct is 0–100%; p95_latency_ms is a positive integer observation |

`O` plus nine digits identifies orders; `L` plus nine digits identifies attempts;
`S` plus nine digits identifies settlements. Sequence order does not imply global
chronological order. A retry is a separate attempt for the same order. Match health
on bank, method and the interval containing attempted_at; an interval is inclusive
at its start and exclusive at its end.

Order conversion uses orders created in the selected window with at least 24 hours
of observation, and success completed within 24 hours of creation. Attempt success
uses completed attempts with attempted_at in the selected window. Settlement
completion uses successful attempts due by cutoff. A pending obligation that is
not yet due does not mean payment failure or overdue backlog. Aggregate attempts
to one row per order before joining order-level metrics.
