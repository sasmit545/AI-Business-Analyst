import pytest
import json
from contextlib import nullcontext
from types import SimpleNamespace
from app.config import Settings

from scripts import evaluate_analyst as evaluator
from test_evidence import example


@pytest.mark.parametrize('scenario',['scenario_a','scenario_a_dirty'])
def test_policy_block_is_reported_before_parsing_missing_evidence(scenario,tmp_path,monkeypatch):
    answer={'status':'blocked','error':'One analytical bundle is permitted per investigation',
            'evidence':None,'narrative':None,'dashboard':None}
    (tmp_path/'reports/analyst').mkdir(parents=True)
    monkeypatch.setattr(evaluator,'ROOT',tmp_path)
    monkeypatch.setattr(evaluator,'SCENARIOS',[scenario])
    monkeypatch.setattr(evaluator.sys,'argv',['evaluate_analyst.py','--live-model'])
    monkeypatch.setattr(evaluator.Settings,'from_root',lambda root:Settings(db_password='unused',evidence_dir=tmp_path/'evidence'))
    monkeypatch.setattr(evaluator.admin,'select_scenario',lambda scenario:None)
    monkeypatch.setattr(evaluator,'Authorization',lambda settings:SimpleNamespace(scenario='lifecycle_v1',close=lambda:None))
    monkeypatch.setattr(evaluator,'check_sources',lambda:{'changed':[]})
    monkeypatch.setattr(evaluator,'live_api',lambda settings:nullcontext(None))
    monkeypatch.setattr(evaluator,'live_question',lambda client,question:answer)
    with pytest.raises(AssertionError,match='One analytical bundle'):
        evaluator.main()
    report=json.loads((tmp_path/'reports/analyst/live_acceptance.json').read_text())
    assert report['status']=='failed'
    assert report['last_investigation']['error']==answer['error']
    assert report['restored_selection']['schema']=='lifecycle_v1'


def test_verified_without_publication_is_not_accepted():
    with pytest.raises(AssertionError,match='published evidence'):
        evaluator.published_evidence({'status':'verified','error':None,'evidence':None},'scenario_a',example().request)


@pytest.mark.parametrize('scenario,status',[('scenario_a','verified'),('scenario_a_dirty','blocked')])
def test_published_answer_reaches_independent_oracle_checks(scenario,status):
    from app.contracts import Scope
    evidence=example(Scope(scenario=scenario,session_id='evaluation'))
    answer={'status':status,'error':None,'evidence':evidence.model_dump(mode='json'),
            'narrative':{'answer':'Checked later against independent results'},'dashboard':{'components':[]}}
    assert evaluator.published_evidence(answer,scenario,evidence.request)==evidence
