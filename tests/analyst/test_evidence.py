from datetime import datetime, timezone
import pytest
from app.contracts import Evidence, Scope, AnalysisRequest, QualityRecord
from app.evidence.store import EvidenceStore


def example(scope=None):
    return Evidence(scope=scope or Scope(scenario='scenario_a',session_id='one'),
                    request=AnalysisRequest(baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'}),
                    created_at=datetime.now(timezone.utc),snapshot='1:2:',quality=[],queries=[],results={})


def test_idempotent_and_owned_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    original = example()
    saved = store.put(original, 'analysis')
    assert store.put(original, 'analysis').id == saved.id
    assert store.get(saved.id, original.scope).checksum == saved.checksum
    with pytest.raises(PermissionError):
        store.get(saved.id, original.scope.model_copy(update={'session_id':'other'}))
    with pytest.raises(PermissionError):
        store.get('../anything', original.scope)
    with pytest.raises(ValueError):
        store.put(original.model_copy(update={'results':{'changed':True}}), 'analysis')
    path = tmp_path / (saved.id + '.json')
    path.write_text('{}')
    with pytest.raises(ValueError):
        store.get(saved.id, original.scope)
