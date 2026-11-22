from fastapi.testclient import TestClient
from app.api.main import create_app
from app.config import Settings
from app.evidence.store import EvidenceStore
from app.agent.graph import Investigator
from app.agent.model import ToolCall
from test_agent_flow import AuthorizationDouble, ModelDouble


def client_for(tmp_path):
    settings=Settings(db_password='x',evidence_dir=tmp_path/'evidence')
    def runner(auth,store):
        return Investigator(settings,auth,store,ModelDouble([ToolCall('one','clarify',{'topic':'windows'})]))
    return TestClient(create_app(settings=settings,root=tmp_path,runner_factory=runner,
                                 authorization_factory=lambda settings:AuthorizationDouble(),
                                 store_factory=lambda:EvidenceStore(settings.evidence_dir)))


def test_local_capability_required_and_unknown_request_fields_rejected(tmp_path):
    with client_for(tmp_path) as client:
        assert client.post('/sessions').status_code == 401
        token=(tmp_path/'.local/analyst/api_token').read_text()
        client.headers['Authorization']='Bearer '+token
        session=client.post('/sessions').json()
        sid=session['session_id']
        assert client.post(f'/sessions/{sid}/investigations',json={'question':'question','schema':'scenario_b'}).status_code == 422
        response=client.post(f'/sessions/{sid}/investigations',json={'question':'Why did success fall last week?'}).json()
        iid=response['investigation_id']
        job=client.app.state.sessions.sessions[sid].jobs[iid]
        job.future.result(timeout=10)
        result=client.get(f'/sessions/{sid}/investigations/{iid}').json()
        assert result['status']=='clarification_required'
        assert result['budget']['sql_statements']==0
        assert result['evidence'] is None
        assert client.post(f'/sessions/{sid}/investigations/{iid}/reply',json={'version':999,'answer':'October'}).status_code==409
        assert client.get(f'/sessions/{sid}/evidence/not-owned').status_code==404


def test_stale_session_clears_prior_results(tmp_path):
    with client_for(tmp_path) as client:
        client.headers['Authorization']='Bearer '+(tmp_path/'.local/analyst/api_token').read_text()
        sid=client.post('/sessions').json()['session_id']
        session=client.app.state.sessions.sessions[sid]
        session.authorization.stale=True
        response=client.post(f'/sessions/{sid}/investigations',json={'question':'Compare'})
        assert response.status_code==409
        assert response.json()['detail']['status']=='stale'
        assert client.get(f'/sessions/{sid}/history').status_code==409


def test_untrusted_host_and_origin_denied(tmp_path):
    with client_for(tmp_path) as client:
        token=(tmp_path/'.local/analyst/api_token').read_text()
        assert client.post('/sessions',headers={'Authorization':'Bearer '+token,'Host':'evil.example'}).status_code==403
        assert client.post('/sessions',headers={'Authorization':'Bearer '+token,'Origin':'https://evil.example'}).status_code==403


def test_valid_clarification_reply_preserves_budgets_and_advances_version(tmp_path):
    with client_for(tmp_path) as client:
        client.headers['Authorization']='Bearer '+(tmp_path/'.local/analyst/api_token').read_text()
        sid=client.post('/sessions').json()['session_id']
        initial=client.post(f'/sessions/{sid}/investigations',json={'question':'Why did success fall last week?'}).json()
        iid=initial['investigation_id']
        job=client.app.state.sessions.sessions[sid].jobs[iid]
        job.future.result(timeout=10)
        budget=job.budget
        response=client.post(f'/sessions/{sid}/investigations/{iid}/reply',json={'version':1,'answer':'Attempt success for October 1-14 versus October 15-28 in Asia/Kolkata.'})
        assert response.status_code==200
        job.future.result(timeout=10)
        assert job.scope.version==2
        assert job.budget is budget
        assert job.budget.tools==1
        assert client.post(f'/sessions/{sid}/investigations/{iid}/reply',json={'version':1,'answer':'Repeated reply'}).status_code==409
