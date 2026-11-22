"""Recovery must load the committed result before re-running an analytical step."""
from uuid import uuid4

import pytest

from app.agent.graph import Investigator
from app.api.session import Investigation
from app.config import Settings
from app.contracts import AnalysisRequest, Scope
from app.evidence.bundle_receipts import BundleReceipt
from app.evidence.postgres_store import PostgresStore
from app.evidence.store import checksum
from app.evidence.verify import verify_evidence
from app.query.executor import Authorization
from app.query.executor import Budget


def test_budget_persists_reservations_before_returning_to_caller():
    receipts = []
    budget = Budget()
    budget.persist = lambda: receipts.append((budget.statements, budget.tokens_reserved))
    budget.sql()
    budget.reserve_tokens(100)
    budget.settle_tokens(100, 60)
    assert receipts == [(1, 0), (1, 100), (1, 60)]


class SimulatedProcessExit(BaseException):
    pass


@pytest.mark.integration
@pytest.mark.parametrize('crash_at',['before_receipt','before_evidence','after_evidence'])
def test_restart_either_side_of_evidence_commit(monkeypatch, crash_at):
    settings = Settings.from_root()
    store = PostgresStore(settings)
    auth = Authorization(settings)
    scope = Scope(scenario=auth.scenario, session_id=uuid4().hex)
    store.owner_token = uuid4().hex
    request = AnalysisRequest(
        baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},
        comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'},
    )
    with store.connect() as conn:
        conn.execute("""INSERT INTO analyst_meta.sessions
            (session_id,subject,scenario,generation,import_epoch,key_digest,owner_token)
            SELECT %s,%s,scenario,generation,import_epoch,'test',%s FROM analyst_meta.control WHERE ready""",
            (scope.session_id,scope.subject,store.owner_token))
    if crash_at == 'before_receipt':
        def interrupt_delivery(*args):
            raise SimulatedProcessExit
        monkeypatch.setattr(BundleReceipt,'seal',interrupt_delivery)
    else:
        original_put = store.put
        def crash(evidence,step):
            verify_evidence(evidence.model_copy(update={'checksum':checksum(evidence)}))
            if crash_at=='after_evidence':
                original_put(evidence,step)
            raise SimulatedProcessExit
        monkeypatch.setattr(store,'put',crash)
    try:
        original_job = Investigation('Test replay',scope)
        with pytest.raises(SimulatedProcessExit):
            Investigator(settings,auth,store).run_typed(original_job,request)
        assert original_job.budget.statements == 8
        def forbid_second_bundle(*args):
            pytest.fail('Replay attempted to open a new fixture SQL connection')
        monkeypatch.setattr('app.query.executor.connect',forbid_second_bundle)
        restarted = PostgresStore(settings)
        restarted.owner_token = store.owner_token
        job = Investigation('Test replay',scope)
        Investigator(settings,auth,restarted).run_typed(job,request)
        assert job.budget.statements == original_job.budget.statements
        if crash_at == 'before_receipt':
            assert job.status == 'limited' and job.evidence is None
            assert 'no complete result receipt' in job.error
            assert restarted.find_step(scope,'analysis') is None
            return
        assert job.status == 'verified' and job.narrative is not None, job.error
        assert job.budget.tools == 2
        verify_evidence(job.evidence)
        assert restarted.find_step(scope,'analysis').id == job.evidence.id
        with store.connect() as conn:
            receipt = conn.execute('SELECT receipt FROM analyst_meta.bundles WHERE session_id=%s',
                                   (scope.session_id,)).fetchone()['receipt']
            assert job.evidence.snapshot == receipt['snapshot']
            assert [q.sql_sha256 for q in job.evidence.queries] == [q['sql_sha256'] for q in receipt['queries']]
            assert conn.execute('SELECT count(*) AS n FROM analyst_meta.evidence WHERE session_id=%s',
                                (scope.session_id,)).fetchone()['n']==1
            conn.execute("UPDATE analyst_meta.budgets SET deadline=now()-interval '1 hour' WHERE session_id=%s",
                         (scope.session_id,))
        replayed = Investigation('Test replay',scope)
        Investigator(settings,auth,restarted).run_typed(replayed,request)
        assert replayed.snapshot() == job.snapshot()
    finally:
        auth.close()
        with store.connect() as conn, conn.transaction():
            thread = f'{scope.session_id}/{scope.investigation_id}/{scope.version}'
            for table in ('checkpoint_writes','checkpoint_blobs','checkpoints'):
                conn.execute(f'DELETE FROM analyst_meta.{table} WHERE thread_id=%s',(thread,))
            for table in ('bundles','evidence','budgets','sessions'):
                conn.execute(f'DELETE FROM analyst_meta.{table} WHERE session_id=%s',(scope.session_id,))
