"""Test an observed segment using one fresh grouped query against the same import."""
from collections import defaultdict
from datetime import datetime, timezone

from app.analytics.contributions import aggregate, decompose
from app.contracts import Evidence, QualityRecord
from app.evidence.verify import verify_evidence
from app.quality.policy import blocked
from app.query.compiler import compile_queries
from app.query.executor import BudgetExceeded, Bundle


def derive_observations(rows):
    dims = ['payer_bank_id', 'bank_name', 'payment_method']
    failures = defaultdict(int)
    for row in rows:
        total, successes = row['attempts'], row['successes']
        if type(total) is not int or total <= 0 or successes != (total if row['status']=='SUCCESS' else 0):
            raise ValueError('Invalid adaptive observation')
        if row['status']=='FAILED':
            key = tuple(row[k] for k in ('period', *dims, 'failure_reason'))
            failures[key] += total
        elif row['status']!='SUCCESS':
            raise ValueError('Invalid attempt status')
    segments = aggregate(rows, dims)
    overall = {row['period']:row for row in aggregate(rows, [])}
    methods = aggregate(segments, ['payment_method'])
    banks = aggregate(segments, dims[:2])
    return {
        'overall':[overall.get(p,dict(period=p,attempts=0,successes=0,rate=None)) for p in (0,1)],
        'segments':segments, 'daily':aggregate(rows,['day']), 'methods':methods, 'banks':banks,
        'failures':[dict(zip(('period', *dims, 'failure_reason'),key),count=n) for key,n in sorted(failures.items())],
        'decomposition':{'joint':decompose(segments,['payer_bank_id','payment_method']),
                         'method':decompose(methods,['payment_method']),'bank':decompose(banks,['payer_bank_id'])},
    }


def test_segment(settings, authorization, store, scope, request, budget, parent):
    # The post-query write requires the same live generation and immutable import epoch.
    if scope.session_id != parent.scope.session_id or scope.subject != parent.scope.subject or scope.scenario != parent.scope.scenario:
        raise ValueError('Hypothesis belongs to another authorization')
    parent = store.get(parent.id, parent.scope)
    verify_evidence(parent)
    if blocked(parent.quality) or request != parent.request.model_copy(update={'filters':request.filters}):
        raise ValueError('Hypothesis requires verified compatible measurements')
    inherited = parent.request.filters.model_dump(exclude_none=True)
    current = request.filters.model_dump(exclude_none=True)
    if not inherited.items() < current.items():
        raise ValueError('Hypothesis must narrow the parent population')
    replay = budget.journal is not None and budget.journal.replay is not None
    if request.metric != 'attempt_success' or (not replay and budget.statements + 4 > 12):
        raise BudgetExceeded('Insufficient SQL allowance for this additional hypothesis test')
    with store.connect() as conn, store.authorized(conn, scope) as fingerprint:
        epoch = fingerprint['import_epoch']
    queries, params = compile_queries(scope.scenario, request, adaptive=True)
    with Bundle(settings,authorization,budget) as bundle:
        rows = bundle.query('observations', queries['observations'], params)
        bundle.seal()
        evidence = Evidence(
            scope=scope, request=request, created_at=datetime.now(timezone.utc), snapshot=bundle.snapshot,
            observation_cutoff=parent.observation_cutoff,
            quality=[*parent.quality, QualityRecord(rule='inherited_quality',count=0,status='PASS',
                scope=f'Evidence {parent.id}, checksum {parent.checksum}, import epoch {epoch}')],
            queries=bundle.records, results=derive_observations(rows),
        )
    authorization.check()
    return evidence
