-- Evaluator-only counterfactual queries, never granted to the AI's single-schema role.
-- query: summary
SELECT count(*) AS matched_attempts,
       sum(CASE WHEN b.status = 'SUCCESS' AND i.status = 'FAILED' THEN 1 ELSE 0 END) AS converted_successes,
       sum(CASE WHEN b.status <> i.status OR b.failure_reason <> i.failure_reason THEN 1 ELSE 0 END) AS changed_outcome_rows,
       sum(CASE WHEN b.attempted_at <> i.attempted_at OR b.merchant_id <> i.merchant_id OR b.payer_bank_id <> i.payer_bank_id
                     OR b.payment_method <> i.payment_method OR b.amount_paise <> i.amount_paise OR b.currency <> i.currency
                THEN 1 ELSE 0 END) AS changed_non_outcome_rows,
       round(100.0 * (sum(CASE WHEN i.status = 'SUCCESS' THEN 1 ELSE 0 END) -
                     sum(CASE WHEN b.status = 'SUCCESS' THEN 1 ELSE 0 END)) / count(*), 6) AS overall_success_change_pp
FROM phase2_baseline.payments b JOIN phase2_incident.payments i ON b.attempt_id = i.attempt_id;

-- query: eligible
SELECT attempt_id FROM phase2_baseline.payments WHERE payer_bank_id = 'BANK_B' AND payment_method = 'UPI'
AND status = 'SUCCESS' AND substr(attempted_at, 1, 10) BETWEEN '2026-10-15' AND '2026-10-21' ORDER BY attempt_id;

-- query: changed
SELECT b.attempt_id, b.payer_bank_id, b.payment_method, substr(b.attempted_at, 1, 10) AS local_date,
       b.status AS original_status, i.status AS incident_status,
       b.failure_reason AS original_reason, i.failure_reason AS incident_reason
FROM phase2_baseline.payments b JOIN phase2_incident.payments i ON b.attempt_id = i.attempt_id
WHERE b.status <> i.status OR b.failure_reason <> i.failure_reason ORDER BY b.attempt_id;

-- query: segment_changes
SELECT b.payer_bank_id, b.payment_method,
       CASE WHEN substr(b.attempted_at, 1, 10) < '2026-10-15' THEN 'pre'
            WHEN substr(b.attempted_at, 1, 10) <= '2026-10-21' THEN 'incident_window' ELSE 'post' END AS time_window,
       count(*) AS attempts,
       sum(CASE WHEN b.status = 'SUCCESS' THEN 1 ELSE 0 END) AS baseline_successes,
       sum(CASE WHEN i.status = 'SUCCESS' THEN 1 ELSE 0 END) AS incident_successes,
       sum(CASE WHEN i.failure_reason = 'BANK_TIMEOUT' THEN 1 ELSE 0 END) -
       sum(CASE WHEN b.failure_reason = 'BANK_TIMEOUT' THEN 1 ELSE 0 END) AS additional_timeouts,
       round(100.0 * (sum(CASE WHEN i.status = 'SUCCESS' THEN 1 ELSE 0 END) -
                     sum(CASE WHEN b.status = 'SUCCESS' THEN 1 ELSE 0 END)) / count(*), 6) AS success_change_pp
FROM phase2_baseline.payments b JOIN phase2_incident.payments i ON b.attempt_id = i.attempt_id
GROUP BY b.payer_bank_id, b.payment_method, time_window ORDER BY b.payer_bank_id, b.payment_method, time_window;
