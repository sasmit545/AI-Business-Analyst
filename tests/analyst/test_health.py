from test_lifecycle import hand_connection, execute, request
from app.quality.lifecycle import check_lifecycle_quality
from app.query.policy import validate_sql


class TemporaryBundle:
    def __init__(self,connection):
        self.connection=connection

    def query(self,name,sql,parameters=None):
        validate_sql(sql,'lifecycle_v1')
        return self.connection.execute(sql.replace('lifecycle_v1.','pg_temp.'),parameters or {}).fetchall()


def test_containing_bucket_missing_and_duplicate_health_do_not_multiply(hand_connection):
    req=request('bank_health')
    row=execute(hand_connection,req)['overall'][0]
    assert (row['numerator'],row['denominator'],row['unmatched'])==(2,4,0)
    hand_connection.execute("DELETE FROM pg_temp.bank_health WHERE observed_at LIKE '%10:05:%'")
    row=execute(hand_connection,req)['overall'][0]
    assert (row['numerator'],row['denominator'],row['unmatched'])==(2,4,1)
    hand_connection.execute('INSERT INTO pg_temp.bank_health SELECT * FROM pg_temp.bank_health')
    row=execute(hand_connection,req)['overall'][0]
    assert (row['numerator'],row['denominator'],row['unmatched'])==(2,4,4)


def test_boundary_and_other_method_do_not_match(hand_connection):
    hand_connection.execute("UPDATE pg_temp.payments SET attempted_at='2026-10-28T10:05:00+05:30' WHERE attempt_number='2'")
    hand_connection.execute("UPDATE pg_temp.bank_health SET payment_method='CARD' WHERE observed_at LIKE '%10:05:%'")
    row=execute(hand_connection,request('bank_health'))['overall'][0]
    assert row['unmatched']==1


def test_bad_health_warns_but_invalid_completion_blocks(hand_connection):
    hand_connection.execute("UPDATE pg_temp.bank_health SET observed_at='invalid'")
    records=check_lifecycle_quality(TemporaryBundle(hand_connection),'bank_health')
    assert any(q.status=='WARN' for q in records) and not any(q.status=='BLOCK' for q in records)
    assert execute(hand_connection,request('bank_health'))['overall'][0]['unmatched']==4
    hand_connection.execute("UPDATE pg_temp.payments SET completed_at='' WHERE attempt_number='2'")
    records=check_lifecycle_quality(TemporaryBundle(hand_connection),'bank_health')
    assert any(q.status=='BLOCK' for q in records)


def test_order_grain_quality_and_settlement_dependencies(hand_connection):
    bundle=TemporaryBundle(hand_connection)
    assert all(q.status=='PASS' for q in check_lifecycle_quality(bundle,'order_conversion'))
    hand_connection.execute('INSERT INTO pg_temp.settlements SELECT * FROM pg_temp.settlements')
    assert all(q.status=='PASS' for q in check_lifecycle_quality(bundle,'order_conversion'))
    assert any(q.status=='BLOCK' for q in check_lifecycle_quality(bundle,'settlement_count'))
    hand_connection.execute("UPDATE pg_temp.payments SET attempt_number='1' WHERE attempt_number='2'")
    assert any(q.status=='BLOCK' for q in check_lifecycle_quality(bundle,'order_conversion'))


def test_out_of_range_health_is_unavailable_not_a_payment_failure(hand_connection):
    hand_connection.execute("UPDATE pg_temp.bank_health SET availability_pct='101'")
    records=check_lifecycle_quality(TemporaryBundle(hand_connection),'bank_health')
    assert any(q.status=='WARN' for q in records) and not any(q.status=='BLOCK' for q in records)
    row=execute(hand_connection,request('bank_health'))['overall'][0]
    assert (row['numerator'],row['denominator'],row['unmatched'])==(2,4,4)


def test_duplicate_health_with_invalid_value_remains_ambiguous(hand_connection):
    hand_connection.execute("INSERT INTO pg_temp.bank_health SELECT 'broken', bank_id, observed_at, p95_latency_ms, payment_method FROM pg_temp.bank_health")
    row=execute(hand_connection,request('bank_health'))['overall'][0]
    assert (row['numerator'],row['denominator'],row['unmatched'])==(2,4,4)


def test_empty_health_windows_have_unavailable_telemetry():
    from app.analytics.lifecycle import derive
    result=derive({'overall':[],'segments':[]},metric='bank_health')
    for row in result['overall']:
        assert row['rate'] is None and row['denominator']==0
        assert row['unmatched']==0
        assert row['attempt_weighted_availability_pct'] is None
        assert row['attempt_weighted_bucket_p95_ms'] is None
