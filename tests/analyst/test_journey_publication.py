"""Integration checks for the boundary between an explanation and a new measurement."""
import json

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import Investigator
from app.agent.model import ToolCall
from app.api.main import create_app
from app.config import Settings
from app.evidence.store import EvidenceStore


@pytest.mark.integration
def test_followup_reuses_a_finding_while_explicit_new_scope_is_measured(tmp_path):
    settings = Settings.from_root()
    planned = []

    class Planner:
        def next(self, messages, tools, budget):
            names = {t['function']['name'] for t in tools}
            if 'publish_answer' in names:
                result = next(m for m in reversed(messages) if m['role'] == 'tool')
                return ToolCall('p', 'publish_answer', {'evidence_id':json.loads(result['content'])['evidence_id'],
                                                       'views':[]})
            question = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
            planned.append(question)
            args = {'baseline':{'start':'2026-10-01T00:00:00+05:30', 'end':'2026-10-15T00:00:00+05:30'},
                    'comparison':{'start':'2026-10-15T00:00:00+05:30', 'end':'2026-10-29T00:00:00+05:30'},
                    'objective':{'kind':'volume', 'dimension':'reason', 'measure':'failed_attempts'}}
            if ' for bank ID ' in question:
                args['filters'] = {'payer_bank_id': question.split(' for bank ID ')[1].rstrip('?')}
            return ToolCall('q', 'analyze_attempts', args)

    api = create_app(settings, tmp_path, runner_factory=lambda auth, store: Investigator(settings, auth, store, Planner()),
                     store_factory=lambda: EvidenceStore(tmp_path/'measurements'))
    with TestClient(api) as client:
        client.headers['Authorization'] = 'Bearer '+(tmp_path/'.local/analyst/api_token').read_text()
        session = client.post('/sessions').json()
        sid = session['session_id']
        base = '/sessions/'+sid+'/investigations'

        def finish(response):
            response.raise_for_status()
            ident = response.json()['investigation_id']
            api.state.sessions.sessions[sid].jobs[ident].future.result(timeout=125)
            result = client.get(base+'/'+ident).json()
            assert result['status'] == 'verified', result['error']
            return result

        parent_question = 'Which failure reason accounted for the most failures? Text only.'
        parent = finish(client.post(base, json={'question':parent_question}))
        assert parent['dashboard']['blocks'] == []
        path = base+'/'+parent['investigation_id']+'/followup'
        follow = finish(client.post(path, json={'version':parent['version'], 'action':'question',
                                                'question':'What steps should I take to address this?'}))
        assert planned == [parent_question]
        assert follow['budget']['sql_statements'] == 0 and follow['evidence']['reused_from'] == parent['evidence']['id']
        assert follow['narrative']['answer'] == parent['narrative']['recommendations'][0]
        old = client.post(path, json={'version':parent['version'], 'action':'question', 'question':'Why?'})
        assert old.status_code == 409
        bank = next(iter(session['banks']))
        changed_question = f'What should I check for bank ID {bank}?'
        changed = finish(client.post(base+'/'+follow['investigation_id']+'/followup',
                                     json={'version':follow['version'], 'action':'question','question':changed_question}))
        assert planned == [parent_question, changed_question]
        assert changed['evidence']['request']['filters']['payer_bank_id'] == bank
        assert changed['budget']['sql_statements'] > 0 and not changed['evidence'].get('reused_from')
        for row in (parent, follow, changed):
            assert row['narrative']['guidance']['evidence_id'] == row['evidence']['id']
            assert row['narrative']['guidance']['reference'] == row['dashboard']['finding_ref']
