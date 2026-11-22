"""Five-minute bank/method alignment; no causal inference from telemetry."""
from app.analytics.lifecycle import aggregate_queries, parameters
from app.quality.lifecycle import invalid_time, select_counts


def health_source():
    # Invalid telemetry is explicitly counted, then represented as unavailable.
    typed=f'''SELECT bank_id, payment_method,
        CASE WHEN NOT {invalid_time('observed_at')} THEN observed_at::timestamptz END AS bucket,
        CASE WHEN pg_input_is_valid(availability_pct,'double precision') THEN availability_pct::double precision END AS availability,
        CASE WHEN pg_input_is_valid(p95_latency_ms,'bigint') THEN p95_latency_ms::bigint END AS latency
        FROM lifecycle_v1.bank_health OFFSET 0'''
    return f'''SELECT bank_id, payment_method, bucket, MAX(availability) AS availability, MAX(latency) AS latency
        FROM ({typed}) typed GROUP BY bank_id,payment_method,bucket HAVING COUNT(*)=1
        AND MAX(availability)>=0 AND MAX(availability)<=100 AND MAX(latency)>0
        AND bucket=date_bin(INTERVAL '5 minutes',bucket,TIMESTAMPTZ '2000-01-01T00:00:00+05:30')'''


def health_quality_sql():
    return select_counts({
        'unusable_health_rows':f'SELECT (SELECT COUNT(*) FROM lifecycle_v1.bank_health)-(SELECT COUNT(*) FROM ({health_source()}) usable)',
        'duplicate_health_rows':'SELECT COALESCE(SUM(n-1),0)::bigint FROM (SELECT COUNT(*) AS n FROM lifecycle_v1.bank_health GROUP BY bank_id,payment_method,observed_at) d',
    })


def compile_health(request):
    params=parameters(request)
    source=f'''SELECT p.payer_bank_id,p.payment_method,p.merchant_id,p.event_time,
        1 AS eligible, CASE WHEN p.status='SUCCESS' THEN 1 ELSE 0 END AS completed,
        CASE WHEN h.bucket IS NULL THEN 1 ELSE 0 END AS unmatched, h.availability, h.latency
        FROM (SELECT payer_bank_id,payment_method,merchant_id,status,attempted_at::timestamptz AS event_time
              FROM lifecycle_v1.payments WHERE completed_at::timestamptz<=%(cutoff)s::timestamptz
              AND ingested_at::timestamptz<=%(cutoff)s::timestamptz OFFSET 0) p
        LEFT JOIN ({health_source()}) h ON p.payer_bank_id=h.bank_id
        AND p.payment_method=h.payment_method
        AND date_bin(INTERVAL '5 minutes',p.event_time,TIMESTAMPTZ '2000-01-01T00:00:00+05:30')=h.bucket'''
    extra=''', SUM(r.unmatched)::bigint AS unmatched,
        SUM(r.availability)/NULLIF(COUNT(r.availability),0) AS attempt_weighted_availability_pct,
        SUM(r.latency)::double precision/NULLIF(COUNT(r.latency),0) AS attempt_weighted_bucket_p95_ms'''
    return aggregate_queries(source,'r.completed','r.eligible',params,extra),params
