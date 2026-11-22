"""Metric dependencies are checked before casts; telemetry defects only warn."""
from app.contracts import QualityRecord
from app.quality.policy import blocked


def invalid_time(column, optional=False):
    invalid=f"({column} IS NULL OR {column}='' OR NOT pg_input_is_valid({column}, 'timestamp with time zone') OR NOT {column} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]+)?[+]05:30$')"
    return f"({column}<>'' AND {invalid})" if optional else invalid


def select_counts(tests):
    return 'SELECT '+', '.join(f'({sql}) AS {name}' for name,sql in tests.items())


def raw_checks(metric):
    p='lifecycle_v1.payments'
    queries=[(name,select_counts({name:f'SELECT COUNT(*) FROM {p} WHERE '+invalid_time(column)}))
             for name,column in [('invalid_completion_time','completed_at'),('invalid_observation_time','ingested_at')]]
    tests={}
    if metric not in ('settlement_count','settlement_amount','bank_health'):
        tests.update({
            'invalid_attempt_number':f"SELECT COUNT(*) FROM {p} WHERE attempt_number IS NULL OR attempt_number NOT IN ('1','2','3')",
            'duplicate_orders':'SELECT COUNT(*)-COUNT(DISTINCT order_id) FROM lifecycle_v1.orders',
            'invalid_order_identity':"SELECT COUNT(*) FROM lifecycle_v1.orders WHERE order_id IS NULL OR order_id='' OR amount_paise IS NULL OR NOT amount_paise ~ '^[1-9][0-9]*$' OR currency IS NULL OR currency<>'INR'",
            'orphan_order_attempts':f'SELECT COUNT(*) FROM {p} p LEFT JOIN lifecycle_v1.orders o ON p.order_id=o.order_id WHERE o.order_id IS NULL',
            'orders_without_attempts':f'SELECT COUNT(*) FROM lifecycle_v1.orders o LEFT JOIN {p} p ON o.order_id=p.order_id WHERE p.order_id IS NULL',
            'order_attribute_mismatch':f'SELECT COUNT(*) FROM {p} p JOIN lifecycle_v1.orders o ON p.order_id=o.order_id WHERE p.amount_paise<>o.amount_paise OR p.currency<>o.currency OR p.merchant_id<>o.merchant_id',
        })
        queries.append(('invalid_order_time',select_counts({'invalid_order_time':'SELECT COUNT(*) FROM lifecycle_v1.orders WHERE '+invalid_time('created_at')})))
    if metric.startswith('settlement_'):
        tests.update({
            'invalid_settlement_fields':"SELECT COUNT(*) FROM lifecycle_v1.settlements WHERE settlement_id IS NULL OR settlement_id='' OR gross_amount_paise IS NULL OR NOT gross_amount_paise ~ '^[1-9][0-9]*$' OR NOT pg_input_is_valid(gross_amount_paise,'bigint') OR settlement_status IS NULL OR settlement_status NOT IN ('PENDING','SETTLED') OR settled_at IS NULL OR (settlement_status='PENDING' AND settled_at<>'') OR (settlement_status='SETTLED' AND settled_at='')",
            'duplicate_settlements':'SELECT COUNT(*)-COUNT(DISTINCT attempt_id) FROM lifecycle_v1.settlements',
            'duplicate_settlement_ids':'SELECT COUNT(*)-COUNT(DISTINCT settlement_id) FROM lifecycle_v1.settlements',
            'invalid_settlement_reference':f"SELECT COUNT(*) FROM lifecycle_v1.settlements s LEFT JOIN {p} p ON s.attempt_id=p.attempt_id WHERE p.attempt_id IS NULL OR p.status<>'SUCCESS' OR s.gross_amount_paise<>p.amount_paise",
            'missing_obligations':f"SELECT COUNT(*) FROM {p} p LEFT JOIN lifecycle_v1.settlements s ON p.attempt_id=s.attempt_id WHERE p.status='SUCCESS' AND s.attempt_id IS NULL",
        })
        for column in ('due_at','settled_at'):
            name='invalid_'+column
            queries.append((name,select_counts({name:'SELECT COUNT(*) FROM lifecycle_v1.settlements WHERE '+invalid_time(column,optional=column=='settled_at')})))
    if tests:
        queries.append(('lifecycle_raw_quality',select_counts(tests)))
    return queries


def invariant_checks(metric):
    p='lifecycle_v1.payments'
    tests={'completion_order':f'SELECT COUNT(*) FROM {p} WHERE completed_at::timestamptz < attempted_at::timestamptz OR ingested_at::timestamptz < completed_at::timestamptz'}
    if metric not in ('settlement_count','settlement_amount','bank_health'):
        tests.update({
            'invalid_attempt_chains':f'''SELECT COUNT(*) FROM (SELECT order_id FROM {p} GROUP BY order_id
                HAVING COUNT(*)<>COUNT(DISTINCT attempt_number) OR MIN(attempt_number::integer)<>1
                OR MAX(attempt_number::integer)<>COUNT(*) OR COUNT(*) FILTER (WHERE status='SUCCESS')>1
                OR COUNT(DISTINCT payer_bank_id)<>1 OR COUNT(DISTINCT payment_method)<>1) bad''',
            'attempt_before_order':f'SELECT COUNT(*) FROM {p} p JOIN lifecycle_v1.orders o ON p.order_id=o.order_id WHERE p.attempted_at::timestamptz<o.created_at::timestamptz',
            'invalid_retry_sequence':f'''SELECT COUNT(*) FROM {p} p JOIN {p} earlier ON p.order_id=earlier.order_id
                AND p.attempt_number::integer=earlier.attempt_number::integer+1
                WHERE earlier.status='SUCCESS' OR p.attempted_at::timestamptz<=earlier.completed_at::timestamptz''',
        })
    if metric.startswith('settlement_'):
        tests['invalid_due_or_settled_time']=f'''SELECT COUNT(*) FROM lifecycle_v1.settlements s JOIN {p} p ON s.attempt_id=p.attempt_id
            WHERE s.due_at::timestamptz<>p.completed_at::timestamptz+INTERVAL '24 hours'
            OR CAST(NULLIF(s.settled_at,'') AS TIMESTAMPTZ)<p.completed_at::timestamptz'''
    return select_counts(tests)


def check_lifecycle_quality(bundle, metric):
    records=[]
    for name,sql in [*raw_checks(metric),('lifecycle_invariants',invariant_checks(metric))]:
        if blocked(records):
            break
        row=bundle.query(name,sql)[0]
        records.extend(QualityRecord(rule=k,count=v,status='BLOCK' if v else 'PASS',metric=metric,
            scope='entire selected metric dependency population before filtering') for k,v in row.items())
    if metric=='bank_health' and not blocked(records):
        from app.analytics.health import health_quality_sql
        row=bundle.query('health_quality',health_quality_sql())[0]
        records.extend(QualityRecord(rule=k,count=v,status='WARN' if v else 'PASS',metric=metric,
            scope='selected schema telemetry; does not block payment metrics') for k,v in row.items())
    return records
