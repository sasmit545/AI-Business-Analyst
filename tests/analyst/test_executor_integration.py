import pytest

from app.analytics.attempts import analyze
from app.config import Settings
from app.contracts import AnalysisRequest, Scope
from app.query.executor import Authorization, Budget, StaleSession
from test_lifecycle import hand_connection


@pytest.mark.integration
def test_live_selected_scope_comparison():
    settings = Settings.from_root()
    auth = Authorization(settings)
    try:
        request = AnalysisRequest(baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'}, comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'})
        evidence = analyze(settings, auth, Scope(scenario=auth.scenario, session_id='test'), request, Budget())
        assert evidence.queries and evidence.snapshot
        if auth.scenario == 'lifecycle_v1':
            assert sum(row['attempts'] for row in evidence.results['overall']) == 199733
            assert sum(row['successes'] for row in evidence.results['overall']) == 193947
            assert all(q.status == 'PASS' for q in evidence.quality)
    finally:
        auth.close()


@pytest.mark.integration
def test_original_connection_cannot_reconnect():
    auth = Authorization(Settings.from_root())
    auth.connection.close()
    with pytest.raises(StaleSession):
        auth.check()
    with pytest.raises(StaleSession):
        auth.check()


def test_bank_lookup_uses_database_names_and_clarifies_before_analysis(hand_connection, tmp_path):
    from app.agent.graph import Investigator
    from app.agent.model import ToolCall
    from app.api.session import Investigation
    from app.evidence.store import EvidenceStore
    from app.query.compiler import compile_queries
    from app.query.executor import read_bank_directory
    from test_agent_flow import AuthorizationDouble, ModelDouble
    from test_evidence import example
    from test_health import TemporaryBundle

    hand_connection.execute("INSERT INTO pg_temp.banks VALUES ('issuer-71','Harbor Mutual'), "
                            "('issuer-82','Union North'), ('issuer-94','Union North'), ('issuer-05','No Traffic')")
    hand_connection.execute("UPDATE pg_temp.payments SET payer_bank_id='issuer-71'")
    auth = AuthorizationDouble()
    auth.banks = read_bank_directory(hand_connection, 'pg_temp')
    for label, expected in [('Harbor Mutual','issuer-71'), ('No Traffic','issuer-05'),
                            ('Unknown Bank',None), ('Union North',None), ('issuer-82','issuer-82')]:
        args = example().request.model_dump(mode='json')
        args['filters'] = {'payer_bank_id':label}
        model = ModelDouble([ToolCall('query','analyze_attempts',args)])
        job = Investigation('Compare this bank', Scope(session_id='bank-lookup', scenario=auth.scenario))
        runner = Investigator(Settings(db_password='unused'), auth, EvidenceStore(tmp_path), model)
        try:
            call = runner._model({'job':job})['call']
            if expected is None:
                assert call is None and job.status == 'clarification_required' and job.budget.statements == 0
                expected_message = 'No bank matches' if label == 'Unknown Bank' else 'issuer-82, issuer-94'
                assert expected_message in job.clarification
            else:
                request = AnalysisRequest.model_validate(call.arguments)
                assert request.filters.payer_bank_id == expected
                queries, params = compile_queries(auth.scenario, request)
                rows = TemporaryBundle(hand_connection).query('overall', queries['overall'], params)
                assert sum(r['attempts'] for r in rows) == (4 if expected == 'issuer-71' else 0)
        finally:
            runner.close()
