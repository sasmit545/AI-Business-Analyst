from app.query.compiler import compile_queries
from app.query.policy import validate_sql
from test_evidence import example


def test_filter_attack_stays_in_bound_values():
    from app.contracts import Filters
    attack = "BANK_B'; DROP TABLE payments; --"
    request = example().request.model_copy(update={'filters':Filters(payer_bank_id=attack)})
    queries, parameters = compile_queries('scenario_a',request)
    assert parameters['payer_bank_id']==attack
    for sql in queries.values():
        assert attack not in sql
        validate_sql(sql,'scenario_a')


def test_queries_join_real_banks_and_apply_half_open_windows():
    queries,parameters=compile_queries('lifecycle_v1',example().request)
    assert parameters['c_end']=='2026-10-29T00:00:00+05:30'
    assert all('JOIN lifecycle_v1.banks' in q for q in queries.values())
    assert all('< %(c_end)s' in q and '>= %(c_start)s' in q for q in queries.values())
