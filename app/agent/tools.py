from typing import Literal
from contextlib import nullcontext
from uuid import uuid4

from pydantic import Field, ValidationError

from app.analytics.attempts import analyze
from app.analytics.lifecycle import analyze as analyze_lifecycle
from app.agent.windows import WindowMismatch, explicit_windows
from app.agent.objective import Objective, inferred_objective
from app.context.catalog import catalog
from app.contracts import AnalysisRequest, LifecycleRequest, StrictModel
from app.evidence.render_claims import publication_narrative
from app.evidence.verify import verify_evidence
from app.quality.policy import blocked
from app.ui_specs.models import Block, Layout, Measure
from app.ui_specs.planning import expand_views, publication_parameters, text_only
from app.ui_specs.results import describe_sources, result_catalog
from app.ui_specs.validate import default_layout, validate_layout


class Empty(StrictModel):
    pass


class EvidenceReference(StrictModel):
    evidence_id: str = Field(min_length=1,max_length=64)


class Publication(EvidenceReference):
    chart: Literal['bar','line','table'] = 'bar'
    blocks: list[Block] | None = Field(default=None, max_length=6)
    headline_measure: Measure | None = None
    views: list[str] | None = Field(default=None, max_length=12)


class Clarification(StrictModel):
    topic: Literal['metric','windows','filters','unsupported','priority'] = 'windows'


CLARIFICATIONS = {
    'priority':'Which priority should I compare: the largest number affected, the biggest change in rate, or the largest contribution to the overall change?',
    'metric':'Which metric and denominator do you mean: attempt success, order conversion, first-attempt success, retry uptake, recovery among all initial failures or retried orders, or settlement count or amount completion?',
    'windows':'What explicit baseline and comparison date ranges and timezone should I use?',
    'filters':'Which bank, payment method or merchant filter should I apply?',
    'unsupported':'That analysis is unavailable in this selected dataset. Please choose a supported metric and explicit comparison dates.',
}


ARGUMENTS = {'get_context':Empty,'analyze_attempts':AnalysisRequest,
             'analyze_lifecycle':LifecycleRequest,
             'get_evidence':EvidenceReference,'publish_answer':Publication,'clarify':Clarification}

DESCRIPTIONS = {
    'get_context':'Get answer-free definitions for the selected dataset. Takes no arguments: pass {}.',
    'analyze_attempts':'Compare completed attempts, success rates, volumes and failed counts by bank or method, daily trends, and failure labels. For comparisons across banks omit the bank filter. Optionally request merchant or transaction detail.',
    'analyze_lifecycle':'Compare a lifecycle metric using its registered denominator and observation cutoff. Only available for the selected lifecycle dataset. Health alignment does not prove causation.',
    'get_evidence':'Inspect the active executed evidence by ID.',
    'publish_answer':'Publish the evidence_id and ordered views for this question. Pass views=[] for text alone.',
    'clarify':'Ask one focused question to resolve consequential ambiguity before querying.',
}


def definitions(evidence_ready=False, requested_windows=None, scenario=None, evidence=None, question=''):
    allowed = {'get_evidence','publish_answer'} if evidence_ready else {'analyze_attempts','clarify'}
    if not evidence_ready and scenario=='lifecycle_v1':
        allowed.add('analyze_lifecycle')
    tools = [{'type':'function','function':{'name':name,'description':DESCRIPTIONS[name],
            'parameters':shape.model_json_schema()}} for name,shape in ARGUMENTS.items() if name in allowed]
    for tool in tools:
        if tool['function']['name'] in ('analyze_attempts','analyze_lifecycle'):
            tool['function']['parameters']['properties']['objective'] = Objective.model_json_schema()
    if evidence is not None:
        for tool in tools:
            if tool['function']['name'] == 'publish_answer':
                tool['function']['parameters'] = publication_parameters(evidence, question)
                if 'views' not in tool['function']['parameters']['properties']:
                    tool['function']['description'] = 'Publish the verified text answer. Omit views, blocks and chart.'
    if requested_windows:
        for tool in tools:
            if tool['function']['name'] in ('analyze_attempts','analyze_lifecycle'):
                for key,window in requested_windows.items():
                    tool['function']['parameters']['properties'][key]['const']=window.model_dump(mode='json')
    return tools


def validation_issues(tool, error):
    """Expose only schema-owned field names and error codes, never submitted values."""
    fields = set()

    def collect(schema):
        if isinstance(schema, dict):
            fields.update(schema.get('properties', {}))
            for value in schema.values():
                collect(value)
        elif isinstance(schema, list):
            for value in schema:
                collect(value)

    collect(ARGUMENTS[tool].model_json_schema())
    issues = []
    for item in error.errors(include_input=False, include_context=False, include_url=False)[:12]:
        location = '.'.join(part if part in fields else '<unknown_field>'
                            for part in item['loc'][:8]) or '<request>'
        issues.append({'field': location, 'code': item['type']})
    return issues


class PolicyRejected(RuntimeError):
    pass


def observation(evidence):
    verify_evidence(evidence)
    results = evidence.results
    decompositions = results.get('decomposition',{})
    joint = decompositions.get('joint',{})
    joint_summary = {key:value for key,value in joint.items() if key != 'parts'}
    if joint.get('available'):
        joint_summary['largest_within_effects'] = sorted(joint['parts'],key=lambda part:abs(part['within']),reverse=True)[:3]
    return {'evidence_id':evidence.id,'request':evidence.request.model_dump(mode='json'),
            'quality':[q.model_dump() for q in evidence.quality if q.status != 'PASS'],
            'quality_status':'BLOCK' if blocked(evidence.quality) else 'WARN' if any(q.status=='WARN' for q in evidence.quality) else 'PASS',
            'ui_sources':describe_sources(result_catalog(evidence)),
            'detail_preview':results.get(evidence.request.detail, [])[:4]
                if isinstance(evidence.request, AnalysisRequest) and evidence.request.detail else [],
            'overall':results.get('overall'), 'methods':results.get('methods'),
            'segments':[{key:value for key,value in row.items() if key != 'bank_name'} for row in results.get('segments',[])],
            'decomposition':{'method':decompositions.get('method'),'joint':joint_summary},
            'failure_labels':sorted(results.get('failures',[]), key=lambda r:r['count'], reverse=True)[:6],
            'caveat':'Failure labels are observations; counts depend on traffic. No causal proof.'}


class Dispatcher:
    def __init__(self, settings, authorization, store):
        self.settings, self.authorization, self.store = settings,authorization,store

    def call(self, call, job):
        self.authorization.check()
        if call.name in ('analyze_attempts', 'analyze_lifecycle') and job.evidence is None:
            parameters = dict(call.arguments)
            proposed = parameters.pop('objective', None)
            if proposed is not None:
                inferred = inferred_objective(job.question)
                supplied = Objective.model_validate(proposed)
                job.objective = inferred.model_copy(update=supplied.model_dump(exclude_unset=True))
                call = type(call)(call.id, call.name, parameters)
            elif getattr(job, 'objective', None) is None:
                question = ' '.join([job.question, *(exchange['reply'] for exchange in
                                                   getattr(job, 'clarification_exchanges', []))])
                job.objective = inferred_objective(question)
        durable_analysis = call.name in ('analyze_attempts','analyze_lifecycle') and hasattr(self.store,'bundle')
        # A crash can leave evidence committed and the tool-node checkpoint unwritten.
        # Reuse the scoped step before charging a new tool or issuing another query.
        if call.name in ('analyze_attempts','analyze_lifecycle') and job.evidence is None and hasattr(self.store,'find_step'):
            committed = self.store.find_step(job.scope, 'analysis')
            if committed is not None:
                if ARGUMENTS[call.name].model_validate(call.arguments) != committed.request:
                    raise PolicyRejected('Committed step has a different request')
                verify_evidence(committed)
                job.evidence = committed
                return observation(committed)
        if not (durable_analysis and job.evidence is None and self.store.has_bundle(job.scope)):
            job.budget.tool()
        if call.name not in ARGUMENTS:
            raise PolicyRejected('Requested tool is not available')
        invalid_layout = call.id == 'text-only'
        try:
            arguments = ARGUMENTS[call.name].model_validate(call.arguments)
        except ValidationError:
            if call.name != 'publish_answer':
                raise
            # No part of a malformed presentation may be used, including a legacy chart.
            # The scoped retrieval below still requires a valid owned evidence ID.
            arguments = Publication.model_validate({'evidence_id':call.arguments.get('evidence_id')})
            invalid_layout = True
        if call.name == 'get_context':
            return catalog(job.scope.scenario)
        if call.name == 'clarify':
            if job.evidence is not None:
                raise PolicyRejected('Clarification must precede calculation')
            with job.lock:
                job.budget.check()
                job.clarification = CLARIFICATIONS[arguments.topic]
                job.status = 'clarification_required'
            return {'status':job.status}
        if call.name in ('analyze_attempts','analyze_lifecycle'):
            if job.evidence is not None:
                raise PolicyRejected('One analytical bundle is permitted per investigation')
            expected = explicit_windows(job.messages)
            if expected and any(getattr(arguments,key) != window for key,window in expected.items()):
                raise WindowMismatch(expected)
            if call.name=='analyze_lifecycle' and job.scope.scenario!='lifecycle_v1':
                raise PolicyRejected('Lifecycle metrics are unavailable in this selected dataset')
            previous = getattr(job, 'parent_evidence', None)
            if previous is not None and arguments == previous.request:
                if (previous.scope.investigation_id != job.parent_id or any(
                        getattr(previous.scope, k) != getattr(job.scope, k) for k in ('scenario','session_id','subject'))):
                    raise PolicyRejected('Parent evidence is unavailable')
                source = self.store.get(previous.id, previous.scope)
                verify_evidence(source)
                reused = source.model_copy(update={'scope':job.scope, 'id':uuid4().hex, 'reused_from':source.id})
                job.evidence = self.store.put(reused, 'analysis')
                return observation(job.evidence)
            analysis = analyze_lifecycle if call.name=='analyze_lifecycle' else analyze
            parent = getattr(job, 'adaptive_parent', None)
            journal = self.store.bundle(job.scope, arguments, parent, job.budget) if durable_analysis else nullcontext()
            with journal:
                if parent is None:
                    evidence = analysis(self.settings,self.authorization,job.scope,arguments,job.budget)
                else:
                    from app.analytics.adaptive import test_segment
                    evidence = test_segment(self.settings,self.authorization,self.store,job.scope,arguments,job.budget,parent)
            self.authorization.check()
            saved = self.store.put(evidence,'analysis')
            job.evidence = saved
            return observation(saved)
        if job.evidence is None or arguments.evidence_id != job.evidence.id:
            raise PolicyRejected('Evidence is not owned by this investigation')
        evidence = self.store.get(arguments.evidence_id,job.scope)
        verify_evidence(evidence)
        if call.name == 'get_evidence':
            return observation(evidence)
        dashboard = Layout(version='1', evidence_id=evidence.id, blocks=[], fallback=True)
        if not invalid_layout:
            try:
                if text_only(job.question) or blocked(evidence.quality):
                    if arguments.views or arguments.blocks:
                        raise ValueError('Only a textual publication is available')
                    candidate = Layout(version='1', evidence_id=evidence.id, blocks=[],
                                       headline_measure=arguments.headline_measure)
                elif arguments.views is not None:
                    if arguments.blocks is not None:
                        raise ValueError('Supply one presentation')
                    candidate = expand_views(evidence, arguments.views, arguments.headline_measure, job.question)
                elif arguments.blocks is not None:
                    candidate = Layout(version='1', evidence_id=evidence.id, blocks=arguments.blocks,
                                       headline_measure=arguments.headline_measure)
                else:
                    candidate = default_layout(evidence, arguments.chart)
                dashboard = validate_layout(candidate, evidence)
            except ValueError:
                if arguments.views is not None and job.budget.repairs < 2:
                    job.budget.repairs += 1
                    job.budget.record()
                    schema = publication_parameters(evidence, job.question)['properties']
                    if 'views' not in schema:
                        return {'error':'Text only. Omit views, blocks and chart. Supply evidence_id and only '
                                        'the headline_measure if it is offered.', 'evidence_id':evidence.id}
                    allowed = schema['views']['items']['enum']
                    valid = [v for v in arguments.views if v in allowed and not v.startswith('section.')]
                    return {'error':'Layout rejected. Select up to six distinct legal views. Omit headings on retry.',
                            'evidence_id':evidence.id, 'legal_requested_views':list(dict.fromkeys(valid))[:6]}
                # The fallback retains verified text when the repair allowance is exhausted.
        objective = getattr(job, 'objective', None) or inferred_objective(job.question)
        dashboard = dashboard.model_copy(update={'objective':objective, 'response':getattr(job, 'response', 'answer')})
        rendered = publication_narrative(evidence, dashboard)
        dashboard = dashboard.model_copy(update={'finding_ref':rendered['guidance']['reference']})
        self.authorization.check()
        with job.lock:
            job.budget.check()
            job.dashboard = dashboard
            job.narrative = rendered
            job.status = 'blocked' if blocked(evidence.quality) else 'verified'
        return {'status':job.status,'evidence_id':evidence.id}
