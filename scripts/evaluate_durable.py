"""Live follow-up and recovery acceptance using the currently selected lifecycle fixture."""
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluate_analyst import check_sources, live_api
from app.config import Settings
from app.contracts import Evidence
from app.evidence.verify import verify_evidence


def wait_verified(client, prefix, response):
    response.raise_for_status()
    iid = response.json()['investigation_id']
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        result = client.get(f'{prefix}/{iid}')
        result.raise_for_status()
        job = result.json()
        if job['status'] not in ('received', 'running'):
            assert job['status']=='verified', (job['status'],job['error'],job['budget'])
            verify_evidence(Evidence.model_validate(job['evidence']))
            return job
        time.sleep(.25)
    raise TimeoutError('Investigation did not finish within the evaluation deadline')


def attempt_truth(bank, method):
    totals = [[0, 0], [0, 0]]
    with (ROOT/'data/synthetic/phase3/lifecycle_v1/payments.csv').open(newline='') as source:
        for row in csv.DictReader(source):
            day = row['attempted_at'][:10]
            if not '2026-10-01' <= day < '2026-10-29':
                continue
            if row['payer_bank_id'] == bank and row['payment_method'] == method:
                counts = totals[int(day >= '2026-10-15')]
                counts[0] += row['status'] == 'SUCCESS'
                counts[1] += 1
    return totals


def main():
    settings = Settings.from_root()
    report = dict(started=datetime.now(timezone.utc).isoformat(),status='running',model=settings.model)
    windows = (' for 2026-10-01 inclusive to 2026-10-15 exclusive versus '
               '2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata.')
    try:
        with live_api(settings) as client:
            created = client.post('/sessions')
            created.raise_for_status()
            session = created.json()
            assert session['scenario']=='lifecycle_v1', 'Select the lifecycle fixture before this evaluator'
            prefix = '/sessions/'+session['session_id']+'/investigations'
            original = wait_verified(client,prefix,client.post(prefix,json={'question':'Compare payment attempt success'+windows}))
            path = prefix+'/'+original['investigation_id']+'/followup'
            child = wait_verified(client,prefix,client.post(path,json={
                'version':original['version'],'action':'test_hypothesis'}))
            assert child['hypothesis']['status']=='supported', child['hypothesis']['status']
            assert child['budget']['sql_statements']==12
            assert client.post(path,json={'version':original['version'],'action':'test_hypothesis'}).status_code==409
            filters = child['evidence']['request']['filters']
            counts = [[r['successes'],r['attempts']] for r in child['evidence']['results']['overall']]
            assert counts==attempt_truth(filters['payer_bank_id'],filters['payment_method'])
            report['adaptive']=dict(parent=original['evidence']['id'],child=child['evidence']['id'],
                                    filters=filters,counts=counts,budget=child['budget'],
                                    hypothesis=child['hypothesis']['status'],stale_version_rejected=True)
            print('Adaptive segment test passed against independent CSV counts.',flush=True)
            other = wait_verified(client,prefix,client.post(prefix,json={
                'question':'Compare 24-hour order conversion among mature orders'+windows}))
            assert other['evidence']['request']['metric']=='order_conversion'
        with live_api(settings) as client:
            credentials={'session_id':session['resume_id'],'resume_key':session['resume_key']}
            res=client.post('/sessions/resume',json=credentials)
            res.raise_for_status()
            current='/sessions/'+res.json()['session_id']
            assert client.get(prefix+'/'+original['investigation_id']).status_code==404
            restored=client.get(current+'/investigations/'+child['investigation_id']).json()
            assert restored['evidence']==child['evidence'] and restored['hypothesis']==child['hypothesis']
            comparison=client.post(current+'/investigations/'+other['investigation_id']+'/compare',json={
                'version':other['version'],'other_investigation_id':original['investigation_id']})
            comparison.raise_for_status()
            measured=comparison.json()
            assert measured['status']=='different_definitions'
            assert measured['left']['denominator']!=measured['right']['denominator']
            assert measured['left']['import_epoch']==measured['right']['import_epoch']
            report['definition_comparison']=measured
            report['recovery']={'checksummed_evidence_restored':True,'old_handle_rejected':True,
                                'hypothesis_restored':True}
            client.delete(current).raise_for_status()
            assert client.post('/sessions/resume',json=credentials).status_code==404
            print('Recovered evidence and compared different metric definitions.',flush=True)
        report['status']='passed'
    except Exception as exc:
        report['status']='failed'
        report['failure_type']=type(exc).__name__
        raise
    finally:
        report['protected_sources']=check_sources()
        target=ROOT/'reports/analyst'/('durable_live_'+report['status']+'.json')
        target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
