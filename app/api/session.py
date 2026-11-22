import json
import threading
import time
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import wraps
from uuid import uuid4

from app.agent.graph import Investigator
from app.agent.objective import Objective, continuation, inferred_objective
from app.api.recovery import SessionLease, saved_sessions
from app.context.banks import matching_bank_ids
from app.context.dimensions import bind_filters
from app.contracts import Scope, AnalysisRequest, LifecycleRequest
from app.evidence.render_claims import narrative, publication_headline, publication_narrative
from app.evidence.verify import verify_evidence
from app.ui_specs.validate import read_layout, validate_layout
from app.ui_specs.results import result_catalog, selected_rows
from app.ui_specs.models import Measure
from app.evidence.store import EvidenceStore
from app.observability.events import Events
from app.query.executor import Authorization, Budget, StaleSession

ACTIVE = {'received','running'}


class ResultVersionChanged(ValueError):
    """A user action names a result revision that has already advanced."""


def session_operation(method):
    """Keep detach/resume from racing a request that has obtained a handle."""
    @wraps(method)
    def guarded(self,*args,**kwargs):
        with self.lock:
            return method(self,*args,**kwargs)
    return guarded


@dataclass
class Investigation:
    question: str
    scope: Scope
    status: str = 'received'
    budget: Budget = field(default_factory=Budget)
    messages: list = field(default_factory=list)
    evidence: object = None
    narrative: dict | None = None
    dashboard: object = None
    clarification: str | None = None
    error: str | None = None
    future: object = None
    lock: object = field(default_factory=threading.RLock)
    created_at: float = field(default_factory=time.time)
    revision: int = 1
    parent_id: str | None = None
    requested_analysis: AnalysisRequest | LifecycleRequest | None = None
    focus_measure: Measure | None = None
    adaptive: bool = False
    test_started: bool = False
    hypothesis: dict | None = None
    clarification_exchanges: list[dict[str, str]] = field(default_factory=list)
    objective: Objective | None = None
    response: str = 'answer'

    def fail(self,status,message):
        with self.lock:
            if self.status == 'stale' or (self.status == 'cancelled' and status != 'stale'):
                return
            self.status,self.error = status,message
            self.narrative,self.dashboard = None,None

    def invalidate(self):
        self.budget.cancel.set()
        self.fail('stale','Session authorization expired; start a new session')
        self.evidence = None

    def snapshot(self):
        with self.lock:
            result=self._snapshot()
            if self.status in ('running', 'limited', 'failed') and self.evidence is not None:
                # A completed SQL result can survive interruption during publication.
                try:
                    result['verified_finding'] = narrative(self.evidence)['answer']
                except (ValueError, KeyError, TypeError, IndexError):
                    pass
            if self.visible_status() != self.status:
                result.update(status='running', evidence=None, narrative=None, dashboard=None, hypothesis=None)
            return result

    def visible_status(self):
        if self.future and not self.future.done() and self.status not in ACTIVE | {'cancelled','stale'}:
            return 'running'
        return self.status

    def history_entry(self):
        with self.lock:
            status = self.visible_status()
            turns = [{'role':'user', 'text':self.question}]
            for exchange in self.clarification_exchanges:
                if exchange['prompt']:
                    turns.append({'role':'assistant', 'text':exchange['prompt']})
                turns.append({'role':'user', 'text':exchange['reply']})
            if status == 'clarification_required' and self.clarification:
                turns.append({'role':'assistant', 'text':self.clarification})
            elif status in ('verified', 'blocked') and self.narrative and self.evidence:
                answer = self.narrative['answer']
                if self.dashboard and self.dashboard.objective is None:
                    answer = publication_headline(self.evidence, self.dashboard, answer)
                turns.append({'role':'assistant', 'text':answer})
            elif status not in ACTIVE and self.error:
                turns.append({'role':'assistant', 'text':self.error})
            return {'investigation_id':self.scope.investigation_id, 'parent_id':self.parent_id, 'created_at':self.created_at,
                    'status':status, 'turns':turns}

    def _snapshot(self):
        published = self.narrative is not None and self.status in ('verified','blocked')
        return {'investigation_id':self.scope.investigation_id,'status':self.status,'question':self.question,
                'progress':('Planning presentation from executed results' if self.evidence else
                            'Executing registered analysis' if self.budget.statements else 'Resolving the question'),
                'scope':self.scope.model_dump(mode='json'),'version':self.revision,
                'parent_id':self.parent_id,'hypothesis':self.hypothesis if published else None,
                'clarification':self.clarification,'error':self.error,
                'narrative':self.narrative if published else None,
                'evidence':self.evidence.model_dump(mode='json') if published else None,
                'dashboard':self.dashboard.model_dump(mode='json') if published else None,
                'budget':{'sql_statements':self.budget.statements,'tool_calls':self.budget.tools,
                          'repairs':self.budget.repairs,'tokens_reserved':self.budget.tokens_reserved}}

    def can_test_segment(self):
        if (self.visible_status() != 'verified' or not self.evidence or self.adaptive or self.test_started
                or self.evidence.request.metric != 'attempt_success' or self.budget.statements + 4 > 12
                or self.budget.tools + 2 > 10 or time.monotonic() - self.budget.started >= 120):
            return False
        filters = self.evidence.request.filters
        if filters.payer_bank_id and filters.payment_method:
            return False
        periods = [set(), set()]
        for row in self.evidence.results['segments']:
            if row['rate'] is not None:
                periods[row['period']].add((row['payer_bank_id'], row['payment_method']))
        return bool(periods[0] & periods[1])

    def saved_state(self):
        with self.lock:
            return dict(question=self.question, scope=self.scope.model_dump(mode='json'),
                        status=self.status, revision=self.revision, created_at=self.created_at,
                        messages=self.messages, clarification=self.clarification, error=self.error,
                        clarification_exchanges=self.clarification_exchanges,
                        parent_id=self.parent_id, adaptive=self.adaptive, test_started=self.test_started,
                        focus_measure=self.focus_measure,
                        objective=self.objective.model_dump() if self.objective else None, response=self.response,
                        hypothesis=self.hypothesis, evidence_id=self.evidence.id if self.evidence else None,
                        dashboard=self.dashboard.model_dump(mode='json') if self.dashboard else None,
                        request=self.requested_analysis.model_dump(mode='json') if self.requested_analysis else None,
                        deadline=time.time()+120-(time.monotonic()-self.budget.started),
                        budget=self._snapshot()['budget'])

    @classmethod
    def restore(cls, data, store):
        scope = Scope.model_validate(data['scope'])
        budget = Budget(started=time.monotonic()-(time.time()+120-data['deadline']),
                        statements=data['budget']['sql_statements'], tools=data['budget']['tool_calls'],
                        repairs=data['budget']['repairs'], tokens_reserved=data['budget']['tokens_reserved'])
        job = cls(data['question'], scope, status=data['status'], budget=budget)
        job.focus_measure = data.get('focus_measure')
        job.objective = Objective.model_validate(data['objective']) if data.get('objective') else None
        job.response = data.get('response', 'answer')
        job.clarification_exchanges = data.get('clarification_exchanges', [])
        for key in ('messages','clarification','error','revision','created_at','parent_id','adaptive','test_started','hypothesis'):
            setattr(job,key,data[key])
        if data['request']:
            shape = AnalysisRequest if data['request']['metric']=='attempt_success' else LifecycleRequest
            job.requested_analysis=shape.model_validate(data['request'])
        if data['evidence_id']:
            job.evidence=store.get(data['evidence_id'],scope)
            verify_evidence(job.evidence)
        if job.evidence is not None and job.status in ('verified','blocked') and not (
                job.status=='blocked' and data['dashboard'] is None):
            job.dashboard=read_layout(data['dashboard'],job.evidence)
            job.narrative=publication_narrative(job.evidence, job.dashboard)
        return job


@dataclass
class Session:
    id: str
    authorization: object
    runner: object
    jobs: dict = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.RLock)
    lease: object = None
    resume_key: str | None = None
    store: object = None
    local_operator: bool = False

    @property
    def stable_id(self):
        return self.lease.id if self.lease else self.id

    def save(self,*jobs):
        if self.lease:
            self.lease.save(*jobs)

    def close(self):
        self.authorization.close()
        if hasattr(self.runner,'close'):
            self.runner.close()
        if self.lease:
            self.lease.close()


class Sessions:
    def __init__(self,settings,root,runner_factory=None,authorization_factory=Authorization,store_factory=None):
        self.settings,self.root = settings,root
        if store_factory is None:
            from app.evidence.postgres_store import PostgresStore
            store_factory = lambda: PostgresStore(settings)
        self.store_factory = store_factory
        self.events = Events(root/'.local/analyst/events.jsonl')
        self.runner_factory = runner_factory or (lambda auth,store: Investigator(settings,auth,store,events=self.events))
        self.authorization_factory = authorization_factory
        self.sessions = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2,thread_name_prefix='analyst')

    def saved(self):
        if isinstance(self.store_factory(), EvidenceStore):
            return []
        auth = self.authorization_factory(self.settings)
        try:
            rows = saved_sessions(self.settings, auth.scenario)
            auth.check()
            return rows
        finally:
            auth.close()

    def create(self, saved_id=None, resume_key=None, *, local_operator=False):
        with self.lock:
            for key,session in list(self.sessions.items()):
                if time.monotonic()-session.touched > 1800:
                    if not any(j.future and not j.future.done() for j in session.jobs.values()):
                        self.detach(key)
            if saved_id and local_operator:
                for handle, active in self.sessions.items():
                    if active.local_operator and active.stable_id == saved_id:
                        # A refreshed tab can reconnect to running work. Retire the old handle.
                        self.get(handle)
                        del self.sessions[handle]
                        active.id = uuid4().hex
                        self.sessions[active.id] = active
                        return active
            if len(self.sessions) >= 8:
                raise ValueError('Session limit reached; close an existing session')
            auth = self.authorization_factory(self.settings)
            session_id = uuid4().hex
            lease = None
            try:
                store = self.store_factory()
                if not isinstance(store,EvidenceStore):
                    key = resume_key if saved_id else secrets.token_urlsafe(36)
                    lease = SessionLease(self.settings,saved_id or uuid4().hex,auth.scenario,key,
                                         create=saved_id is None,local_operator=local_operator)
                    store.owner_token = lease.owner
                elif saved_id:
                    raise KeyError('Session is not saved')
                session = Session(session_id,auth,self.runner_factory(auth,store),store=store,lease=lease,
                                  resume_key=key if lease and not saved_id and not local_operator else None,
                                  local_operator=local_operator)
                if saved_id:
                    for data in lease.load():
                        restored = Investigation.restore(data,store)
                        if restored.scope.session_id!=saved_id or restored.scope.scenario!=auth.scenario:
                            raise StaleSession('Saved work has a different scope')
                        session.jobs[restored.scope.investigation_id]=restored
                auth.check()
            except Exception:
                auth.close()
                if lease:
                    lease.close()
                raise
            self.sessions[session_id] = session
            for job in session.jobs.values():
                if job.status in ACTIVE:
                    self.submit(session,job)
            return session

    def get(self,session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError('Unknown session')
            if time.monotonic()-session.touched > 1800:
                self.detach(session_id)
                raise StaleSession('Session expired')
            try:
                session.authorization.check()
                if session.lease:
                    with session.lease.authorized():
                        pass
            except StaleSession:
                for job in session.jobs.values():
                    job.invalidate()
                raise
            session.touched = time.monotonic()
            return session

    def submit(self,session,job):
        def run():
            try:
                if job.parent_id and (job.requested_analysis is None or job.response != 'answer'):
                    parent = session.jobs[job.parent_id]
                    job.parent_evidence = session.store.get(parent.evidence.id, parent.scope)
                if job.requested_analysis is None:
                    session.runner.run(job)
                else:
                    parent=session.jobs[job.parent_id]
                    session.runner.run_typed(job,job.requested_analysis,parent.evidence if job.adaptive else None)
                    if job.adaptive and job.status=='verified':
                        from app.agent.hypotheses import assess_test
                        epoch=session.lease.epoch
                        job.hypothesis=assess_test(parent.evidence,job.evidence,left_epoch=epoch,right_epoch=epoch)
                session.authorization.check()
                session.save(job)
            except StaleSession:
                job.invalidate()
            except Exception:
                job.fail('failed','Could not complete the saved investigation')
                session.save(job)
        job.future=self.executor.submit(run)

    def require_idle(self,session):
        if any(job.status in ACTIVE or (job.future and not job.future.done()) for job in session.jobs.values()):
            raise ValueError('An investigation is already running')

    def check_capacity(self,session):
        self.require_idle(session)
        if len(session.jobs) >= 16:
            raise ValueError('Investigation limit reached; start a new session')

    @session_operation
    def start(self,session_id,question):
        session = self.get(session_id)
        with session.lock:
            self.check_capacity(session)
            job = Investigation(question,Scope(session_id=session.stable_id,scenario=session.authorization.scenario))
            session.save(job)
            session.jobs[job.scope.investigation_id] = job
            self.submit(session,job)
            return job

    def job(self,session_id,investigation_id):
        session = self.get(session_id)
        job = session.jobs.get(investigation_id)
        if job is None:
            raise KeyError('Unknown investigation')
        return session,job

    @session_operation
    def history(self, session_id):
        session = self.get(session_id)
        jobs = sorted(session.jobs.values(), key=lambda j: (j.created_at, j.scope.investigation_id))
        return {'investigations': [job.history_entry() for job in jobs]}

    @session_operation
    def followup(self,session_id,investigation_id,command):
        from app.agent.hypotheses import propose_test
        session,parent = self.job(session_id,investigation_id)
        with session.lock:
            self.check_capacity(session)
            if command.version != parent.revision:
                raise ResultVersionChanged('The selected result has a newer revision.')
            if parent.status!='verified' or not parent.evidence:
                raise ValueError('Follow-up requires the current verified result')
            source = self.evidence(session_id,parent.evidence.id)
            verify_evidence(source)
            request = source.request.model_dump(mode='json')
            budget = Budget()
            focus_measure = parent.dashboard.headline_measure if parent.dashboard else None
            adaptive = command.action=='test_hypothesis'
            if adaptive:
                if not parent.can_test_segment():
                    raise ValueError('No eligible segment test remains for this result')
                if source.request.metric!='attempt_success' or parent.budget.statements+4>12:
                    raise ValueError('This measurement has no additional segment test within the SQL allowance')
                if parent.test_started or parent.adaptive:
                    raise ValueError('This hypothesis has already been tested')
                filters,question=propose_test(source)
                request['filters'] = filters.model_dump()
                budget=Budget(started=parent.budget.started,statements=parent.budget.statements,
                              tools=parent.budget.tools,repairs=parent.budget.repairs,
                              tokens_reserved=parent.budget.tokens_reserved)
            elif command.action in ('filter', 'point'):
                original = source.request.filters
                if command.action == 'point':
                    layout = validate_layout(parent.dashboard, source)
                    if command.block >= len(layout.blocks):
                        raise ValueError('Unknown chart selection')
                    block = layout.blocks[command.block]
                    if not block.drilldown:
                        raise ValueError('Chart has no drill-down action')
                    focus_measure = block.measure
                    dataset = result_catalog(source)[block.source]
                    rows = selected_rows(block, dataset)
                    if command.row >= len(rows):
                        raise ValueError('Unknown chart row')
                    changes = {dataset.action_field: rows[command.row][dataset.action_field]}
                else:
                    changes=command.filters.model_dump(exclude_none=True)
                changes = bind_filters(changes, session.authorization)
                existing = original.model_dump(exclude_none=True)
                if 'payer_bank_id' in changes:
                    banks = session.authorization.banks
                    bank_id = changes['payer_bank_id']
                    if original.payer_bank_id is not None and bank_id not in matching_bank_ids(original.payer_bank_id, banks):
                        raise ValueError('Select a narrower bank, method or merchant')
                    existing.pop('payer_bank_id', None)
                existing = bind_filters(existing, session.authorization)
                if not changes or any(existing.get(k) not in (None,v) for k,v in changes.items()):
                    raise ValueError('Select a narrower bank, method or merchant')
                filters=original.model_copy(update=changes)
                if filters==original:
                    raise ValueError('Filters already applied')
                question='Compare '+source.request.metric.replace('_',' ')+' for '+', '.join(changes.values())
                request['filters'] = filters.model_dump()
            elif command.action == 'windows':
                request.update(baseline=command.baseline, comparison=command.comparison)
                question = 'Repeat the comparison with the selected windows'
            elif command.action == 'breakdown':
                if source.request.metric != 'attempt_success':
                    raise ValueError('This breakdown requires attempt success')
                request['detail'] = command.detail
                question = 'Show ' + command.detail.replace('_', ' ') + ' for the same comparison'
            else:
                question = command.question
            if command.action != 'question':
                request['filters'] = bind_filters(request['filters'], session.authorization)
            req = type(source.request).model_validate(request)
            parent_objective = parent.dashboard.objective or inferred_objective(parent.question)
            response = continuation(question) if command.action == 'question' else None
            reuse_scope = command.action != 'question' or response is not None
            job=Investigation(question,Scope(session_id=session.stable_id,scenario=source.scope.scenario),
                              budget=budget,parent_id=investigation_id,
                              focus_measure=focus_measure if command.action in ('point','filter','windows') else None,
                              objective=parent_objective if reuse_scope else None, response=response or 'answer',
                              requested_analysis=req if reuse_scope else None, adaptive=adaptive)
            if command.action == 'question':
                from app.agent.graph import initial_messages
                job.messages = initial_messages(job.scope, question)
                job.messages.insert(-1, {'role':'system','content':'The following is verified parent data. '
                    'An identical registered analysis reuses these verified results. '
                    'Changes to filters, dates, cutoff, metric, or unavailable detail require new SQL. '
                    'Use these windows, filters, metric and cutoff unless the user changes them. '
                    'Resolve ambiguous changes through clarification. ' + json.dumps({
                        'evidence_id': source.id, 'request': request, 'answer': parent.narrative['answer'],
                        'objective':parent_objective.model_dump(), 'finding':parent.narrative['guidance']['finding'],
                        'recommended_steps':parent.narrative['recommendations'],
                        'available_results': list(result_catalog(source)),
                        'layout': parent.dashboard.model_dump(mode='json')})})
            parent.revision+=1
            was_started=parent.test_started
            parent.test_started=was_started or adaptive
            try:
                session.save(parent,job)
            except Exception:
                parent.revision-=1
                parent.test_started=was_started
                raise
            session.jobs[job.scope.investigation_id]=job
            self.submit(session,job)
            return job

    @session_operation
    def compare(self,session_id,investigation_id,version,other_id):
        from app.analytics.source_conflicts import compare_sources
        session,left=self.job(session_id,investigation_id)
        with session.lock:
            _,right=self.job(session_id,other_id)
            if left.revision!=version or investigation_id==other_id or any(
                    job.snapshot()['status']!='verified' for job in (left,right)):
                raise ValueError('Comparison requires two current verified sources')
            epoch=session.lease.epoch if session.lease else None
            result=compare_sources(self.evidence(session_id,left.evidence.id),self.evidence(session_id,right.evidence.id),
                                   left_epoch=epoch,right_epoch=epoch)
            session.authorization.check()
            return result

    @session_operation
    def reply(self,session_id,investigation_id,version,answer):
        session,job = self.job(session_id,investigation_id)
        with session.lock:
            self.require_idle(session)
            if job.status != 'clarification_required' or job.revision != version:
                raise ValueError('Clarification reply is stale')
            job.budget.check()
            update = dict(scope=job.scope.model_copy(update={'version':version+1}),revision=version+1,
                          messages=[*job.messages,{'role':'user','content':answer}],
                          clarification_exchanges=[*job.clarification_exchanges,
                                                   {'prompt':job.clarification or '', 'reply':answer}],
                          clarification=None,status='received')
            session.save(replace(job,**update))
            with job.lock:
                for key,value in update.items():
                    setattr(job,key,value)
            self.submit(session,job)
            return job

    @session_operation
    def cancel(self,session_id,investigation_id):
        session,job = self.job(session_id,investigation_id)
        with job.lock:
            job.budget.cancel.set()
            job.fail('cancelled','Investigation cancelled')
        session.save(job)
        return job

    @session_operation
    def evidence(self,session_id,evidence_id):
        session = self.get(session_id)
        for job in session.jobs.values():
            if (job.evidence and job.evidence.id == evidence_id and job.narrative is not None
                    and (job.future is None or job.future.done())):
                result = session.store.get(evidence_id,job.scope)
                session.authorization.check()
                return result
        raise KeyError('Unknown evidence')

    def detach(self,session_id,revoke=False):
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                if any(job.future and not job.future.done() for job in session.jobs.values()):
                    raise ValueError('Wait for the active investigation')
                if revoke and session.lease:
                    session.lease.revoke()
                session.close()
                self.sessions.pop(session_id)

    def close(self,session_id):
        self.detach(session_id,revoke=True)

    def shutdown(self):
        self.executor.shutdown(wait=True)
        for session_id in list(self.sessions):
            self.detach(session_id)
