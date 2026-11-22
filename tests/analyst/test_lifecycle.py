import json
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import Settings
from app.contracts import LifecycleRequest
from app.analytics.lifecycle import compile_lifecycle, derive
from app.query.policy import validate_sql


@pytest.fixture
def hand_connection():
    """Evaluator-only disposable tables; original schemas are never written."""
    settings = Settings.from_root()
    fixture = json.loads(Path('evaluation/phase3/hand_fixture.json').read_text())
    with psycopg.connect(host='127.0.0.1', port=settings.db_port,
                        dbname='payments_analytics', user='postgres',
                        password=Path('.local/postgres/postgres_password').read_text().strip(),
                        row_factory=dict_row) as connection:
        try:
            for table, rows in fixture['tables'].items():
                columns = list(rows[0])
                connection.execute(f'CREATE TEMP TABLE {table} ('+', '.join(c+' text' for c in columns)+') ON COMMIT DROP')
                with connection.cursor() as cursor:
                    cursor.executemany(f'INSERT INTO {table} VALUES ('+', '.join(['%s']*len(columns))+')',
                                       [[r[c] for c in columns] for r in rows])
            yield connection
        finally:
            connection.rollback()


def request(metric, cutoff='2026-10-29T12:00:00+05:30'):
    return LifecycleRequest(metric=metric,
        baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'},
        comparison={'start':'2026-10-29T00:00:00+05:30','end':'2026-10-30T00:00:00+05:30'},
        observation_cutoff=cutoff)


def execute(connection, req):
    queries, params = compile_lifecycle('lifecycle_v1', req)
    rows = {}
    for name, sql in queries.items():
        validate_sql(sql, 'lifecycle_v1')
        rows[name] = connection.execute(sql.replace('lifecycle_v1.', 'pg_temp.'), params).fetchall()
    return derive(rows)


@pytest.mark.parametrize('metric,numerator,denominator', [
    ('order_conversion',1,2), ('first_attempt_success',0,2),
    ('retry_uptake',1,2), ('retry_recovery_all',1,2),
    ('retry_recovery_retried',1,1), ('settlement_count',1,1),
    ('settlement_amount',10000,10000),
])
def test_hand_grains_cutoff_and_denominators(hand_connection, metric, numerator, denominator):
    result=execute(hand_connection,request(metric))
    assert (result['overall'][0]['numerator'],result['overall'][0]['denominator'])==(numerator,denominator)
    assert result['overall'][1]['rate'] is None


def test_pending_due_obligation_is_backlog(hand_connection):
    hand_connection.execute("UPDATE pg_temp.settlements SET settlement_status='PENDING', settled_at='' WHERE attempt_id='L000000002'")
    row=execute(hand_connection,request('settlement_amount'))['overall'][0]
    assert (row['numerator'],row['denominator'],row['excluded'])==(0,10000,1)


def test_success_after_attempt_window_counts_for_created_order(hand_connection):
    hand_connection.execute("UPDATE pg_temp.payments SET attempted_at='2026-10-29T00:00:01+05:30', completed_at='2026-10-29T00:00:02+05:30', ingested_at='2026-10-29T00:00:02+05:30' WHERE attempt_number='2'")
    row=execute(hand_connection,request('order_conversion'))['overall'][0]
    assert (row['numerator'],row['denominator'])==(1,2)
