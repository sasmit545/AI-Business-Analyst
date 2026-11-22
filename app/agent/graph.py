import json
import re
import time
from contextlib import nullcontext
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.model import InsufficientModelAllowance, ModelOutputError, ModelUnavailable, NemotronModel, ToolCall
from app.agent.prompts import PRESENTATION, SYSTEM
from app.agent.objective import ambiguous_priority
from app.agent.tools import Dispatcher, PolicyRejected, definitions, validation_issues
from app.agent.windows import WindowMismatch, explicit_windows
from app.context.catalog import catalog
from app.context.banks import BankLookupError
from app.context.dimensions import DimensionLookupError, bind_filters
from app.query.executor import BudgetExceeded, Cancelled, StaleSession


class State(TypedDict):
    job: object
    call: object


def initial_messages(scope, question):
    return [{'role':'system','content':SYSTEM},
            {'role':'system','content':json.dumps({'selected_dataset':catalog(scope.scenario)})},
            {'role':'user','content':question}]


def publication_messages(job):
    """Keep the question and latest SQL observation without rebilling the discovery catalog."""
    for index in range(len(job.messages)-1, 0, -1):
        message = job.messages[index]
        if message['role'] != 'tool':
            continue
        observation = json.loads(message['content'])
        if 'ui_sources' in observation:
            # Decompositions and failure labels already summarize the most relevant segments.
            observation.pop('segments', None)
            prompts = [m for m in job.messages[:index-1] if m['role'] == 'user']
            return [{'role':'system','content':PRESENTATION}, *prompts,
                    job.messages[index-1], dict(message, content=json.dumps(observation, separators=(',',':'))),
                    *job.messages[index+1:]]
    return job.messages  # Older interrupted checkpoints did not advertise a source catalog.


class Investigator:
    def __init__(self, settings, authorization, store, model=None, events=None):
        self.authorization = authorization
        self.model = model or NemotronModel(settings)
        self.dispatcher = Dispatcher(settings,authorization,store)
        self.events = events
        graph = StateGraph(State)
        graph.add_node('model',self._model)
        graph.add_node('tool',self._tool)
        graph.add_edge(START,'model')
        graph.add_conditional_edges('model',lambda state: 'tool' if state.get('call') else ('model' if state['job'].status == 'running' else END))
        graph.add_conditional_edges('tool',lambda state: 'model' if state['job'].status == 'running' else END)
        self.graph = graph.compile()

    def _repair(self,job):
        if job.budget.repairs >= 2:
            raise ModelOutputError('Structured output could not be validated')
        job.budget.repairs += 1
        job.budget.record()
        job.messages.append({'role':'user','content':'The last tool request was invalid. Use only a registered tool with its exact argument schema. Do not invent results.'})

    def _clarify_scope(self, job, message):
        with job.lock:
            job.budget.tool()
            job.clarification = message
            job.messages.append({'role':'assistant', 'content':message})
            job.status = 'clarification_required'
        return {'job':job, 'call':None}

    def _model(self,state):
        job = state['job']
        job.budget.check()
        self.authorization.check()
        try:
            request = getattr(job, 'requested_analysis', None)
            if request is None:
                messages = publication_messages(job) if job.evidence is not None else job.messages
                call = self.model.next(messages,definitions(evidence_ready=job.evidence is not None,
                                       requested_windows=explicit_windows(job.messages),scenario=job.scope.scenario,
                                       evidence=job.evidence,question=job.question),job.budget)
            elif job.evidence is None:
                name = 'analyze_attempts' if request.metric == 'attempt_success' else 'analyze_lifecycle'
                call = ToolCall('typed-analysis', name, request.model_dump(mode='json'))
            else:
                args = {'evidence_id':job.evidence.id}
                if getattr(request, 'detail', None):
                    args['blocks'] = [{'kind':'table','source':request.detail}]
                if job.focus_measure:
                    args['headline_measure'] = job.focus_measure
                    args['blocks'] = [
                        {'kind':'comparison','source':'overall','measure':job.focus_measure},
                        {'kind':'bar','source':'overall','measure':job.focus_measure},
                        *args.get('blocks', []),
                    ]
                call = ToolCall('typed-publication', 'publish_answer', args)
        except (ModelOutputError, ModelUnavailable, InsufficientModelAllowance) as exc:
            if job.evidence is not None:
                # A failed presentation stream cannot erase a completed, verifiable SQL result.
                call = ToolCall('text-only', 'publish_answer', {'evidence_id':job.evidence.id, 'blocks':[]})
            elif not isinstance(exc, ModelOutputError):
                raise
            else:
                self._repair(job)
                return {'job':job,'call':None}
        # Bind new requests before checkpointing. Replays keep their original SQL parameters.
        unsupported = (call.name == 'clarify' and call.arguments == {'topic': 'unsupported'}
                       and re.search(r'\b(orders?|settlements?|retr(?:y|ies)|recovery|bank health|first.attempt)\b',
                                     job.question, re.I))
        if job.evidence is None and (call.name == 'analyze_lifecycle' or unsupported):
            if 'orders' not in catalog(job.scope.scenario)['tables']:
                return self._clarify_scope(job, f'The selected dataset {job.scope.scenario} contains completed attempts. '
                                           'Order, retry, settlement and bank-health measures require a lifecycle dataset. '
                                           'Would you like to compare completed attempts in this dataset?')
        if job.evidence is None and call.name in ('analyze_attempts', 'analyze_lifecycle'):
            filters = call.arguments.get('filters')
            if isinstance(filters, dict):
                try:
                    bound = bind_filters(filters, self.authorization)
                except (BankLookupError, DimensionLookupError) as exc:
                    return self._clarify_scope(job, str(exc))
                call = ToolCall(call.id, call.name, dict(call.arguments, filters=bound))
        job.messages.append({'role':'assistant','content':None,'tool_calls':[{'id':call.id,'type':'function','function':{'name':call.name,'arguments':json.dumps(call.arguments)}}]})
        return {'job':job,'call':call}

    def _tool(self,state):
        job,call = state['job'],state['call']
        started = time.monotonic()
        try:
            output = self.dispatcher.call(call,job)
        except (ValidationError,WindowMismatch) as exc:
            issues = ([{'field':'baseline/comparison','code':'explicit_window_mismatch'}]
                      if isinstance(exc,WindowMismatch) else validation_issues(call.name, exc))
            output = {'error':'Tool arguments failed schema validation', 'issues':issues}
            if isinstance(exc,WindowMismatch):
                output['expected_windows'] = exc.expected
            if call.name == 'get_context':
                output['expected_arguments'] = {}
            job.messages.append({'role':'tool','tool_call_id':call.id,'content':json.dumps(output)})
            if self.events:
                self.events.record(job,'tool_validation_failed',(time.monotonic()-started)*1000,
                                   call.name,details={'issues':issues})
            self._repair(job)
            return {'job':job,'call':None}
        job.messages.append({'role':'tool','tool_call_id':call.id,'content':json.dumps(output,default=str)})
        if self.events:
            self.events.record(job,'tool_completed',(time.monotonic()-started)*1000,call.name)
        return {'job':job,'call':None}

    def run_typed(self, job, request, parent_evidence=None):
        job.requested_analysis = request
        job.adaptive_parent = parent_evidence
        return self.run(job)

    def run(self,job):
        from app.evidence.postgres_store import PostgresStore
        store = self.dispatcher.store
        durable = isinstance(store, PostgresStore)
        try:
            self.authorization.check()
            with store.meter(job.scope,job.budget) if durable else nullcontext():
                if not durable:
                    job.budget.check()
                if not job.messages:
                    job.messages = initial_messages(job.scope, job.question)
                if (job.scope.version == 1 and not job.requested_analysis
                        and ambiguous_priority(job.question)):
                    from app.agent.tools import CLARIFICATIONS
                    job.clarification = CLARIFICATIONS['priority']
                    job.status = 'clarification_required'
                    return
                if (job.scope.version == 1 and not getattr(job, 'requested_analysis', None)
                        and not any(m['role']=='assistant' for m in job.messages)
                        and re.search(r'\b(last week|this week|yesterday|today|recently|last month)\b',job.question,re.I)):
                    job.clarification = 'Please specify the metric and explicit baseline and comparison dates, including timezone.'
                    job.status = 'clarification_required'
                    return
                job.status = 'running'
                if durable:
                    from app.agent.checkpoints import invoke_durable
                    invoke_durable(self, job, store)
                else:
                    self.graph.invoke({'job':job,'call':None},{'recursion_limit':32})
        except StaleSession:
            job.invalidate()
        except Cancelled:
            job.fail('cancelled','Investigation cancelled')
        except BudgetExceeded as exc:
            job.fail('limited',str(exc))
        except PolicyRejected as exc:
            job.fail('blocked',str(exc))
        except (ModelUnavailable,ModelOutputError) as exc:
            job.fail('failed',str(exc))
        except Exception:
            job.fail('failed','Analysis failed safely; no unverified result was published')
        finally:
            if self.events:
                self.events.record(job,'investigation_state')

    def close(self):
        if hasattr(self.model,'close'):
            self.model.close()
