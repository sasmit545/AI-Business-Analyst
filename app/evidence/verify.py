"""Recompute all publishable derivations from the executed result records."""
import math

from app.analytics.contributions import aggregate, decompose
from app.evidence.store import checksum
from app.quality.policy import blocked


def verify_evidence(evidence):
    if checksum(evidence) != evidence.checksum:
        raise ValueError('Evidence checksum mismatch')
    if blocked(evidence.quality):
        if evidence.results:
            raise ValueError('Blocked evidence cannot contain certified metrics')
        return
    raw = {q.name: q.rows for q in evidence.queries}
    if 'observations' in raw:
        from app.analytics.adaptive import derive_observations
        if evidence.request.metric != 'attempt_success' or derive_observations(raw['observations']) != evidence.results:
            raise ValueError('Hypothesis result differs from executed evidence')
        return
    if evidence.request.metric != 'attempt_success':
        from app.analytics.lifecycle import derive
        if derive({name:raw[name] for name in ('overall','segments')},evidence.request.metric) != evidence.results:
            raise ValueError('Lifecycle result differs from executed evidence')
        if evidence.observation_cutoff != evidence.request.observation_cutoff.isoformat():
            raise ValueError('Lifecycle cutoff differs from request')
        return
    detail = evidence.request.detail
    tables = ['overall', 'segments', 'daily', 'failures']
    if detail:
        tables.append(detail)
    if set(evidence.results) != {*tables, 'banks', 'methods', 'decomposition'}:
        raise ValueError('Unexpected evidence result inventory')
    for name in tables:
        expected = [dict(row) for row in raw[name]]
        if name not in ('failures', 'transactions'):
            for row in expected:
                n, s = row['attempts'], row['successes']
                if not isinstance(n, int) or not isinstance(s, int) or not 0 <= s <= n:
                    raise ValueError('Invalid counts')
                row['rate'] = s/n if n else None
        if name == 'overall':
            by_period = {r['period']:r for r in expected}
            expected = [by_period.get(i, dict(period=i, attempts=0, successes=0, rate=None)) for i in (0,1)]
        if expected != evidence.results[name]:
            raise ValueError('Derived result differs from executed evidence')
    for name, keys in [('methods', ['payment_method']), ('banks', ['payer_bank_id', 'bank_name'])]:
        if aggregate(evidence.results['segments'], keys) != evidence.results[name]:
            raise ValueError('Roll-up differs from source partition')
    for part, table, keys in [('joint','segments',['payer_bank_id','payment_method']), ('method','methods',['payment_method']), ('bank','banks',['payer_bank_id'])]:
        if decompose(evidence.results[table], keys) != evidence.results['decomposition'][part]:
            raise ValueError('Decomposition differs from source counts')


def verify_claim(claim, evidence):
    verify_evidence(evidence)
    if blocked(evidence.quality) or claim.evidence_id != evidence.id:
        raise ValueError('Claim source is unavailable')
    try:
        observed = evidence.results[claim.table][claim.row][claim.field]
    except (IndexError, KeyError):
        raise ValueError('Unknown result cell') from None
    expected_unit = 'fraction' if claim.field == 'rate' else 'count'
    if claim.unit != expected_unit or observed is None or not math.isfinite(claim.value):
        raise ValueError('Incompatible claim unit or unavailable value')
    if claim.value != observed:
        raise ValueError('Claim value differs from evidence')
    return observed
