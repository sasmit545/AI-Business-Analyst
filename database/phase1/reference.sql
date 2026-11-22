-- PostgreSQL queries over imported tables. Run one schema at a time via search_path.
-- Only run metrics after quality validation passes. Dates remain in local +05:30.
-- query: periods
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       count(*) AS attempts, sum((status = 'SUCCESS')::integer) AS successes,
       sum((status = 'FAILED')::integer) AS failures,
       round(100.0 * sum((status = 'SUCCESS')::integer) / count(*), 6) AS success_rate_pct
FROM payments GROUP BY period ORDER BY period;

-- query: bank_method
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       payer_bank_id, payment_method, count(*) AS attempts,
       sum((status = 'SUCCESS')::integer) AS successes, sum((status = 'FAILED')::integer) AS failures,
       round(100.0 * sum((status = 'SUCCESS')::integer) / count(*), 6) AS success_rate_pct
FROM payments GROUP BY period, payer_bank_id, payment_method ORDER BY period, payer_bank_id, payment_method;

-- query: methods
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       payment_method, count(*) AS attempts, sum((status = 'SUCCESS')::integer) AS successes,
       round(100.0 * sum((status = 'SUCCESS')::integer) / count(*), 6) AS success_rate_pct,
       round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY
         CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END), 6) AS volume_share_pct
FROM payments GROUP BY period, payment_method ORDER BY period, payment_method;

-- query: failure_reasons
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       payer_bank_id, payment_method, failure_reason, count(*) AS failures
FROM payments WHERE status = 'FAILED'
GROUP BY period, payer_bank_id, payment_method, failure_reason
ORDER BY period, payer_bank_id, payment_method, failure_reason;

-- query: merchant_allocations
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       payer_bank_id, payment_method, merchant_id, count(*) AS attempts,
       sum((status = 'SUCCESS')::integer) AS successes
FROM payments GROUP BY period, payer_bank_id, payment_method, merchant_id
ORDER BY period, payer_bank_id, payment_method, merchant_id;

-- query: daily
SELECT substr(attempted_at, 1, 10) AS local_date, count(*) AS attempts
FROM payments GROUP BY local_date ORDER BY local_date;

-- query: joins
SELECT (SELECT count(*) FROM payments) AS payment_count,
       (SELECT count(*) FROM payments p JOIN merchants m ON p.merchant_id = m.merchant_id) AS merchant_join_count,
       (SELECT count(*) FROM payments p JOIN banks b ON p.payer_bank_id = b.bank_id) AS bank_join_count,
       count(*) AS combined_join_count
FROM payments p JOIN merchants m ON p.merchant_id = m.merchant_id
JOIN banks b ON p.payer_bank_id = b.bank_id;

-- query: merchant_segments
SELECT CASE WHEN substr(p.attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       m.category, m.region, count(*) AS attempts, sum((p.status = 'SUCCESS')::integer) AS successes
FROM payments p JOIN merchants m ON p.merchant_id = m.merchant_id
GROUP BY period, m.category, m.region ORDER BY period, m.category, m.region;

-- query: bank_method_change
WITH cells AS (
  SELECT payer_bank_id, payment_method,
    sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 1 ELSE 0 END) AS baseline_attempts,
    sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' THEN 1 ELSE 0 END) AS comparison_attempts,
    sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS baseline_successes,
    sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS comparison_successes
  FROM payments GROUP BY payer_bank_id, payment_method
)
SELECT *, (comparison_attempts - comparison_successes) - (baseline_attempts - baseline_successes) AS additional_failures,
  round(100.0 * comparison_successes / sum(comparison_attempts) OVER ()
      - 100.0 * baseline_successes / sum(baseline_attempts) OVER (), 6) AS overall_change_contribution_pp
FROM cells ORDER BY payer_bank_id, payment_method;

-- query: method_decomposition
WITH methods AS (
  SELECT payment_method,
    sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 1 ELSE 0 END) AS n0,
    sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' THEN 1 ELSE 0 END) AS n1,
    sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS s0,
    sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS s1
  FROM payments GROUP BY payment_method
), rates AS (
  SELECT *, 1.0 * n0 / sum(n0) OVER () AS w0, 1.0 * n1 / sum(n1) OVER () AS w1,
    1.0 * s0 / n0 AS r0, 1.0 * s1 / n1 AS r1 FROM methods
)
SELECT payment_method, round(100 * (w1 - w0) * r0, 6) AS mix_effect_pp,
       round(100 * w1 * (r1 - r0), 6) AS within_method_effect_pp
FROM rates ORDER BY payment_method;
