"""Independent evaluator: CSV ground truth and administrative authority stay here."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from evaluate_analyst import check_sources, live_api, live_question, permission_probes
from app.analytics.lifecycle import analyze, DEFINITIONS
from app.config import Settings
from app.contracts import Evidence, LifecycleRequest, Scope
from app.evidence.store import EvidenceStore
from app.evidence.verify import verify_evidence
from app.evidence.render_claims import narrative, publication_narrative
from app.ui_specs.validate import read_layout
from app.query.executor import Authorization, Budget
import postgres_phase1 as admin


def request(metric):
    return LifecycleRequest(metric=metric,
        baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},
        comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'})


def independent_truth():
    def table(name):
        with (ROOT/'data/synthetic/phase3/lifecycle_v1'/f'{name}.csv').open(newline='',encoding='utf-8') as f:
            return list(csv.DictReader(f))
    orders=table('orders'); payments=table('payments'); settlements={r['attempt_id']:r for r in table('settlements')}
    health={(r['bank_id'],r['payment_method'],datetime.fromisoformat(r['observed_at'])):r for r in table('bank_health')}
    health_totals=defaultdict(lambda:[0,0.0,0])
    by_order=defaultdict(list)
    for p in payments: by_order[p['order_id']].append(p)
    req=request('order_conversion')
    cutoff=req.observation_cutoff
    windows=(req.baseline,req.comparison)
    result={m:[{'numerator':0,'denominator':0},{'numerator':0,'denominator':0}] for m in DEFINITIONS}
    segments={m:defaultdict(lambda:[0,0]) for m in DEFINITIONS}
    def period(stamp):
        t=datetime.fromisoformat(stamp)
        for i,w in enumerate(windows):
            if w.start<=t<w.end: return i
        return None
    def add(metric,i,bank,method,n,d):
        result[metric][i]['numerator']+=int(n);result[metric][i]['denominator']+=int(d)
        segments[metric][(i,bank,method)][0]+=int(n);segments[metric][(i,bank,method)][1]+=int(d)
    for o in orders:
        i=period(o['created_at']); created=datetime.fromisoformat(o['created_at'])
        if i is None or created+timedelta(hours=24)>cutoff: continue
        attempts=[p for p in by_order[o['order_id']] if datetime.fromisoformat(p['ingested_at'])<=cutoff and datetime.fromisoformat(p['completed_at'])<=cutoff]
        first=next(p for p in attempts if p['attempt_number']=='1')
        failed=first['status']=='FAILED'; retried=len(attempts)>1
        success=next((p for p in attempts if p['status']=='SUCCESS'),None)
        converted=success is not None and datetime.fromisoformat(success['completed_at'])<=created+timedelta(hours=24)
        values={'order_conversion':(converted,1),'first_attempt_success':(not failed,1),
                'retry_uptake':(failed and retried,failed),'retry_recovery_all':(failed and success is not None,failed),
                'retry_recovery_retried':(failed and success is not None,failed and retried)}
        for metric,(n,d) in values.items(): add(metric,i,first['payer_bank_id'],first['payment_method'],n,d)
    for p in payments:
        i=period(p['attempted_at'])
        if i is None or datetime.fromisoformat(p['ingested_at'])>cutoff: continue
        bank,method=p['payer_bank_id'],p['payment_method']
        add('bank_health',i,bank,method,p['status']=='SUCCESS',1)
        t=datetime.fromisoformat(p['attempted_at']);bucket=t.replace(minute=t.minute//5*5,second=0,microsecond=0)
        observation=health.get((bank,method,bucket))
        if observation:
            for key in ((i,bank,method),(i,None,None)):
                h=health_totals[key];h[0]+=1;h[1]+=float(observation['availability_pct']);h[2]+=int(observation['p95_latency_ms'])
        if p['status']!='SUCCESS': continue
        s=settlements[p['attempt_id']]
        if datetime.fromisoformat(s['due_at'])>cutoff: continue
        settled=s['settlement_status']=='SETTLED' and datetime.fromisoformat(s['settled_at'])<=cutoff
        add('settlement_count',i,bank,method,settled,1)
        amount=int(s['gross_amount_paise']);add('settlement_amount',i,bank,method,amount if settled else 0,amount)
    # Independently computed period sums must also match the original saved SQL answers.
    original=json.loads((ROOT/'evaluation/phase3/expected_answers.json').read_text())['metrics']
    totals={m:(sum(r['numerator'] for r in rows),sum(r['denominator'] for r in rows)) for m,rows in result.items()}
    assert totals['order_conversion']==(original['orders'][0]['paid_orders_24h'],original['orders'][0]['eligible_orders'])
    assert totals['retry_recovery_all']==(original['retries'][0]['recovered_orders'],original['retries'][0]['initially_failed_orders'])
    assert totals['retry_recovery_retried'][1]==original['retries'][0]['retried_orders']
    assert totals['settlement_count']==(original['settlements'][0]['settled_due_attempts'],original['settlements'][0]['due_attempts'])
    assert totals['settlement_amount'][0]==original['settlements'][0]['settled_amount_paise']
    assert totals['bank_health']==(original['attempts'][0]['successes'],original['attempts'][0]['attempts'])
    return result,segments,health_totals


def compare(evidence,truth,segments,health_totals):
    verify_evidence(evidence)
    metric=evidence.request.metric
    assert evidence.request==request(metric)
    assert not any(q.status=='BLOCK' for q in evidence.quality)
    for actual,expected in zip(evidence.results['overall'],truth[metric]):
        assert (actual['numerator'],actual['denominator'])==(expected['numerator'],expected['denominator'])
    actual={(r['period'],r['payer_bank_id'],r['payment_method']):[r['numerator'],r['denominator']] for r in evidence.results['segments']}
    assert actual==dict(segments[metric])
    if metric=='bank_health':
        assert sum(r['unmatched'] for r in evidence.results['overall'])==0
        for row in evidence.results['overall']+evidence.results['segments']:
            n,availability,latency=health_totals[(row['period'],row.get('payer_bank_id'),row.get('payment_method'))]
            assert n==row['denominator']
            assert abs(row['attempt_weighted_availability_pct']-availability/n)<1e-9
            assert abs(row['attempt_weighted_bucket_p95_ms']-latency/n)<1e-9


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live-model',action='store_true')
    parser.add_argument('--report',type=Path,help='Write the results to a separate acceptance report')
    args=parser.parse_args()
    settings=Settings.from_root();truth,segments,health_totals=independent_truth()
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'mode':'live_model_api_sql' if args.live_model else 'restricted_sql',
            'provider':'nvidia' if args.live_model else None,'model':settings.model if args.live_model else None,
            'status':'running','metrics':[],'protected_sources_before':check_sources()}
    report_dir=ROOT/'reports/analyst'; store=EvidenceStore(settings.evidence_dir)
    try:
        admin.select_scenario('lifecycle_v1')
        with (live_api(settings) if args.live_model else nullcontext()) as client:
            for metric in DEFINITIONS:
                report['current_metric']=metric
                print(metric+': checking',flush=True)
                started=time.monotonic();req=request(metric)
                question=f'Compare {DEFINITIONS[metric][0]} ({metric}) for 2026-10-01 inclusive to 2026-10-15 exclusive versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. Use observation cutoff 2026-11-01T00:00:00+05:30. Show the registered numerator and denominator with bank/method segments.'
                if args.live_model:
                    answer=live_question(client,question)
                    report['last_investigation']={k:answer.get(k) for k in ('status','error','budget')}
                    assert answer['status']=='verified',report['last_investigation']
                    evidence=Evidence.model_validate(answer['evidence'])
                    content = publication_narrative(evidence, read_layout(answer['dashboard'], evidence))
                    assert answer['narrative'] == content
                else:
                    auth=Authorization(settings)
                    try: evidence=store.put(analyze(settings,auth,Scope(scenario=auth.scenario,session_id='lifecycle-evaluation'),req,Budget()),'analysis')
                    finally: auth.close()
                compare(evidence,truth,segments,health_totals)
                if not args.live_model:
                    content = narrative(evidence)
                report['metrics'].append({'metric':metric,'status':'passed','evidence_id':evidence.id,'checksum':evidence.checksum,'question':question,'overall':evidence.results['overall'],'statement_count':len(evidence.queries)+3,'query_timings_ms':{q.name:q.elapsed_ms for q in evidence.queries},'elapsed_seconds':time.monotonic()-started})
                print(metric+': passed',flush=True)
                report['metrics'][-1].update(plan=content['analysis_plan'], guidance=content['guidance'],
                    sql=[{'name':q.name, 'sql':q.sql, 'parameters':q.parameters} for q in evidence.queries])
        report['denial_probes']=permission_probes(settings,'lifecycle_v1')
        report['status']='passed'
    except Exception as exc:
        report['status']='failed';report['failure_type']=type(exc).__name__
        raise
    finally:
        admin.select_scenario('lifecycle_v1')
        auth=Authorization(settings)
        try: assert auth.scenario=='lifecycle_v1';report['restored_selection']='lifecycle_v1'
        finally: auth.close()
        report['protected_sources_after']=check_sources()
        target = args.report or report_dir/('lifecycle_live_acceptance.json' if args.live_model else 'lifecycle_sql_acceptance.json')
        target.write_text(json.dumps(report,indent=2)+'\n', encoding='utf-8')


if __name__=='__main__': main()
