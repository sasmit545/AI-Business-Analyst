"""Registered lifecycle calculations; order outcomes are reduced before joins."""
from datetime import datetime, timezone

from app.contracts import Evidence
from app.context.catalog import asset
from app.quality.checks import check_quality
from app.quality.policy import blocked
from app.query.executor import Bundle


DEFINITIONS = {name:(value['label'],value['numerator'],value['denominator'])
               for name,value in asset('metrics')['implemented'].items() if name!='attempt_success'}


def parameters(request):
    return {'b_start':request.baseline.start.isoformat(), 'b_end':request.baseline.end.isoformat(),
            'c_start':request.comparison.start.isoformat(), 'c_end':request.comparison.end.isoformat(),
            'cutoff':request.observation_cutoff.isoformat(), **request.filters.model_dump(exclude_none=True)}


def compile_lifecycle(scenario, request):
    if scenario != 'lifecycle_v1':
        raise ValueError('Lifecycle metrics require the selected lifecycle schema')
    if request.metric == 'bank_health':
        from app.analytics.health import compile_health
        return compile_health(request)
    params=parameters(request)
    cutoff='%(cutoff)s::timestamptz'
    if request.metric.startswith('settlement_'):
        source=f'''SELECT p.payer_bank_id, p.payment_method, p.merchant_id,
            p.attempted_at::timestamptz AS event_time,
            CASE WHEN s.due_at::timestamptz <= {cutoff} THEN 1 ELSE 0 END AS eligible,
            CASE WHEN s.due_at::timestamptz <= {cutoff} AND s.settlement_status='SETTLED'
                 AND CAST(NULLIF(s.settled_at, '') AS TIMESTAMPTZ) <= {cutoff} THEN 1 ELSE 0 END AS completed,
            s.gross_amount_paise::bigint AS amount
            FROM lifecycle_v1.payments p JOIN lifecycle_v1.settlements s ON p.attempt_id=s.attempt_id
            WHERE p.status='SUCCESS' AND p.completed_at::timestamptz <= {cutoff}
              AND p.ingested_at::timestamptz <= {cutoff}'''
        denominator='r.eligible' if request.metric=='settlement_count' else 'r.eligible*r.amount'
        numerator='r.completed' if request.metric=='settlement_count' else 'r.completed*r.amount'
    else:
        # The quality gate proves one initial attempt per order. Only retries need
        # grouping before the order join.
        retries=f'''SELECT p.order_id, COUNT(*) AS retries,
            MIN(CASE WHEN p.status='SUCCESS' THEN p.completed_at::timestamptz END) AS success_at
            FROM lifecycle_v1.payments p WHERE p.attempt_number<>'1' AND p.completed_at::timestamptz <= {cutoff}
              AND p.ingested_at::timestamptz <= {cutoff} GROUP BY p.order_id'''
        success=f"COALESCE(CASE WHEN a.status='SUCCESS' THEN a.completed_at::timestamptz END, retries.success_at)"
        source=f'''SELECT a.payer_bank_id, a.payment_method, o.merchant_id,
            o.created_at AS event_time,
            CASE WHEN o.created_at + INTERVAL '24 hours' <= {cutoff} THEN 1 ELSE 0 END AS eligible,
            CASE WHEN a.status='SUCCESS' THEN 1 ELSE 0 END AS first_success,
            CASE WHEN a.status='FAILED' THEN 1 ELSE 0 END AS first_failed,
            CASE WHEN retries.retries>0 THEN 1 ELSE 0 END AS retried,
            CASE WHEN {success} IS NOT NULL THEN 1 ELSE 0 END AS recovered,
            CASE WHEN {success} <= o.created_at + INTERVAL '24 hours' THEN 1 ELSE 0 END AS converted
            FROM (SELECT order_id, merchant_id, created_at::timestamptz AS created_at FROM lifecycle_v1.orders OFFSET 0) o
            LEFT JOIN lifecycle_v1.payments a ON o.order_id=a.order_id
                AND a.attempt_number='1' AND a.completed_at::timestamptz<={cutoff} AND a.ingested_at::timestamptz<={cutoff}
            LEFT JOIN ({retries}) retries ON o.order_id=retries.order_id'''
        if request.metric.startswith('retry_'):
            source+=" WHERE a.status='FAILED'"
        numerator,denominator={
            'order_conversion':('r.converted*r.eligible','r.eligible'),
            'first_attempt_success':('r.first_success*r.eligible','r.eligible'),
            'retry_uptake':('r.retried*r.first_failed*r.eligible','r.first_failed*r.eligible'),
            'retry_recovery_all':('r.recovered*r.first_failed*r.eligible','r.first_failed*r.eligible'),
            'retry_recovery_retried':('r.recovered*r.first_failed*r.eligible','r.retried*r.first_failed*r.eligible'),
        }[request.metric]
    return aggregate_queries(source, numerator, denominator, params),params


def aggregate_queries(source, numerator, denominator, params, extra=''):
    period='CASE WHEN r.event_time >= %(b_start)s::timestamptz AND r.event_time < %(b_end)s::timestamptz THEN 0 ELSE 1 END'
    where='((r.event_time >= %(b_start)s::timestamptz AND r.event_time < %(b_end)s::timestamptz) OR (r.event_time >= %(c_start)s::timestamptz AND r.event_time < %(c_end)s::timestamptz))'
    for key in ('payer_bank_id','payment_method','merchant_id'):
        if key in params:
            where+=f' AND r.{key}=%({key})s'
    queries={}
    for name,dims in [('overall',[]),('segments',['r.payer_bank_id','r.payment_method'])]:
        columns=', '.join([period+' AS period',*dims])
        groups=', '.join(str(i) for i in range(1,len(dims)+2))
        queries[name]=f'''SELECT {columns}, COALESCE(SUM({numerator}),0)::bigint AS numerator,
            COALESCE(SUM({denominator}),0)::bigint AS denominator,
            SUM(1-r.eligible)::bigint AS excluded {extra}
            FROM ({source} OFFSET 0) r WHERE {where} GROUP BY {groups} ORDER BY {groups}'''
    return queries


def derive(raw, metric=None):
    results={key:[dict(row) for row in rows] for key,rows in raw.items()}
    for rows in results.values():
        for row in rows:
            n,d=row['numerator'],row['denominator']
            if not isinstance(n,int) or not isinstance(d,int) or not 0 <= n <= d:
                raise ValueError('Invalid lifecycle numerator or denominator')
            row['rate']=n/d if d else None
    periods={r['period']:r for r in results['overall']}
    empty_health=({'unmatched':0,'attempt_weighted_availability_pct':None,'attempt_weighted_bucket_p95_ms':None}
                  if metric=='bank_health' or any('unmatched' in row for rows in raw.values() for row in rows) else {})
    results['overall']=[periods.get(i,dict(period=i,numerator=0,denominator=0,excluded=0,rate=None,**empty_health)) for i in (0,1)]
    for row in results['overall']:
        for field in ('numerator','denominator','excluded'):
            if sum(r[field] for r in results['segments'] if r['period']==row['period']) != row[field]:
                raise ValueError('Lifecycle partition reconciliation failed')
    return results


def analyze(settings, authorization, scope, request, budget):
    from app.quality.lifecycle import check_lifecycle_quality
    if scope.scenario != authorization.scenario or scope.scenario != 'lifecycle_v1':
        raise ValueError('Lifecycle metric unavailable in selected scope')
    with Bundle(settings,authorization,budget) as bundle:
        quality=check_quality(bundle)
        if not blocked(quality):
            quality.extend(check_lifecycle_quality(bundle,request.metric))
        results={}
        if not blocked(quality):
            queries,params=compile_lifecycle(scope.scenario,request)
            raw = {name:bundle.query(name,sql,params) for name,sql in queries.items()}
        bundle.seal()
        if not blocked(quality):
            results=derive(raw,request.metric)
            if request.metric=='bank_health':
                from app.contracts import QualityRecord
                missing=sum(r.get('unmatched',0) for r in results['overall'])
                quality.append(QualityRecord(rule='unmatched_health_attempts',count=missing,
                    status='WARN' if missing else 'PASS',metric='bank_health',scope='selected observed attempts'))
        evidence=Evidence(scope=scope,request=request,semantic_version='1.1.0',
            created_at=datetime.now(timezone.utc),snapshot=bundle.snapshot,quality=quality,
            queries=bundle.records,results=results,observation_cutoff=request.observation_cutoff.isoformat())
    authorization.check()
    return evidence
