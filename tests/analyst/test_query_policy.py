import pytest
from app.query.policy import validate_sql


@pytest.mark.parametrize('sql', [
    'DELETE FROM lifecycle_v1.payments', 'SELECT 1; SELECT 2',
    'WITH x AS (DELETE FROM lifecycle_v1.payments RETURNING *) SELECT * FROM x',
    'SELECT * INTO x FROM lifecycle_v1.payments',
    'SELECT * FROM lifecycle_v1.payments FOR UPDATE',
    'SELECT * FROM scenario_a.payments', 'SELECT * FROM pg_catalog.pg_authid',
    "SELECT pg_read_file('/etc/passwd')", 'SELECT pg_sleep(3)',
    'SET ROLE postgres', 'COPY lifecycle_v1.payments TO PROGRAM \'x\'',
    'SELECT public.evil(attempt_id) FROM lifecycle_v1.payments',
])
def test_rejects_forbidden_queries(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, 'lifecycle_v1')


def test_allows_selected_registered_shape():
    validate_sql('SELECT COUNT(*) AS n FROM lifecycle_v1.payments', 'lifecycle_v1')
