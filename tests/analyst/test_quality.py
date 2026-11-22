import pytest
from app.config import Settings
from app.query.executor import connect, Bundle, Authorization, Budget, Cancelled, BudgetExceeded
from app.quality.checks import quality_sql
from app.query.policy import validate_sql


def test_preflight_has_no_window_or_filter_predicate():
    sql=quality_sql('scenario_a_dirty')
    validate_sql(sql,'scenario_a_dirty')
    for rule in ('duplicate_occurrences','missing_timestamps','orphan_merchants','orphan_banks','malformed_timestamps','invalid_amount_currency','invalid_status_reason'):
        assert rule in sql
    assert '%(' not in sql


@pytest.mark.integration
def test_invalid_timestamp_is_diagnostic_without_cast_error():
    with connect(Settings.from_root()) as connection:
        row=connection.execute("SELECT pg_input_is_valid(%s,'timestamp with time zone') AS valid",('2026-02-31T00:00:00+05:30',)).fetchone()
        assert row=={'valid':False}


def test_budget_counts_failures_and_cancel():
    budget=Budget()
    for _ in range(12):
        budget.sql()
    with pytest.raises(BudgetExceeded):
        budget.sql()
    assert budget.statements==13
    budget=Budget()
    budget.cancel.set()
    with pytest.raises(Cancelled):
        budget.check()


@pytest.mark.integration
def test_transaction_rollback_and_next_request():
    settings=Settings.from_root()
    auth=Authorization(settings)
    try:
        with pytest.raises(ValueError):
            with Bundle(settings,auth,Budget()) as bundle:
                bundle.query('invalid','DELETE FROM lifecycle_v1.payments')
        with Bundle(settings,auth,Budget()) as bundle:
            rows=bundle.query('read',f'SELECT COUNT(*) AS n FROM {auth.scenario}.banks')
            assert rows[0]['n']==5
    finally:
        auth.close()
