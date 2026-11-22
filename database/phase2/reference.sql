-- PostgreSQL evaluation SQL; one selected schema at a time.
-- query: totals
SELECT count(*) AS attempts, sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
       sum(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures,
       round(100.0 * sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) / count(*), 6) AS success_rate_pct
FROM payments;

-- query: periods
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       count(*) AS attempts, sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
       sum(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures,
       round(100.0 * sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) / count(*), 6) AS success_rate_pct
FROM payments GROUP BY period ORDER BY period;

-- query: bank_method
SELECT payer_bank_id, payment_method, count(*) AS attempts,
       sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
       round(100.0 * sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) / count(*), 6) AS success_rate_pct
FROM payments GROUP BY payer_bank_id, payment_method ORDER BY payer_bank_id, payment_method;

-- query: window_bank_method
SELECT CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'pre'
            WHEN substr(attempted_at, 1, 10) <= '2026-10-21' THEN 'incident_window' ELSE 'post' END AS time_window,
       payer_bank_id, payment_method, count(*) AS attempts,
       sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
       sum(CASE WHEN failure_reason = 'BANK_TIMEOUT' THEN 1 ELSE 0 END) AS bank_timeouts,
       round(100.0 * sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) / count(*), 6) AS success_rate_pct
FROM payments GROUP BY time_window, payer_bank_id, payment_method ORDER BY time_window, payer_bank_id, payment_method;

-- query: merchants
SELECT merchant_id, count(*) AS attempts FROM payments GROUP BY merchant_id ORDER BY merchant_id;

-- query: banks
SELECT payer_bank_id, count(*) AS attempts FROM payments GROUP BY payer_bank_id ORDER BY payer_bank_id;

-- query: merchant_methods
SELECT merchant_id, payment_method, count(*) AS attempts FROM payments
GROUP BY merchant_id, payment_method ORDER BY merchant_id, payment_method;

-- query: categories
SELECT m.category, p.payment_method, count(*) AS attempts,
       sum(CASE WHEN p.status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes
FROM payments p JOIN merchants m ON m.merchant_id = p.merchant_id
GROUP BY m.category, p.payment_method ORDER BY m.category, p.payment_method;

-- query: amounts
WITH ranked AS (
  SELECT m.category, CAST(p.amount_paise AS INTEGER) AS amount,
    row_number() OVER (PARTITION BY m.category ORDER BY CAST(p.amount_paise AS INTEGER), p.attempt_id) AS rank,
    count(*) OVER (PARTITION BY m.category) AS n
  FROM payments p JOIN merchants m ON m.merchant_id = p.merchant_id
)
SELECT category, count(*) AS attempts, min(amount) AS minimum_paise, max(amount) AS maximum_paise,
       round(1.0 * sum(amount) / count(*), 6) AS mean_paise,
       round(avg(CASE WHEN rank IN (CAST((n + 1) / 2 AS INTEGER), CAST((n + 2) / 2 AS INTEGER)) THEN amount END), 6) AS median_paise
FROM ranked GROUP BY category ORDER BY category;

-- query: hourly
SELECT m.category, CAST(substr(p.attempted_at, 12, 2) AS INTEGER) AS local_hour,
       count(*) AS attempts, sum(CASE WHEN p.status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes
FROM payments p JOIN merchants m ON m.merchant_id = p.merchant_id
GROUP BY m.category, local_hour ORDER BY m.category, local_hour;

-- query: weekdays
SELECT m.category, extract(isodow FROM substr(p.attempted_at, 1, 10)::date)::integer AS iso_weekday,
       count(*) AS attempts, round(count(*) / 4.0, 6) AS attempts_per_calendar_day
FROM payments p JOIN merchants m ON m.merchant_id = p.merchant_id
GROUP BY m.category, iso_weekday ORDER BY m.category, iso_weekday;

-- query: daily
SELECT substr(attempted_at, 1, 10) AS local_date, count(*) AS attempts,
       sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes
FROM payments GROUP BY local_date ORDER BY local_date;

-- query: matched_segments
SELECT payer_bank_id, payment_method,
       CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       CAST(substr(attempted_at, 12, 2) AS INTEGER) AS local_hour,
       extract(isodow FROM substr(attempted_at, 1, 10)::date)::integer AS iso_weekday,
       count(*) AS attempts, sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes
FROM payments GROUP BY payer_bank_id, payment_method, period, local_hour, iso_weekday
ORDER BY payer_bank_id, payment_method, period, local_hour, iso_weekday;

-- query: failure_reasons
SELECT payment_method, failure_reason, count(*) AS failures FROM payments WHERE status = 'FAILED'
GROUP BY payment_method, failure_reason ORDER BY payment_method, failure_reason;

-- query: standardized_periods
-- Within each bank/method, match local hour and weekday. Use pooled exposure weights
-- over strata observed in BOTH periods; explicitly report excluded attempts.
WITH strata AS (
  SELECT payer_bank_id, payment_method,
         CAST(substr(attempted_at, 12, 2) AS INTEGER) AS local_hour,
         extract(isodow FROM substr(attempted_at, 1, 10)::date)::integer AS iso_weekday,
         sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' THEN 1 ELSE 0 END) AS n0,
         sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' THEN 1 ELSE 0 END) AS n1,
         sum(CASE WHEN substr(attempted_at, 1, 10) < '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS s0,
         sum(CASE WHEN substr(attempted_at, 1, 10) >= '2026-10-15' AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS s1
  FROM payments GROUP BY payer_bank_id, payment_method, local_hour, iso_weekday
), weighted AS (
  SELECT *, CASE WHEN n0 > 0 AND n1 > 0 THEN n0 + n1 ELSE 0 END AS weight FROM strata
)
SELECT payer_bank_id, payment_method,
       sum(CASE WHEN weight > 0 THEN 1 ELSE 0 END) AS common_strata,
       sum(n0) AS baseline_attempts, sum(n1) AS comparison_attempts,
       sum(CASE WHEN weight = 0 THEN n0 ELSE 0 END) AS excluded_baseline_attempts,
       sum(CASE WHEN weight = 0 THEN n1 ELSE 0 END) AS excluded_comparison_attempts,
       round(sum(CASE WHEN weight > 0 THEN 100.0 * weight * s0 / n0 ELSE 0 END) / sum(weight), 6) AS baseline_standardized_pct,
       round(sum(CASE WHEN weight > 0 THEN 100.0 * weight * s1 / n1 ELSE 0 END) / sum(weight), 6) AS comparison_standardized_pct,
       round(sum(CASE WHEN weight > 0 THEN 100.0 * weight * (1.0 * s1 / n1 - 1.0 * s0 / n0) ELSE 0 END) / sum(weight), 6) AS change_pp
FROM weighted GROUP BY payer_bank_id, payment_method ORDER BY payer_bank_id, payment_method;

-- query: joins
SELECT (SELECT count(*) FROM payments) AS payment_count,
       (SELECT count(*) FROM payments p JOIN merchants m ON p.merchant_id = m.merchant_id) AS merchant_join_count,
       (SELECT count(*) FROM payments p JOIN banks b ON p.payer_bank_id = b.bank_id) AS bank_join_count,
       count(*) AS combined_join_count
FROM payments p JOIN merchants m ON p.merchant_id = m.merchant_id JOIN banks b ON p.payer_bank_id = b.bank_id;
