import pytest

from app.agent.hypotheses import assess_test, propose_test
from app.frontend.renderers import followup_filters
from app.contracts import Filters
from test_source_conflicts import measurement


def test_measured_segment_proposal_and_independent_result():
    parent = measurement()
    filters, rationale = propose_test(parent)
    assert filters == Filters(payer_bank_id='BANK_E', payment_method='CARD')
    assert 'BANK_E' in rationale and 'CARD' in rationale
    child = measurement(filters=filters)
    result = assess_test(parent, child, left_epoch=3, right_epoch=3)
    assert result['status'] == 'supported'
    assert result['evidence_ids'] == [parent.id, child.id]
    assert assess_test(parent, child, left_epoch=3, right_epoch=4)['status'] == 'inconclusive'
    with pytest.raises(ValueError):
        propose_test(child)


def test_followup_text_resolves_only_supported_narrowing():
    parent = measurement()
    assert followup_filters('Show only Bank E card', parent) == Filters(payer_bank_id='BANK_E', payment_method='CARD')
    assert followup_filters('Bank E', parent) == Filters(payer_bank_id='BANK_E')
    for invalid in ('Bank Z', 'Bank E instead of Bank C', 'Bank E except CARD', 'today Bank E'):
        with pytest.raises(ValueError):
            followup_filters(invalid, parent)


def test_bank_names_with_unrelated_ids_use_the_runtime_directory():
    from app.context.banks import BankLookupError, resolve_bank_id

    banks = {'RT-739':'Harbor Credit Union', 'west01':'Harbor Bank', 'east09':'Harbor-Bank'}
    assert resolve_bank_id('harbor_credit union', banks) == 'RT-739'
    assert resolve_bank_id('rt 739', banks) == 'RT-739'
    with pytest.raises(BankLookupError, match='east09, west01'):
        resolve_bank_id('Harbor Bank', banks)
    assert resolve_bank_id('west01', banks) == 'west01'
    with pytest.raises(BankLookupError, match='No bank matches'):
        resolve_bank_id('Bank D', banks)
    with pytest.raises(BankLookupError, match='No bank matches'):
        resolve_bank_id('Harbor', banks)


@pytest.mark.integration
def test_unknown_bank_clarification_accepts_a_runtime_name_via_api(tmp_path):
    from fastapi.testclient import TestClient
    from app.agent.graph import Investigator
    from app.agent.model import ToolCall
    from app.api.main import create_app
    from app.config import Settings
    from app.evidence.store import EvidenceStore
    from test_agent_flow import CompareDouble

    class BankModel(CompareDouble):
        def next(self, messages, tools, budget):
            if any(tool['function']['name'] == 'analyze_attempts' for tool in tools):
                bank = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
                return ToolCall('lookup','analyze_attempts',{
                    'baseline':{'start':'2030-01-01T00:00:00+05:30', 'end':'2030-01-02T00:00:00+05:30'},
                    'comparison':{'start':'2030-01-02T00:00:00+05:30', 'end':'2030-01-03T00:00:00+05:30'},
                    'filters':{'payer_bank_id':bank}})
            return super().next(messages, tools, budget)

    settings = Settings.from_root()
    api = create_app(settings, tmp_path, runner_factory=lambda auth, store: Investigator(settings, auth, store, BankModel()),
                     store_factory=lambda: EvidenceStore(tmp_path/'evidence'))
    with TestClient(api) as client:
        client.headers['Authorization'] = 'Bearer ' + (tmp_path/'.local/analyst/api_token').read_text()
        session = client.post('/sessions').json()
        bank_id, display = next(iter(session['banks'].items()))
        sid = session['session_id']
        start = f'/sessions/{sid}/investigations'
        absent = 'Unlisted bank for clarification check'
        iid = client.post(start, json={'question':absent}).json()['investigation_id']
        path = start + '/' + iid
        job = api.state.sessions.sessions[sid].jobs[iid]
        job.future.result(timeout=45)
        first = client.get(path).json()
        assert first['status'] == 'clarification_required' and 'No bank matches' in first['clarification']
        assert first['budget']['sql_statements'] == 0 and first['evidence'] is None
        assert client.post(path+'/reply', json={'version':first['version'], 'answer':display}).status_code == 200
        job.future.result(timeout=45)
        result = client.get(path).json()
        assert result['status'] == 'verified' and result['evidence']['request']['filters']['payer_bank_id'] == bank_id
        assert all(r['attempts'] == 0 and r['rate'] is None for r in result['evidence']['results']['overall'])
        invalid = client.post(path+'/followup', json={'version':result['version'], 'action':'filter',
                                                      'filters':{'payer_bank_id':absent}})
        assert invalid.status_code == 422 and invalid.json()['detail']['status'] == 'bank_filter'


@pytest.mark.integration
def test_bank_name_followup_recalculates_legacy_empty_result(tmp_path):
    from app.agent.graph import Investigator
    from app.agent.model import ToolCall
    from app.api.main import Followup
    from app.api.session import Investigation, Sessions
    from app.config import Settings
    from app.contracts import Scope
    from app.evidence.store import EvidenceStore
    from test_agent_flow import CompareDouble
    from test_evidence import example

    class NamedBankModel(CompareDouble):
        def next(self, messages, tools, budget):
            call = super().next(messages, tools, budget)
            if call.name == 'analyze_attempts':
                call.arguments['filters'] = {'payer_bank_id':'Bank D', 'payment_method':'UPI'}
            return call

    settings = Settings.from_root()
    sessions = Sessions(settings, tmp_path, lambda auth, store: Investigator(settings, auth, store, NamedBankModel()),
                        store_factory=lambda: EvidenceStore(tmp_path/'evidence'))
    try:
        session = sessions.create()
        scope = Scope(session_id=session.stable_id, scenario=session.authorization.scenario)
        parent = Investigation('Saved bank comparison', scope)
        session.jobs[scope.investigation_id] = parent
        args = example().request.model_dump(mode='json')
        args['filters'] = {'payer_bank_id':'Bank D', 'payment_method':'UPI'}
        # A previously checkpointed call must still describe exactly the SQL it ran.
        dispatch = session.runner.dispatcher.call
        dispatch(ToolCall('old', 'analyze_attempts', args), parent)
        dispatch(ToolCall('publish', 'publish_answer', {'evidence_id':parent.evidence.id}), parent)
        assert all(row['attempts'] == 0 for row in parent.evidence.results['overall'])

        for command in [dict(action='question', question='Show Bank D and UPI again.'),
                        dict(action='filter', filters={'payer_bank_id':'BANK_D'})]:
            child = sessions.followup(session.id, scope.investigation_id, Followup(version=parent.revision, **command))
            child.future.result(timeout=45)
            assert child.status == 'verified', child.error
            assert child.evidence.request.filters == Filters(payer_bank_id='BANK_D', payment_method='UPI')
            assert child.budget.statements > 0 and not child.evidence.reused_from
            totals = child.evidence.results['overall']
            assert all(row['attempts'] > 0 for row in totals)
            if scope.scenario == 'lifecycle_v1':
                assert [(r['successes'], r['attempts']) for r in totals] == [(8594,9056), (8950,9382)]
            assert session.store.get(parent.evidence.id, scope).request.filters.payer_bank_id == 'Bank D'
        with pytest.raises(ValueError, match='narrower'):
            sessions.followup(session.id, scope.investigation_id, Followup(
                version=parent.revision, action='filter', filters={'payer_bank_id':'BANK_E'}))
    finally:
        sessions.shutdown()


def test_saved_bank_label_offers_a_versioned_recalculation(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from app.frontend.api_client import ApiClient

    evidence = measurement(filters=Filters(payer_bank_id='Harbor Credit Union', payment_method='UPI'))
    posts = []
    def request(self, method, path, **kwargs):
        if method == 'POST':
            posts.append((path, kwargs['json']))
            return {'investigation_id':'child'}
        if path.endswith('/child'):
            return {'status':'received', 'question':'Compare RT-739'}
        return {'status':'verified', 'question':'Show Harbor Credit Union', 'version':3,
                'evidence':evidence.model_dump(mode='json')}

    monkeypatch.setattr(ApiClient, 'request', request)
    app = AppTest.from_file(str(Path('app/frontend/main.py').resolve()))
    app.session_state['session'] = {'session_id':'test', 'scenario':'lifecycle_v1',
                                    'banks':{'RT-739':'Harbor Credit Union'}}
    app.session_state['investigation'] = 'saved'
    app.run(timeout=30)
    next(b for b in app.button if b.label == 'Recalculate for RT-739').click().run(timeout=30)
    assert not app.exception and not app.error
    assert posts == [('/sessions/test/investigations/saved/followup',
                      {'action':'filter', 'version':3, 'filters':{'payer_bank_id':'RT-739'}})]


def test_failed_session_switch_keeps_owned_handle_until_detached(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from app.frontend.api_client import ApiClient

    busy = True
    calls = []
    def fake_request(self, method, path, **kwargs):
        calls.append((method, path))
        if method == 'GET' and path == '/local/sessions':
            return {'sessions': [
                {'session_id': 'first', 'title': 'Earlier question', 'last_question_at': 100},
                {'session_id': 'other', 'title': 'Earlier question', 'last_question_at': 100},
                {'session_id': 'empty', 'title': None, 'last_question_at': None},
            ]}
        if path.endswith('/detach'):
            if busy:
                raise RuntimeError('Investigation still running.')
            return {}
        if path == '/local/sessions/other/open':
            raise RuntimeError('Session is unavailable.')
        return {'session_id': 'current', 'resume_id': 'stable',
                'scenario': 'lifecycle_v1', 'investigation_ids': []}

    monkeypatch.setattr(ApiClient, 'request', fake_request)
    app = AppTest.from_file(str(Path('app/frontend/main.py').resolve())).run(timeout=30)
    def press(label):
        next(button for button in app.button if button.label == label).click().run(timeout=30)

    press('Start new session')
    press('Saved sessions')
    assert app.session_state['session']['session_id'] == 'current'
    assert calls[-2:] == [('POST', '/local/sessions'), ('POST', '/sessions/current/detach')]
    busy = False
    press('Saved sessions')
    assert not app.selectbox and not app.text_input
    rows = [b for b in app.button if (b.key or '').startswith('saved-session-')]
    assert [b.key for b in rows] == ['saved-session-first', 'saved-session-other', 'saved-session-empty']
    assert all('Earlier question' in b.label and '1970' in b.label for b in rows[:2])
    assert rows[0].label != rows[1].label and rows[2].label == 'Empty session'
    rows[1].click().run(timeout=30)
    assert calls[-2:] == [('POST', '/local/sessions/other/open'), ('GET', '/local/sessions')]
    assert 'session' not in app.session_state
    assert app.error[0].value == 'Session is unavailable.'
    app.button(key='saved-session-empty').click().run(timeout=30)
    assert calls[-1] == ('POST', '/local/sessions/empty/open')
    assert app.text_area[0].label == 'Business question' and not app.error


def test_chart_click_is_consumed_once_across_poll_and_navigation(monkeypatch):
    from app.frontend import renderers
    state = {}
    widgets = {}
    monkeypatch.setattr(renderers.st,'session_state',state)
    monkeypatch.setattr(renderers.st,'caption',lambda *args: None)
    def draw(figure, *, key, on_select, **options):
        widgets[key] = on_select
    monkeypatch.setattr(renderers.st,'plotly_chart',draw)
    parent = measurement()
    assert renderers.bank_chart_selection(parent) is None
    key, click = next(iter(widgets.items()))
    state[key] = {'selection': {'points': [{'point_index': 0}]}}
    click()
    assert renderers.bank_chart_selection(parent) == Filters(payer_bank_id='BANK_E')
    assert renderers.bank_chart_selection(parent) is None


def test_open_saved_history_reads_selected_investigation(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from app.frontend.api_client import ApiClient
    reads = []
    def read(self, method, path, **kwargs):
        reads.append(path)
        if path.endswith('/history'):
            return {'investigations':[
                dict(investigation_id='original',parent_id=None,created_at=0,status='verified',
                     turns=[dict(role='user',text='How many attempts?'),dict(role='assistant',text='42 attempts.')]),
                dict(investigation_id='filtered',parent_id='original',created_at=1,status='running',
                     turns=[dict(role='user',text='Show just Bank E.')])]}
        return {'status':'received','question':'How many attempts?' if path.endswith('original') else 'Show just Bank E.'}
    monkeypatch.setattr(ApiClient,'request',read)
    app = AppTest.from_file(str(Path('app/frontend/main.py').resolve()))
    app.session_state['session'] = dict(session_id='active',resume_id='saved',scenario='lifecycle_v1')
    app.session_state['history'] = ['original','filtered']
    app.session_state['investigation'] = 'filtered'
    app.run(timeout=30)
    next(b for b in app.button if b.label=='Chat history').click().run(timeout=30)
    assert not app.exception
    assert reads[-1]=='/sessions/active/history'
    assert [m.name for m in app.chat_message] == ['user','assistant','user']
    assert '42 attempts.' in [t.value for t in app.text]
    assert 'Follow-up to: How many attempts?' in [t.value for t in app.text]
    next(b for b in app.button if b.key=='history-open-original').click().run(timeout=30)
    assert app.session_state['investigation'] == 'original'
    assert reads[-1].endswith('/investigations/original')
    assert app.chat_message[0].text[0].value == 'How many attempts?'
    assert not app.text_area
