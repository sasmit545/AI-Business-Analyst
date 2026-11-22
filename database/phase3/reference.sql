-- PostgreSQL evaluation. Bind :window_start, :window_end (exclusive), :cutoff.
-- Timestamps have the same explicit timezone and millisecond precision throughout.
-- query: totals
SELECT (SELECT count(*) FROM orders) AS orders,
       (SELECT count(*) FROM payments) AS attempts,
       (SELECT count(*) FROM payments WHERE status='SUCCESS') AS successful_attempts,
       (SELECT count(*) FROM payments WHERE attempted_at >= :window_end) AS attempts_after_order_window,
       (SELECT count(*) FROM settlements) AS settlements,
       (SELECT count(*) FROM bank_health) AS bank_health_observations;

-- query: periods
SELECT CASE WHEN substr(attempted_at,1,10) < '2026-10-15' THEN 'baseline' ELSE 'comparison' END AS period,
       count(*) AS attempts, sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS successes,
       sum(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS failures,
       round(100.0*sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/count(*),6) AS success_rate_pct
FROM payments WHERE attempted_at >= :window_start AND attempted_at < :window_end AND completed_at <= :cutoff
GROUP BY 1 ORDER BY 1;

-- query: attempts
SELECT count(*) AS attempts, sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS successes,
       sum(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS failures,
       round(100.0*sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/nullif(count(*),0),6) AS success_rate_pct
FROM payments WHERE attempted_at >= :window_start AND attempted_at < :window_end AND completed_at <= :cutoff;

-- query: orders
WITH cohort AS (
 SELECT o.order_id, o.created_at,
   max(CASE WHEN p.status='SUCCESS' AND p.completed_at <= :cutoff AND (extract(epoch FROM (p.completed_at)::timestamptz)::numeric/86400) <= (extract(epoch FROM (o.created_at)::timestamptz)::numeric/86400)+1 THEN 1 ELSE 0 END) AS paid_24h,
   max(CASE WHEN p.status='SUCCESS' AND p.completed_at <= :cutoff THEN 1 ELSE 0 END) AS paid_by_cutoff
 FROM orders o LEFT JOIN payments p ON p.order_id=o.order_id
 WHERE o.created_at >= :window_start AND o.created_at < :window_end
 GROUP BY o.order_id, o.created_at
)
SELECT count(*) AS selected_orders,
 sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN 1 ELSE 0 END) AS eligible_orders,
 sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN paid_24h ELSE 0 END) AS paid_orders_24h,
 sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN paid_by_cutoff ELSE 0 END) AS paid_orders_by_cutoff,
 sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 > (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN 1 ELSE 0 END) AS immature_orders,
 round(100.0*sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN paid_24h ELSE 0 END)/
 nullif(sum(CASE WHEN (extract(epoch FROM (created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400) THEN 1 ELSE 0 END),0),6) AS conversion_24h_pct
FROM cohort;

-- query: retries
WITH chains AS (
 SELECT o.order_id,
 max(CASE WHEN p.attempt_number='1' AND p.status='FAILED' THEN 1 ELSE 0 END) AS initially_failed,
 max(CASE WHEN CAST(p.attempt_number AS integer)>1 THEN 1 ELSE 0 END) AS retried,
 max(CASE WHEN CAST(p.attempt_number AS integer)>1 AND p.status='SUCCESS' THEN 1 ELSE 0 END) AS recovered,
 sum(CASE WHEN CAST(p.attempt_number AS integer)>1 THEN 1 ELSE 0 END) AS retry_attempts
 FROM orders o JOIN payments p ON p.order_id=o.order_id AND p.completed_at <= :cutoff
 WHERE o.created_at >= :window_start AND o.created_at < :window_end AND (extract(epoch FROM (o.created_at)::timestamptz)::numeric/86400)+1 <= (extract(epoch FROM (:cutoff)::timestamptz)::numeric/86400)
 GROUP BY o.order_id
)
SELECT sum(initially_failed) AS initially_failed_orders, sum(retried) AS retried_orders,
       sum(recovered) AS recovered_orders, sum(retry_attempts) AS retry_attempts,
       round(100.0*sum(recovered)/nullif(sum(retried),0),6) AS recovery_among_retried_pct,
       round(100.0*sum(recovered)/nullif(sum(initially_failed),0),6) AS recovery_among_initial_failures_pct
FROM chains;

-- query: settlements
WITH obligations AS (
 SELECT p.attempt_id, p.amount_paise, s.settled_at, s.settlement_status, s.due_at
 FROM payments p JOIN settlements s ON s.attempt_id=p.attempt_id
 WHERE p.status='SUCCESS' AND p.attempted_at >= :window_start AND p.attempted_at < :window_end AND p.completed_at <= :cutoff
)
SELECT count(*) AS successful_attempts,
 sum(CASE WHEN due_at <= :cutoff THEN 1 ELSE 0 END) AS due_attempts,
 sum(CASE WHEN due_at <= :cutoff AND settlement_status='SETTLED' AND settled_at <= :cutoff THEN 1 ELSE 0 END) AS settled_due_attempts,
 sum(CASE WHEN due_at <= :cutoff AND (settlement_status<>'SETTLED' OR settled_at > :cutoff) THEN 1 ELSE 0 END) AS backlog_attempts,
 sum(CASE WHEN due_at > :cutoff THEN 1 ELSE 0 END) AS not_yet_due_attempts,
 coalesce(sum(CASE WHEN due_at <= :cutoff AND (settlement_status<>'SETTLED' OR settled_at > :cutoff) THEN CAST(amount_paise AS bigint) ELSE 0 END),0) AS backlog_amount_paise,
 coalesce(sum(CASE WHEN settlement_status='SETTLED' AND settled_at <= :cutoff THEN CAST(amount_paise AS bigint) ELSE 0 END),0) AS settled_amount_paise,
 round(100.0*sum(CASE WHEN due_at <= :cutoff AND settlement_status='SETTLED' AND settled_at <= :cutoff THEN 1 ELSE 0 END)/
 nullif(sum(CASE WHEN due_at <= :cutoff THEN 1 ELSE 0 END),0),6) AS completion_pct
FROM obligations;

-- query: order_attempt_distribution
SELECT attempts_per_order, count(*) AS orders FROM (
 SELECT o.order_id, count(p.attempt_id) AS attempts_per_order
 FROM orders o LEFT JOIN payments p ON p.order_id=o.order_id AND p.completed_at <= :cutoff
 WHERE o.created_at >= :window_start AND o.created_at < :window_end
 GROUP BY o.order_id
) chains GROUP BY attempts_per_order ORDER BY attempts_per_order;

-- query: bank_method
SELECT payer_bank_id, payment_method, count(*) AS attempts,
 sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS successes,
 round(100.0*sum(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)/count(*),6) AS success_rate_pct,
 round(avg(CAST(processing_duration_ms AS numeric)),6) AS mean_duration_ms
FROM payments WHERE attempted_at >= :window_start AND attempted_at < :window_end AND completed_at <= :cutoff
GROUP BY payer_bank_id, payment_method ORDER BY payer_bank_id, payment_method;

-- query: temporal_join
WITH matched AS (
 SELECT p.attempt_id, h.bank_id
 FROM payments p LEFT JOIN bank_health h ON h.bank_id=p.payer_bank_id AND h.payment_method=p.payment_method
 AND h.observed_at = substr(p.attempted_at,1,14) ||
   CASE WHEN CAST(substr(p.attempted_at,15,2) AS integer)<10 THEN '0' ELSE '' END ||
   CAST((CAST(substr(p.attempted_at,15,2) AS integer)/5)*5 AS text) || ':00.000+05:30'
 WHERE p.attempted_at >= :window_start AND p.attempted_at < :window_end AND p.completed_at <= :cutoff
)
SELECT count(*) AS joined_rows, count(DISTINCT attempt_id) AS distinct_attempts,
 sum(CASE WHEN bank_id IS NULL THEN 1 ELSE 0 END) AS unmatched_attempts FROM matched;

-- query: joins
SELECT count(*) AS joined_rows, count(DISTINCT p.attempt_id) AS distinct_attempts
FROM payments p JOIN orders o ON o.order_id=p.order_id
JOIN merchants m ON m.merchant_id=p.merchant_id JOIN banks b ON b.bank_id=p.payer_bank_id
JOIN payment_methods pm ON pm.payment_method=p.payment_method
LEFT JOIN failure_reasons fr ON fr.failure_reason=p.failure_reason
LEFT JOIN settlements s ON s.attempt_id=p.attempt_id
WHERE p.attempted_at >= :window_start AND p.attempted_at < :window_end AND p.completed_at <= :cutoff;
