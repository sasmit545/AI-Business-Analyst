from datetime import datetime, timezone

import pytest

from app.analytics.lifecycle import derive
from app.analytics.source_conflicts import compare_sources
from app.contracts import Evidence, Filters, LifecycleRequest, QueryRecord, Scope
from app.evidence.store import checksum


def measurement(metric='order_conversion', count=7, filters=None, session='local'):
    req = LifecycleRequest(
        metric=metric,
        baseline={'start': '2026-10-01T00:00:00+05:30', 'end': '2026-10-15T00:00:00+05:30'},
        comparison={'start': '2026-10-15T00:00:00+05:30', 'end': '2026-10-29T00:00:00+05:30'},
        filters=filters or Filters(),
    )
    rows = [dict(period=i, numerator=n, denominator=10, excluded=0) for i, n in enumerate((9, count))]
    raw = {'overall': rows, 'segments': [dict(r, payer_bank_id='BANK_E', payment_method='CARD') for r in rows]}
    evidence = Evidence(
        scope=Scope(session_id=session, scenario='lifecycle_v1'), request=req,
        created_at=datetime.now(timezone.utc), snapshot='example', semantic_version='1.1.0',
        quality=[], observation_cutoff=req.observation_cutoff.isoformat(),
        queries=[QueryRecord(name=name, sql='select 1', parameters={}, rows=values, elapsed_ms=0, sql_sha256='test')
                 for name, values in raw.items()], results=derive(raw, metric),
    )
    return evidence.model_copy(update={'checksum': checksum(evidence)})


def test_equal_counts_require_compatible_contract_and_import_version():
    first = measurement()
    other = measurement()
    assert compare_sources(first, other, left_epoch=3, right_epoch=3)['status'] == 'agrees'
    assert compare_sources(first, other)['status'] == 'unresolved'
    assert compare_sources(first, other, left_epoch=2, right_epoch=3)['status'] == 'unresolved'
    different = compare_sources(first, measurement('first_attempt_success'), left_epoch=3, right_epoch=3)
    assert different['status'] == 'different_definitions'
    assert different['left']['numerator'] != different['right']['numerator']


def test_conflicting_counts_keep_both_sources_and_reject_foreign_session():
    result = compare_sources(measurement(), measurement(count=6), left_epoch=1, right_epoch=1)
    assert result['status'] == 'unresolved'
    assert result['left']['periods'][1]['numerator'] == 7
    assert result['right']['periods'][1]['numerator'] == 6
    with pytest.raises(ValueError):
        compare_sources(measurement(), measurement(session='someone-else'), left_epoch=1, right_epoch=1)
