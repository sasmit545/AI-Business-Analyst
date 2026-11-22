,
PRIMARY KEY (attempt_id),
FOREIGN KEY (merchant_id) REFERENCES {{schema}}.merchants(merchant_id),
FOREIGN KEY (payer_bank_id) REFERENCES {{schema}}.banks(bank_id),
CHECK (attempt_id ~ '^[AB][0-9]{6}$'),
CHECK (attempted_at ~ '^2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+]05:30$'),
CHECK ((attempted_at::timestamptz AT TIME ZONE 'Asia/Kolkata')::date
       BETWEEN DATE '2026-10-01' AND DATE '2026-10-28'),
CHECK (amount_paise ~ '^[1-9][0-9]*$' AND amount_paise::numeric > 0),
CHECK (currency = 'INR'),
CHECK (payment_method IN ('CARD', 'UPI')),
CHECK ((status = 'SUCCESS' AND failure_reason = '') OR
       (status = 'FAILED' AND failure_reason IN
        ('BANK_TIMEOUT', 'INSUFFICIENT_FUNDS', 'AUTHENTICATION_FAILED', 'LIMIT_EXCEEDED')))
