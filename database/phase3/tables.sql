CREATE SCHEMA IF NOT EXISTS lifecycle_v1 AUTHORIZATION postgres;
-- Text columns retain the CSV representation exactly; casts below enforce values.
CREATE TABLE IF NOT EXISTS lifecycle_v1.merchants (
 merchant_id text PRIMARY KEY, merchant_name text NOT NULL, category text NOT NULL, region text NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_v1.banks (bank_id text PRIMARY KEY, bank_name text NOT NULL);
CREATE TABLE IF NOT EXISTS lifecycle_v1.payment_methods (
 payment_method text PRIMARY KEY CHECK(payment_method IN ('CARD','UPI')), label text NOT NULL, role text NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_v1.failure_reasons (
 failure_reason text PRIMARY KEY CHECK(failure_reason IN ('BANK_TIMEOUT','AUTHENTICATION_FAILED','INSUFFICIENT_FUNDS','LIMIT_EXCEEDED')),
 label text NOT NULL, category text NOT NULL CHECK(category IN ('technical','authentication','customer'))
);
CREATE TABLE IF NOT EXISTS lifecycle_v1.orders (
 order_id text PRIMARY KEY CHECK(order_id ~ '^O[0-9]{9}$'),
 merchant_id text NOT NULL REFERENCES lifecycle_v1.merchants,
 created_at text NOT NULL CHECK(created_at ~ '^2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\+05:30$'
   AND created_at::timestamptz >= '2026-10-01T00:00:00+05:30'::timestamptz
   AND created_at::timestamptz < '2026-10-29T00:00:00+05:30'::timestamptz),
 amount_paise text NOT NULL CHECK(amount_paise ~ '^[0-9]+$' AND amount_paise::bigint BETWEEN 1000 AND 10000000),
 currency text NOT NULL CHECK(currency='INR'),
 UNIQUE(order_id,merchant_id,amount_paise,currency)
);
CREATE TABLE IF NOT EXISTS lifecycle_v1.payments (
 attempt_id text PRIMARY KEY CHECK(attempt_id ~ '^L[0-9]{9}$'),
 attempted_at text NOT NULL CHECK(attempted_at ~ '^2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\+05:30$'),
 merchant_id text NOT NULL REFERENCES lifecycle_v1.merchants,
 payer_bank_id text NOT NULL REFERENCES lifecycle_v1.banks,
 payment_method text NOT NULL REFERENCES lifecycle_v1.payment_methods,
 amount_paise text NOT NULL CHECK(amount_paise ~ '^[0-9]+$' AND amount_paise::bigint BETWEEN 1000 AND 10000000),
 currency text NOT NULL CHECK(currency='INR'),
 status text NOT NULL CHECK(status IN ('SUCCESS','FAILED')),
 failure_reason text NOT NULL,
 order_id text NOT NULL REFERENCES lifecycle_v1.orders,
 attempt_number text NOT NULL CHECK(attempt_number IN ('1','2','3')),
 completed_at text NOT NULL CHECK(completed_at ~ '^2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\+05:30$'),
 processing_duration_ms text NOT NULL CHECK(processing_duration_ms ~ '^[0-9]+$' AND processing_duration_ms::integer > 0),
 ingested_at text NOT NULL CHECK(ingested_at ~ '^2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\+05:30$'),
 CHECK((status='SUCCESS' AND failure_reason='') OR (status='FAILED' AND failure_reason IN ('BANK_TIMEOUT','AUTHENTICATION_FAILED','INSUFFICIENT_FUNDS','LIMIT_EXCEEDED'))),
 CHECK(completed_at::timestamptz-attempted_at::timestamptz = processing_duration_ms::integer*interval '1 millisecond'),
 CHECK(ingested_at::timestamptz >= completed_at::timestamptz AND ingested_at::timestamptz <= '2026-11-01T00:00:00+05:30'::timestamptz),
 FOREIGN KEY(order_id,merchant_id,amount_paise,currency) REFERENCES lifecycle_v1.orders(order_id,merchant_id,amount_paise,currency),
 UNIQUE(order_id,attempt_number), UNIQUE(attempt_id,amount_paise)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_success_per_order ON lifecycle_v1.payments(order_id) WHERE status='SUCCESS';
CREATE INDEX IF NOT EXISTS lifecycle_payment_bank_method ON lifecycle_v1.payments(payer_bank_id,payment_method);
CREATE TABLE IF NOT EXISTS lifecycle_v1.settlements (
 settlement_id text PRIMARY KEY CHECK(settlement_id ~ '^S[0-9]{9}$'),
 attempt_id text NOT NULL UNIQUE REFERENCES lifecycle_v1.payments,
 due_at text NOT NULL CHECK(due_at ~ '^2026-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\+05:30$'),
 settled_at text NOT NULL,
 settlement_status text NOT NULL CHECK(settlement_status IN ('PENDING','SETTLED')),
 gross_amount_paise text NOT NULL,
 FOREIGN KEY(attempt_id,gross_amount_paise) REFERENCES lifecycle_v1.payments(attempt_id,amount_paise),
 CHECK((settlement_status='PENDING' AND settled_at='' AND due_at::timestamptz > '2026-11-01T00:00:00+05:30'::timestamptz)
   OR (settlement_status='SETTLED' AND settled_at=due_at AND due_at::timestamptz <= '2026-11-01T00:00:00+05:30'::timestamptz))
);
CREATE TABLE IF NOT EXISTS lifecycle_v1.bank_health (
 bank_id text NOT NULL REFERENCES lifecycle_v1.banks,
 payment_method text NOT NULL REFERENCES lifecycle_v1.payment_methods,
 observed_at text NOT NULL CHECK(observed_at ~ '^2026-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:00\.000\+05:30$'
   AND extract(minute FROM observed_at::timestamptz)::integer % 5=0
   AND observed_at::timestamptz >= '2026-10-01T00:00:00+05:30'::timestamptz
   AND observed_at::timestamptz < '2026-11-01T00:00:00+05:30'::timestamptz),
 availability_pct text NOT NULL CHECK(availability_pct::numeric BETWEEN 0 AND 100),
 p95_latency_ms text NOT NULL CHECK(p95_latency_ms ~ '^[0-9]+$' AND p95_latency_ms::integer>0),
 PRIMARY KEY(bank_id,payment_method,observed_at)
);
REVOKE ALL ON SCHEMA lifecycle_v1 FROM PUBLIC, ai_analyst;
REVOKE ALL ON ALL TABLES IN SCHEMA lifecycle_v1 FROM PUBLIC, ai_analyst;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA lifecycle_v1 REVOKE ALL ON TABLES FROM PUBLIC, ai_analyst;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA lifecycle_v1 REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, ai_analyst;
