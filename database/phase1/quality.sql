SELECT
    count(*) AS rows,
    count(*) - count(DISTINCT p.attempt_id) AS duplicate_occurrences,
    count(*) FILTER (WHERE p.attempted_at = '') AS missing_timestamps,
    count(*) FILTER (WHERE NOT EXISTS
        (SELECT 1 FROM merchants m WHERE m.merchant_id = p.merchant_id)) AS orphan_merchants,
    count(*) FILTER (WHERE NOT EXISTS
        (SELECT 1 FROM banks b WHERE b.bank_id = p.payer_bank_id)) AS orphan_banks
FROM payments p;
