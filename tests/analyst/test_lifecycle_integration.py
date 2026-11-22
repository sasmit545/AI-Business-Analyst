from datetime import datetime, timezone
import pytest

from test_lifecycle import hand_connection, request
from test_health import TemporaryBundle
from app.agent.tools import definitions
from app.analytics.lifecycle import compile_lifecycle, derive
from app.contracts import Evidence, Scope, QueryRecord
from app.evidence.store import checksum
from app.evidence.verify import verify_evidence
from app.quality.lifecycle import check_lifecycle_quality
from app.context.catalog import catalog


def test_lifecycle_evidence_rejects_changed_denominator(hand_connection):
    req=request('order_conversion');queries,params=compile_lifecycle('lifecycle_v1',req)
    raw={n:TemporaryBundle(hand_connection).query(n,sql,params) for n,sql in queries.items()}
    evidence=Evidence(scope=Scope(scenario='lifecycle_v1',session_id='test'),request=req,
        created_at=datetime.now(timezone.utc),snapshot='test',observation_cutoff=req.observation_cutoff.isoformat(),
        quality=[],queries=[QueryRecord(name=n,sql=queries[n],parameters=params,rows=rows,elapsed_ms=0,sql_sha256='test') for n,rows in raw.items()],results=derive(raw))
    evidence=evidence.model_copy(update={'checksum':checksum(evidence)})
    verify_evidence(evidence)
    evidence.results['overall'][0]['denominator']=3
    evidence=evidence.model_copy(update={'checksum':checksum(evidence)})
    with pytest.raises(ValueError,match='differs'): verify_evidence(evidence)


def test_lifecycle_tools_and_definitions_are_selected_scope_only():
    names=lambda scenario,ready=False:{t['function']['name'] for t in definitions(scenario=scenario,evidence_ready=ready)}
    assert 'analyze_lifecycle' in names('lifecycle_v1')
    assert 'analyze_lifecycle' not in names('scenario_a')
    assert 'analyze_lifecycle' not in names('lifecycle_v1',True)
    assert 'order_conversion' not in catalog('scenario_a')['metrics']
    with pytest.raises(ValueError): compile_lifecycle('scenario_a',request('order_conversion'))
    with pytest.raises(ValueError): request('order_conversion','2026-11-02T00:00:00+05:30')


def test_malformed_settlement_blocks_before_cast(hand_connection):
    hand_connection.execute("UPDATE pg_temp.settlements SET due_at='broken', gross_amount_paise='not-an-amount'")
    records=check_lifecycle_quality(TemporaryBundle(hand_connection),'settlement_amount')
    assert any(q.status=='BLOCK' for q in records)
    assert all(q.status=='PASS' for q in check_lifecycle_quality(TemporaryBundle(hand_connection),'order_conversion'))
