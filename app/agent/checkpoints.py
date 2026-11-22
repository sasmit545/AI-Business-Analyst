"""JSON-only graph state and reauthorized PostgreSQL checkpoint access."""
from contextlib import contextmanager
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from app.agent.model import ToolCall
from app.agent.objective import Objective
from app.evidence.render_claims import publication_narrative
from app.evidence.verify import verify_evidence
from app.query.executor import Cancelled
from app.ui_specs.validate import read_layout


class CheckpointState(TypedDict):
    messages: list[dict]
    call: dict | None
    status: str
    evidence_id: str | None
    dashboard: dict | None
    clarification: str | None
    objective: dict | None


class ScopedSaver(PostgresSaver):
    """The pinned saver routes each read/write batch through this cursor."""
    def __init__(self, connection, store, scope):
        super().__init__(connection)
        self.store, self.scope = store, scope

    @contextmanager
    def _cursor(self, *, pipeline=False):
        with self.lock, self.store.authorized(self.conn, self.scope):
            with self.conn.cursor(binary=True) as cursor:
                yield cursor


def capture(job, call=None):
    return CheckpointState(
        messages=list(job.messages),
        call=dict(id=call.id, name=call.name, arguments=call.arguments) if call else None,
        status=job.status, evidence_id=job.evidence.id if job.evidence else None,
        dashboard=job.dashboard.model_dump(mode='json') if job.dashboard else None,
        clarification=job.clarification,
        objective=job.objective.model_dump() if job.objective else None,
    )


def restore(job, state, store):
    with job.lock:
        if job.budget.cancel.is_set():
            raise Cancelled('Investigation cancelled')
        # A completed graph needs no further execution allowance to reconstruct its response.
        if state['status'] == 'running':
            job.budget.check()
        job.messages = list(state['messages'])
        job.clarification = state['clarification']
        if state.get('objective') is not None:
            job.objective = Objective.model_validate(state['objective'])
        job.evidence = store.get(state['evidence_id'], job.scope) if state['evidence_id'] else None
        job.status = state['status']
        job.dashboard = job.narrative = None
        if job.status == 'verified' or (job.status == 'blocked' and state['dashboard'] is not None):
            verify_evidence(job.evidence)
            job.dashboard = read_layout(state['dashboard'], job.evidence)
            job.narrative = publication_narrative(job.evidence, job.dashboard)


def invoke_durable(investigator, job, store):
    def model(state):
        restore(job, state, store)
        result = investigator._model({'job': job})
        return capture(job, result['call'])

    def tool(state):
        restore(job, state, store)
        investigator._tool({'job': job, 'call': ToolCall(**state['call'])})
        return capture(job)

    builder = StateGraph(CheckpointState)
    builder.add_node('model', model)
    builder.add_node('tool', tool)
    builder.add_edge(START, 'model')
    builder.add_conditional_edges('model', lambda s: 'tool' if s['call'] else ('model' if s['status']=='running' else END))
    builder.add_conditional_edges('tool', lambda s: 'model' if s['status']=='running' else END)
    # Each clarification version has a new thread, while its investigation meter persists.
    thread = f'{job.scope.session_id}/{job.scope.investigation_id}/{job.scope.version}'
    config = {'recursion_limit':32, 'configurable':{'thread_id':thread}}
    with store.connect() as connection:
        graph = builder.compile(checkpointer=ScopedSaver(connection, store, job.scope))
        previous = graph.get_state(config)
        if previous.values and not previous.next:
            restore(job, previous.values, store)
            return
        state = graph.invoke(None if previous.next else capture(job), config, durability='sync')
        restore(job, state, store)
