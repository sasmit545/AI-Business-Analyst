from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import Investigator
from app.api.main import create_app
from app.api.session import Investigation
from app.config import Settings
from app.evidence.render_claims import narrative
from app.ui_specs.models import Layout
from test_agent_flow import CompareDouble
from test_source_conflicts import measurement


def test_transcript_only_publishes_visible_turns_and_matches_displayed_headline():
    e = measurement()
    job = Investigation('What was the conversion rate?', e.scope, status='verified', evidence=e,
                        narrative=narrative(e), dashboard=Layout(version='1', evidence_id=e.id,
                        blocks=[], headline_measure='rate'))
    job.messages = [{'role':role, 'content':'private harness data'} for role in ('system','user','tool','assistant')]
    job.future = Future()
    pending = job.history_entry()
    assert pending['status']=='running' and pending['turns']==[{'role':'user','text':job.question}]
    job.future.set_result(None)
    assert job.history_entry()['turns'][-1]['text']=='24-hour order conversion: 90.0000% in the baseline and 70.0000% in the comparison.'
    assert 'private harness data' not in str(job.history_entry())
    job.fail('cancelled', 'Investigation cancelled')
    assert job.history_entry()['turns'][-1]=={'role':'assistant','text':'Investigation cancelled'}
    assert '90.0000%' not in str(job.history_entry())


def test_older_saved_question_with_no_recorded_exchanges_can_be_read():
    e = measurement()
    job = Investigation('Clarify my question', e.scope, status='clarification_required',
                        clarification='Which denominator?')
    legacy = job.saved_state()
    legacy.pop('clarification_exchanges')
    entry = Investigation.restore(legacy, None).history_entry()
    assert [turn['text'] for turn in entry['turns']] == [job.question, job.clarification]


@pytest.mark.integration
def test_session_transcript_survives_restart_without_reexecuting(tmp_path):
    settings = Settings.from_root()
    def service():
        return TestClient(create_app(settings=settings, root=tmp_path, runner_factory=lambda auth, store:
                                     Investigator(settings, auth, store, CompareDouble())))

    def authorize(client):
        client.headers['Authorization'] = 'Bearer '+(tmp_path/'.local/analyst/api_token').read_text()

    with service() as client:
        assert client.get('/sessions/unknown/history').status_code == 401
        authorize(client)
        opened = client.post('/sessions').json()
        sid = opened['session_id']
        prefix = '/sessions/'+sid
        resume = {'session_id': opened['resume_id'], 'resume_key': opened['resume_key']}
        assert client.get(prefix+'/history').json() == {'investigations':[]}
        question = 'How many payments succeeded last week?'
        iid = client.post(prefix+'/investigations', json={'question':question}).json()['investigation_id']
        job = client.app.state.sessions.sessions[sid].jobs[iid]
        job.future.result(timeout=90)
        turns = client.get(prefix+'/history').json()['investigations'][0]['turns']
        assert turns==[{'role':'user','text':question},{'role':'assistant','text':job.clarification}]
        path = prefix+'/investigations/'+iid
        reply = 'Compare October 1 to 14 against October 15 to 28, 2026, in Asia/Kolkata.'
        assert client.post(path+'/reply',json={'version':1,'answer':reply}).is_success
        job.future.result(timeout=125)
        assert job.status=='verified', job.error
        child = client.post(path+'/followup',json={'version':2,'action':'filter','filters':{'payment_method':'CARD'}})
        assert child.is_success
        child_id = child.json()['investigation_id']
        client.app.state.sessions.sessions[sid].jobs[child_id].future.result(timeout=125)
        expected = client.get(prefix+'/history').json()
        root, narrowed = expected['investigations']
        assert root['turns']==[*turns,{'role':'user','text':reply},{'role':'assistant','text':job.narrative['answer']}]
        assert narrowed['parent_id']==iid and narrowed['status']=='verified'
        charges = job.snapshot()['budget']
        assert client.get(prefix+'/history').json()==expected and job.snapshot()['budget']==charges
        other = '/sessions/'+client.post('/sessions').json()['session_id']
        assert client.get(other+'/history').json()=={'investigations':[]}
        assert client.delete(other).is_success
    with service() as restored:
        authorize(restored)
        assert restored.get(prefix+'/history').status_code==404
        current = '/sessions/'+restored.post('/sessions/resume',json=resume).json()['session_id']
        assert restored.get(current+'/history').json()==expected
        assert restored.get(current+'/investigations/'+iid).json()['budget']==charges
        assert restored.delete(current).is_success
        assert restored.get(current+'/history').status_code==404
