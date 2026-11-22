from datetime import datetime, timezone

from app.analytics.contributions import aggregate, decompose
from app.contracts import Evidence
from app.quality.checks import check_quality
from app.quality.policy import blocked
from app.query.compiler import compile_queries
from app.query.executor import Bundle


def analyze(settings, authorization, scope, request, budget):
    if scope.scenario != authorization.scenario:
        raise ValueError('Scope mismatch')
    with Bundle(settings, authorization, budget) as bundle:
        quality = check_quality(bundle)
        results = {}
        if not blocked(quality):
            queries, parameters = compile_queries(scope.scenario, request)
            results = {name: bundle.query(name, sql, parameters) for name, sql in queries.items()}
        bundle.seal()
        if not blocked(quality):
            partitions = ['segments', 'daily']
            if request.detail in ('merchant_categories', 'merchants'):
                partitions.append(request.detail)
            for name in ('overall', *partitions):
                for row in results[name]:
                    row['rate'] = row['successes']/row['attempts'] if row['attempts'] else None
            by_period = {r['period']: r for r in results['overall']}
            results['overall'] = [by_period.get(i, dict(period=i, attempts=0, successes=0, rate=None)) for i in (0, 1)]
            for i, overall in enumerate(results['overall']):
                for table in partitions:
                    for count in ('attempts', 'successes'):
                        if sum(r[count] for r in results[table] if r['period'] == i) != overall[count]:
                            raise ValueError('Partition count reconciliation failed')
                if sum(r['count'] for r in results['failures'] if r['period'] == i) != overall['attempts'] - overall['successes']:
                    raise ValueError('Failure count reconciliation failed')
            results['methods'] = aggregate(results['segments'], ['payment_method'])
            results['banks'] = aggregate(results['segments'], ['payer_bank_id', 'bank_name'])
            results['decomposition'] = {
                'joint': decompose(results['segments'], ['payer_bank_id', 'payment_method']),
                'method': decompose(results['methods'], ['payment_method']),
                'bank': decompose(results['banks'], ['payer_bank_id']),
            }
        evidence = Evidence(scope=scope, request=request, created_at=datetime.now(timezone.utc),
                            snapshot=bundle.snapshot, quality=quality, queries=bundle.records,
                            results=results, observation_cutoff='2026-11-01T00:00:00+05:30' if scope.scenario == 'lifecycle_v1' else None)
    authorization.check()
    return evidence
