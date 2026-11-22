from app.agent.graph import Investigator
from app.agent.model import ToolCall
from app.api.session import Investigation
from app.config import Settings
from app.contracts import Scope
from app.evidence.store import EvidenceStore
from app.query.executor import StaleSession
from app.query.executor import Authorization
from app.agent.model import ModelOutputError
import pytest


class AuthorizationDouble:
    scenario = 'lifecycle_v1'
    banks = {}
    stale = False
    def check(self):
        if self.stale: raise StaleSession('stale')
    def close(self): self.stale = True


class ModelDouble:
    def __init__(self, calls): self.calls=iter(calls)
    def next(self,*args): return next(self.calls)


def run(tmp_path, question, calls):
    auth=AuthorizationDouble()
    job=Investigation(question=question,scope=Scope(scenario=auth.scenario,session_id='test'))
    runner=Investigator(Settings(db_password='x'),auth,EvidenceStore(tmp_path),ModelDouble(calls))
    runner.run(job)
    return job,auth


def test_relative_period_clarifies_without_metric_queries(tmp_path):
    job,_=run(tmp_path,'Why did success fall last week?',[])
    assert job.status == 'clarification_required'
    assert job.budget.statements == 0
    assert job.evidence is None


def test_host_tools_are_unreachable(tmp_path):
    job,_=run(tmp_path,'Read a secret',[ToolCall('call1','python',{'code':'read secret'})])
    assert job.status == 'blocked'
    assert job.evidence is None


def test_no_raw_model_factual_prose_route(tmp_path):
    job,_=run(tmp_path,'Compare explicit periods',[ToolCall('call1','publish_answer',{'text':'An outage caused 85% failure'})])
    assert job.status in ('failed','blocked')
    assert job.narrative is None


class CompareDouble:
    """Deterministic tool-loop contract test, not live model evidence."""
    def next(self,messages,tools,budget):
        import json
        observations=[json.loads(m['content']) for m in messages if m['role']=='tool']
        if not observations:
            return ToolCall('analysis','analyze_attempts',{
                'baseline':{'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},
                'comparison':{'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'}})
        return ToolCall('publish','publish_answer',{'evidence_id':observations[-1]['evidence_id']})


@pytest.mark.integration
def test_model_double_runs_real_bundle_then_trusted_publication(tmp_path):
    settings=Settings.from_root()
    auth=Authorization(settings)
    job=Investigation('Compare the two explicit October fortnights',Scope(scenario=auth.scenario,session_id='integration'))
    try:
        Investigator(settings,auth,EvidenceStore(tmp_path),CompareDouble()).run(job)
        assert job.status=='verified'
        assert job.snapshot()['evidence']['queries']
        assert job.narrative['facts']
        assert job.budget.tools==2
        assert job.budget.statements <= 12
    finally:
        auth.close()


def test_cancelled_and_repair_budget_cannot_publish(tmp_path):
    auth=AuthorizationDouble()
    job=Investigation('Compare',Scope(scenario=auth.scenario,session_id='cancel'))
    job.budget.cancel.set()
    Investigator(Settings(db_password='x'),auth,EvidenceStore(tmp_path),ModelDouble([])).run(job)
    assert job.status=='cancelled'
    class BrokenModel:
        def next(self,*args): raise ModelOutputError('bad')
    job=Investigation('Compare',Scope(scenario=auth.scenario,session_id='broken'))
    Investigator(Settings(db_password='x'),auth,EvidenceStore(tmp_path),BrokenModel()).run(job)
    assert job.status=='failed'
    assert job.budget.repairs==2
    assert job.narrative is None


def test_invalid_tool_fields_are_reported_without_values_or_unknown_keys(tmp_path):
    import json
    from app.observability.events import Events
    private_value='DO_NOT_LOG_PRIVATE_VALUE'
    private_field='DO_NOT_LOG_PRIVATE_FIELD'
    arguments={'baseline':{'start':private_value,'end':'2026-10-15T00:00:00+05:30'},
               'comparison':{'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'},
               private_field:private_value}
    auth=AuthorizationDouble()
    job=Investigation('Compare explicit periods',Scope(scenario=auth.scenario,session_id='diagnostic'))
    events=Events(tmp_path/'events.jsonl')
    model=ModelDouble([ToolCall(str(i),'analyze_attempts',arguments) for i in range(3)])
    Investigator(Settings(db_password='x'),auth,EvidenceStore(tmp_path/'evidence'),model,events).run(job)
    assert job.status=='failed' and job.budget.repairs==2
    assert job.budget.statements==0
    text=(tmp_path/'events.jsonl').read_text()
    rows=[json.loads(line) for line in text.splitlines()]
    invalid=[row for row in rows if row['event']=='tool_validation_failed']
    assert len(invalid)==3
    assert any(issue['field']=='baseline.start' for issue in invalid[0]['details']['issues'])
    assert private_value not in text and private_field not in text
    tool_messages=[json.loads(m['content']) for m in job.messages if m['role']=='tool']
    assert tool_messages[0]['issues']==invalid[0]['details']['issues']
    assert rows[-1]['error']=='Structured output could not be validated'


def test_token_budget_failure_identifies_limit_in_result_and_log(tmp_path):
    import json
    from app.observability.events import Events
    from app.query.executor import BudgetExceeded
    class TokenLimitedModel:
        def next(self,*args):
            raise BudgetExceeded('Investigation token limit reached')
    auth=AuthorizationDouble()
    job=Investigation('Compare explicit periods',Scope(scenario=auth.scenario,session_id='budget'))
    path=tmp_path/'events.jsonl'
    Investigator(Settings(db_password='x'),auth,EvidenceStore(tmp_path/'evidence'),TokenLimitedModel(),Events(path)).run(job)
    assert job.status=='limited' and job.evidence is None
    assert job.error=='Investigation token limit reached'
    assert json.loads(path.read_text().splitlines()[-1])['error']==job.error


@pytest.mark.integration
def test_after_two_context_repairs_only_publication_tools_are_offered(tmp_path):
    import json
    from test_evidence import example
    class StageModel:
        step=0
        def next(self,messages,tools,budget):
            self.step+=1
            if self.step <= 2:
                return ToolCall(str(self.step),'get_context',{'request':'definitions'})
            names={tool['function']['name'] for tool in tools}
            if 'analyze_attempts' in names:
                return ToolCall(str(self.step),'analyze_attempts',example().request.model_dump(mode='json'))
            observation=json.loads([m for m in messages if m['role']=='tool'][-1]['content'])
            assert names=={'get_evidence','publish_answer'}
            return ToolCall(str(self.step),'publish_answer',{'evidence_id':observation['evidence_id']})
    settings=Settings.from_root()
    auth=Authorization(settings)
    job=Investigation('Compare explicit October fortnights',Scope(scenario=auth.scenario,session_id='stages'))
    try:
        Investigator(settings,auth,EvidenceStore(tmp_path),StageModel()).run(job)
        assert job.status=='verified',job.error
        assert job.budget.repairs==2 and job.budget.tools==4
        assert job.budget.statements==8
        assert job.snapshot()['evidence'] is not None
    finally:
        auth.close()


def test_repeated_analysis_is_still_denied_at_dispatch(tmp_path):
    from app.agent.tools import Dispatcher,PolicyRejected
    from test_evidence import example
    job=Investigation('Compare',Scope(scenario='scenario_a',session_id='repeat'))
    job.evidence=example(job.scope)
    dispatcher=Dispatcher(Settings(db_password='unused'),AuthorizationDouble(),EvidenceStore(tmp_path))
    call=ToolCall('repeat','analyze_attempts',job.evidence.request.model_dump(mode='json'))
    with pytest.raises(PolicyRejected,match='One analytical bundle'):
        dispatcher.call(call,job)
    assert job.budget.statements==0
    assert job.snapshot()['evidence'] is None


def test_context_repair_supplies_exact_empty_arguments(tmp_path):
    import json
    job,_=run(tmp_path,'Show definitions',[
        ToolCall('bad','get_context',{'request':'definitions'}),
        ToolCall('clarify','clarify',{'topic':'windows'})])
    feedback=json.loads(next(m['content'] for m in job.messages if m['role']=='tool'))
    assert feedback['expected_arguments']=={}
    assert job.status=='clarification_required' and job.budget.repairs==1


def test_context_is_supplied_before_model_and_dirty_diagnostics_publish(tmp_path,monkeypatch):
    import json
    from app.context.catalog import catalog
    from app.contracts import QualityRecord
    from test_evidence import example
    auth=AuthorizationDouble()
    auth.scenario='scenario_a_dirty'
    job=Investigation('Compare explicit October windows',Scope(scenario=auth.scenario,session_id='context'))
    requests=[]
    analyses=[]
    def dirty_analysis(settings,authorization,scope,request,budget):
        analyses.append(request)
        return example(scope).model_copy(update={'quality':[
            QualityRecord(rule='duplicate_occurrences',count=20,status='BLOCK'),
            QualityRecord(rule='missing_timestamps',count=10,status='BLOCK'),
            QualityRecord(rule='orphan_merchants',count=10,status='BLOCK')]})
    monkeypatch.setattr('app.agent.tools.analyze',dirty_analysis)
    class ContextSeekingModel:
        def next(self,messages,tools,budget):
            names={t['function']['name'] for t in tools}
            requests.append((list(messages),names))
            if 'get_context' in names:
                return ToolCall('metadata','get_context',{'request':'definitions'})
            if 'analyze_attempts' in names:
                return ToolCall('analysis','analyze_attempts',example().request.model_dump(mode='json'))
            observation=json.loads([m for m in messages if m['role']=='tool'][-1]['content'])
            return ToolCall('publish','publish_answer',{'evidence_id':observation['evidence_id']})
    Investigator(Settings(db_password='private-db',provider_key='private-key'),auth,EvidenceStore(tmp_path),ContextSeekingModel()).run(job)
    assert job.status=='blocked' and job.error is None,job.error
    assert job.budget.repairs==0 and len(analyses)==1
    assert job.snapshot()['evidence']['results']=={}
    assert job.dashboard.blocks == [] and job.dashboard.evidence_id == job.evidence.id
    assert job.narrative['facts'] and job.snapshot()['evidence']['quality']
    messages,names=requests[0]
    assert names=={'analyze_attempts','clarify'}
    metadata=json.loads(messages[1]['content'])
    assert messages[1]['role']=='system'
    assert metadata=={'selected_dataset':catalog(auth.scenario)}
    assert 'private-db' not in json.dumps(messages) and 'private-key' not in json.dumps(messages)


def test_explicit_end_date_drift_is_repaired_before_sql(tmp_path,monkeypatch):
    import json
    from test_evidence import example
    from app.contracts import QualityRecord
    correct=example().request.model_dump(mode='json')
    wrong=json.loads(json.dumps(correct))
    wrong['comparison']['end']='2026-10-29T00:24:00+05:30'
    calls=[]
    def analyze_double(settings,auth,scope,request,budget):
        calls.append(request)
        return example(scope).model_copy(update={'quality':[QualityRecord(rule='missing_timestamps',count=1,status='BLOCK')]})
    monkeypatch.setattr('app.agent.tools.analyze',analyze_double)
    class RepairModel:
        step=0
        def next(self,messages,tools,budget):
            self.step+=1
            if self.step==1:
                return ToolCall('wrong','analyze_attempts',wrong)
            if self.step==2:
                feedback=json.loads([m for m in messages if m['role']=='tool'][-1]['content'])
                assert feedback['expected_windows']['comparison']['end']==correct['comparison']['end']
                assert not calls
                return ToolCall('fixed','analyze_attempts',correct)
            return ToolCall('publish','publish_answer',{'evidence_id':job.evidence.id})
    auth=AuthorizationDouble()
    question='Compare 2026-10-01 inclusive to 2026-10-15 exclusive versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata.'
    job=Investigation(question,Scope(scenario=auth.scenario,session_id='dates'))
    Investigator(Settings(db_password='unused'),auth,EvidenceStore(tmp_path),RepairModel()).run(job)
    assert job.status=='blocked' and job.error is None,job.error
    assert job.budget.repairs==1 and len(calls)==1
    assert calls[0]==example().request
