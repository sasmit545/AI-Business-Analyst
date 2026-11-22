from fastapi.testclient import TestClient
import pytest

from app.agent.graph import Investigator
from app.agent.model import ToolCall
from app.api.main import create_app
from app.api.session import Investigation
from app.config import Settings
from app.contracts import Scope
from app.evidence.store import EvidenceStore
from app.context.catalog import catalog
from app.context.dimensions import DimensionLookupError, bind_filters
from app.query.executor import Authorization, read_directory
from test_agent_flow import AuthorizationDouble, CompareDouble, ModelDouble
from test_lifecycle import hand_connection


def test_method_vocabulary_belongs_to_selected_adapter():
    assert set(catalog('phase2_baseline')['filter_values']['payment_method']) == {'CARD', 'UPI'}
    lifecycle = catalog('lifecycle_v1')
    assert 'payment_methods' in lifecycle['tables'] and 'payment_method' not in lifecycle['filter_values']


@pytest.mark.parametrize('call', [ToolCall('unsupported','clarify',{'topic':'unsupported'}),
                                  ToolCall('measure','analyze_lifecycle',{'metric':'settlement_count'})])
def test_unavailable_measure_identifies_selected_scope_before_sql(tmp_path, call):
    auth = AuthorizationDouble()
    auth.scenario = 'scenario_a'
    runner = Investigator(Settings(db_password='unused'), auth, EvidenceStore(tmp_path), ModelDouble([call]))
    job = Investigation('Which settlements are due?', Scope(scenario=auth.scenario, session_id='scope-check'))
    try:
        runner.run(job)
        assert job.status == 'clarification_required' and 'scenario_a' in job.clarification
        assert 'settlement' in job.clarification and job.budget.statements == 0
    finally:
        runner.close()


def test_dimension_membership_uses_registered_names_independent_of_activity(hand_connection):
    from threading import RLock

    hand_connection.execute("INSERT INTO pg_temp.merchants (merchant_id, merchant_name, category, region) "
                            "VALUES ('shop-a','Novel Merchant','retail','west'), "
                            "('shop-b','Novel Merchant','retail','west')")
    hand_connection.execute("INSERT INTO pg_temp.payment_methods (payment_method, label, role) "
                            "VALUES ('dir-test','Novel Method','test')")
    auth = object.__new__(Authorization)
    auth.lock, auth.scenario, auth.connection = RLock(), 'pg_temp', hand_connection
    auth.methods = read_directory(hand_connection, 'pg_temp', 'payment_methods', 'payment_method', 'label')
    assert bind_filters({'merchant_id':'shop-a','payment_method':'novel method'}, auth) == {
        'merchant_id':'shop-a', 'payment_method':'dir-test'}
    with pytest.raises(DimensionLookupError, match='shop-a, shop-b'):
        bind_filters({'merchant_id':'Novel Merchant'}, auth)
    with pytest.raises(DimensionLookupError, match='No payment method matches'):
        bind_filters({'payment_method':'wrong method'}, auth)


@pytest.mark.integration
def test_unknown_merchant_clarifies_and_known_empty_merchant_publishes(tmp_path):
    class MerchantModel(CompareDouble):
        def next(self, messages, tools, budget):
            if any(tool['function']['name'] == 'analyze_attempts' for tool in tools):
                merchant = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
                return ToolCall('metric', 'analyze_attempts', {
                    'baseline':{'start':'2030-01-01T00:00:00+05:30', 'end':'2030-01-02T00:00:00+05:30'},
                    'comparison':{'start':'2030-01-02T00:00:00+05:30', 'end':'2030-01-03T00:00:00+05:30'},
                    'filters':{'merchant_id':merchant}})
            return super().next(messages, tools, budget)

    settings = Settings.from_root()
    api = create_app(settings, tmp_path, runner_factory=lambda auth, store: Investigator(settings, auth, store, MerchantModel()),
                     store_factory=lambda: EvidenceStore(tmp_path/'evidence'))
    with TestClient(api) as client:
        client.headers['Authorization'] = 'Bearer ' + (tmp_path/'.local/analyst/api_token').read_text()
        sid = client.post('/sessions').json()['session_id']
        session = api.state.sessions.sessions[sid]
        merchant = session.authorization.connection.execute(
            'SELECT merchant_id, merchant_name FROM merchants ORDER BY merchant_id LIMIT 1').fetchone()
        url = f'/sessions/{sid}/investigations'
        iid = client.post(url, json={'question':'No matching merchant in the directory'}).json()['investigation_id']
        path = url + '/' + iid
        session.jobs[iid].future.result(timeout=45)
        first = client.get(path).json()
        assert first['status'] == 'clarification_required' and 'No merchant matches' in first['clarification']
        assert first['budget']['sql_statements'] == 0 and first['evidence'] is None
        assert client.post(path+'/reply', json={'version':first['version'], 'answer':merchant['merchant_name']}).status_code == 200
        session.jobs[iid].future.result(timeout=45)
        measured = client.get(path).json()
        assert measured['status'] == 'verified'
        assert measured['evidence']['request']['filters']['merchant_id'] == merchant['merchant_id']
        assert all(row['rate'] is None and row['attempts'] == 0 for row in measured['evidence']['results']['overall'])
        for field, value in [('merchant_id','unregistered merchant'), ('payment_method','unregistered instrument')]:
            error = client.post(path+'/followup', json={'version':measured['version'], 'action':'filter',
                                                       'filters':{field:value}})
            assert error.status_code == 422 and error.json()['detail']['status'] == 'dimension_filter'
