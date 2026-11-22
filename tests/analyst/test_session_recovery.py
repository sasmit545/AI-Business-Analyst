import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from app.api.main import create_app
from app.config import Settings
from app.evidence.postgres_store import open_writer


def test_resume_reauthorizes_with_private_key_and_invalidates_previous_handle(tmp_path):
    settings = Settings.from_root()
    def service():
        return TestClient(create_app(root=tmp_path, settings=settings))
    def authorize(client):
        token = (tmp_path / '.local/analyst/api_token').read_text()
        client.headers['Authorization'] = 'Bearer ' + token
    with service() as first:
        authorize(first)
        created = first.post('/sessions').json()
        resume = {'session_id':created['resume_id'], 'resume_key':created['resume_key']}
        old = '/sessions/' + created['session_id']
        iid = first.post(old+'/investigations',json={'question':'Why did success fall last week?'}).json()['investigation_id']
        for _ in range(100):
            if first.get(old+'/investigations/'+iid).json()['status']=='clarification_required':
                break
            time.sleep(.05)
        assert first.post('/sessions/resume', json=resume).status_code==409
    with service() as second:
        authorize(second)
        assert second.get(old+'/investigations/'+iid).status_code==404
        assert second.post('/sessions/resume',json={**resume,'resume_key':'x'*48}).status_code==404
        resumed=second.post('/sessions/resume',json=resume)
        assert resumed.status_code==200, resumed.text
        new=resumed.json()
        assert new['session_id']!=created['session_id'] and new['investigation_ids']==[iid]
        current='/sessions/'+new['session_id']
        assert second.get(current+'/investigations/'+iid).json()['status']=='clarification_required'
        assert second.delete(current).is_success
        assert second.post('/sessions/resume',json=resume).status_code in (404,409)


def test_two_api_instances_cannot_claim_the_same_saved_session(tmp_path):
    settings=Settings.from_root()
    roots=[tmp_path/'first', tmp_path/'second']
    with (TestClient(create_app(root=roots[0],settings=settings)) as first,
          TestClient(create_app(root=roots[1],settings=settings)) as second):
        for client,root in zip((first,second),roots):
            client.headers['Authorization']='Bearer '+(root/'.local/analyst/api_token').read_text()
        saved=first.post('/sessions').json()
        assert first.post('/sessions/'+saved['session_id']+'/detach').is_success
        credentials={'session_id':saved['resume_id'],'resume_key':saved['resume_key']}
        start=Barrier(2)
        def claim(client):
            start.wait(timeout=10)
            return client,client.post('/sessions/resume',json=credentials)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(claim,(first,second)))
        assert sorted(response.status_code for _,response in results)==[200,409]
        client,winner=next((client,response) for client,response in results if response.is_success)
        assert client.delete('/sessions/'+winner.json()['session_id']).is_success


def test_local_picker_restores_existing_work_after_restart_and_refresh(tmp_path):
    settings = Settings.from_root()
    directory = tmp_path/'.local/analyst'

    def service():
        return TestClient(create_app(root=tmp_path, settings=settings))

    def headers(filename):
        return {'Authorization': 'Bearer '+(directory/filename).read_text()}

    with service() as first:
        ordinary = headers('api_token')
        operator = headers('workspace_token')
        legacy = first.post('/sessions', headers=ordinary).json()
        path = '/local/sessions/'+legacy['resume_id']+'/open'
        assert first.get('/local/sessions').status_code == 401
        assert first.get('/local/sessions', headers=ordinary).status_code == 401
        assert first.post(path, headers=ordinary).status_code == 401
        assert first.post(path, headers=operator).status_code == 409
        question = 'Why did success fall last week?'
        active = '/sessions/'+legacy['session_id']
        iid = first.post(active+'/investigations', headers=ordinary, json={'question': question}).json()['investigation_id']
        first.app.state.sessions.sessions[legacy['session_id']].jobs[iid].future.result(timeout=15)
        empty = first.post('/local/sessions', headers=operator).json()
        assert 'resume_key' not in empty
    with service() as second:
        operator = headers('workspace_token')
        ordinary = headers('api_token')
        saved = second.get('/local/sessions', headers=operator).json()['sessions']
        rows = {row['session_id']: row for row in saved}
        assert rows[legacy['resume_id']]['title'] == question
        assert rows[empty['resume_id']]['title'] is None
        assert set(rows[legacy['resume_id']]) == {'title', 'session_id', 'last_question_at'}
        reopened = second.post(path, headers=operator).json()
        assert reopened['investigation_ids'] == [iid] and 'resume_key' not in reopened
        refreshed = second.post(path, headers=operator).json()
        assert second.get('/sessions/'+reopened['session_id']+'/history', headers=ordinary).status_code == 404
        handle = '/sessions/'+refreshed['session_id']
        turns = second.get(handle+'/history', headers=ordinary).json()['investigations'][0]['turns']
        assert turns[0] == {'role': 'user', 'text': question}
        assert second.delete(handle, headers=ordinary).is_success
        assert second.post(path, headers=operator).status_code == 404
        assert legacy['resume_id'] not in [r['session_id'] for r in second.get('/local/sessions', headers=operator).json()['sessions']]
        unused = second.post('/local/sessions/'+empty['resume_id']+'/open', headers=operator).json()
        assert second.delete('/sessions/'+unused['session_id'], headers=ordinary).is_success


def test_local_workspace_rejects_other_owners_and_old_dataset_versions(tmp_path):
    settings = Settings.from_root()
    ids = [uuid4().hex for _ in range(3)]
    with open_writer(settings) as writer, TestClient(create_app(root=tmp_path, settings=settings)) as client:
        client.headers['Authorization'] = 'Bearer '+(tmp_path/'.local/analyst/workspace_token').read_text()
        try:
            for sid, subject, generation_offset, import_offset in [
                    (ids[0], 'other', 0, 0), (ids[1], 'local-operator', -1, 0),
                    (ids[2], 'local-operator', 0, -1)]:
                writer.execute("""INSERT INTO analyst_meta.sessions
                    (session_id,subject,scenario,generation,import_epoch,key_digest,owner_token)
                    SELECT %s,%s,scenario,generation+%s,import_epoch+%s,'test','test'
                    FROM analyst_meta.control WHERE ready""", (sid,subject,generation_offset,import_offset))
            listed = {row['session_id'] for row in client.get('/local/sessions').json()['sessions']}
            assert listed.isdisjoint(ids)
            for sid in ids:
                assert client.post('/local/sessions/'+sid+'/open').status_code in (404,409)
        finally:
            writer.execute('DELETE FROM analyst_meta.sessions WHERE session_id=ANY(%s)', (ids,))
