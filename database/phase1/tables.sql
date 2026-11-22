-- {{schema}} is supplied only from the script's fixed scenario allowlist.
CREATE SCHEMA IF NOT EXISTS {{schema}} AUTHORIZATION postgres;
CREATE TABLE IF NOT EXISTS {{schema}}.merchants (
    merchant_id text PRIMARY KEY CHECK (merchant_id ~ '^M(0[1-9]|1[0-9]|20)$'),
    merchant_name text NOT NULL CHECK (btrim(merchant_name) <> ''),
    category text NOT NULL CHECK (category IN ('retail', 'grocery', 'dining', 'services')),
    region text NOT NULL CHECK (region IN ('North', 'South', 'East', 'West'))
);
CREATE TABLE IF NOT EXISTS {{schema}}.banks (
    bank_id text PRIMARY KEY CHECK (bank_id ~ '^BANK_[A-E]$'),
    bank_name text NOT NULL CHECK (btrim(bank_name) <> '')
);
-- Text preserves the exact CSV representation, including +05:30 and empty fields.
CREATE TABLE IF NOT EXISTS {{schema}}.payments (
    attempt_id text NOT NULL,
    attempted_at text NOT NULL,
    merchant_id text NOT NULL,
    payer_bank_id text NOT NULL,
    payment_method text NOT NULL,
    amount_paise text NOT NULL,
    currency text NOT NULL,
    status text NOT NULL,
    failure_reason text NOT NULL
    {{clean_constraints}}
);
CREATE INDEX IF NOT EXISTS payments_bank_method_idx ON {{schema}}.payments (payer_bank_id, payment_method);
CREATE INDEX IF NOT EXISTS payments_merchant_idx ON {{schema}}.payments (merchant_id);
REVOKE ALL ON SCHEMA {{schema}} FROM PUBLIC, ai_analyst;
REVOKE ALL ON ALL TABLES IN SCHEMA {{schema}} FROM PUBLIC, ai_analyst;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA {{schema}} REVOKE ALL ON TABLES FROM PUBLIC, ai_analyst;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA {{schema}} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, ai_analyst;
