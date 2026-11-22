"""Public-API acceptance with unchanged CSVs and a disposable PostgreSQL cluster."""
import argparse
import csv
import subprocess
import sys
from collections import Counter
import json
from pathlib import Path
import time
import traceback

from evaluate_analyst import check_sources, compare, oracle
from evaluate_analyst_fences import disposable_cluster, pg, setup
from evaluate_lifecycle import compare as compare_lifecycle, independent_truth, request
from fastapi.testclient import TestClient
from httpx import HTTPStatusError

from app.agent.graph import Investigator
from app.agent.model import ToolCall
from app.api.main import create_app
from app.config import Settings, load_env
from app.contracts import Evidence
from app.evidence.verify import verify_evidence


WINDOWS = ('Compare 2026-10-01 inclusive to 2026-10-15 exclusive versus '
           '2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata.')
VOLUME = 'Which failure reason accounted for the most failures in the comparison period?'
DETERIORATION = 'Which failure reason worsened most per completed attempt?'
FOLLOWUP = 'What steps should I take to address this?'


class FixedQueryPlanner:
    """This double chooses an analysis and a chart. It never supplies findings or actions."""
    def __init__(self, metric):
        self.metric = metric

    def next(self, messages, tools, budget):
        if not any(m['role'] == 'tool' for m in messages):
            args = request('order_conversion').model_dump(mode='json')
            args['metric'] = self.metric
            if self.metric == 'attempt_success':
                args.pop('observation_cutoff')
            return ToolCall('analysis', 'analyze_attempts' if self.metric == 'attempt_success' else 'analyze_lifecycle', args)
        observed = next(json.loads(m['content']) for m in reversed(messages) if m['role'] == 'tool')
        views = ['comparison.overall.rate'] if observed['quality_status'] != 'BLOCK' else []
        return ToolCall('publish', 'publish_answer', {'evidence_id':observed['evidence_id'], 'views':views})


def settled(client, path, timeout=145):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        job = response.json()
        if job['status'] not in ('running','received'):
            return job
        time.sleep(.2)
    raise TimeoutError('Private evaluation exceeded the investigation deadline')


def exchange(root, settings, question, metric='attempt_success', *, live=False, follow=False):
    def runner(auth, store):
        return Investigator(settings, auth, store, model=FixedQueryPlanner(metric))
    api = create_app(settings=settings, root=root, runner_factory=None if live else runner)
    with TestClient(api) as client:
        client.headers['Authorization'] = 'Bearer '+(root/'.local/analyst/api_token').read_text()
        opened = client.post('/sessions')
        opened.raise_for_status()
        start = '/sessions/'+opened.json()['session_id']
        try:
            job_path = start+'/investigations'
            created = client.post(job_path, json={'question':question+' '+WINDOWS})
            created.raise_for_status()
            parent = job_path+'/'+created.json()['investigation_id']
            job = settled(client, parent)
            child = None
            if follow and job['status']=='verified':
                posted = client.post(parent+'/followup', json={'version':job['version'],'question':FOLLOWUP,'action':'question'})
                posted.raise_for_status()
                child = settled(client, job_path+'/'+posted.json()['investigation_id'])
            return job, child
        finally:
            client.delete(start).raise_for_status()


def receipt(job, *, blocked=False, child=None):
    assert job['status'] == ('blocked' if blocked else 'verified'), (job['status'],job.get('error'))
    evidence = Evidence.model_validate(job['evidence'])
    verify_evidence(evidence)
    content = job['narrative']
    guidance = content['guidance']
    assert guidance['evidence_id'] == evidence.id
    assert guidance['reference'] == job['dashboard']['finding_ref']
    assert guidance['recommendations'] == content['recommendations']
    result = dict(question=job['question'], status=job['status'], evidence_id=evidence.id,
                  plan=content['analysis_plan'], answer=content['answer'], guidance=guidance,
                  sql=[{'name':q.name,'sql':q.sql,'parameters':q.parameters} for q in evidence.queries],
                  chart_bindings=job['dashboard']['blocks'], chart_overall=evidence.results.get('overall'),
                  budget=job['budget'])
    if child is not None:
        assert child['status']=='verified', (child['status'],child.get('error'))
        assert child['evidence']['reused_from'] == evidence.id and child['budget']['sql_statements'] == 0
        assert child['evidence']['results'] == evidence.results
        assert child['narrative']['recommendations'] == content['recommendations']
        result['followup'] = {'question':FOLLOWUP, 'answer':child['narrative']['answer'],
                              'evidence_id':child['evidence']['id'], 'reused_from':evidence.id,
                              'analytical_statements':child['budget']['sql_statements']}
    return evidence, result


def write_report(path, report):
    path.write_text(json.dumps(report, indent=2, default=str)+'\n', encoding='utf8')


def require_disposable_database(root):
    permitted_parent = (pg.ROOT / '.local/analyst/fence-tests').resolve()
    if root.resolve().parent != permitted_parent or pg.PGDATA.resolve() != (root / '.local/postgres/pgdata').resolve():
        raise RuntimeError('Journey evaluation requires its own disposable cluster')
    pg.check_server_identity()


def controlled_attempt(report, root, settings, name, question):
    require_disposable_database(root)
    pg.select_scenario(name)
    dirty = name == 'scenario_a_dirty'
    job, child = exchange(root, settings, question, follow=not dirty)
    evidence, data = receipt(job, blocked=dirty, child=child)
    if dirty:
        blocks = {q.rule:q.count for q in evidence.quality if q.status=='BLOCK'}
        assert blocks == {'duplicate_occurrences':20,'missing_timestamps':10,'orphan_merchants':10}, blocks
        assert not evidence.results and not job['dashboard']['blocks'] and len(data['guidance']['recommendations']) >= 3
    else:
        compare(evidence, oracle(name))
        assert any(b['source']=='overall' and b['measure']=='rate' for b in data['chart_bindings'])
        if name == 'scenario_a':
            assert data['guidance']['leaders'] == [{'payer_bank_id':'BANK_B','payment_method':'UPI'}], data['guidance']
        else:
            assert 'mix' in data['guidance']['finding'].lower() or 'traffic' in data['guidance']['finding'].lower()
            assert abs(evidence.results['decomposition']['method']['within'])<1e-8
    report['cases'][name] = data
    print(name, job['status'], flush=True)


def controlled_rankings(report, root, settings):
    require_disposable_database(root)
    pg.select_scenario('scenario_a')
    # The connection points exclusively to the verified disposable data directory.
    # Synthetic 100-attempt windows improve overall despite one worsening reason.
    pg.psql("""BEGIN;
        TRUNCATE scenario_a.payments;
        INSERT INTO scenario_a.payments
        SELECT 'A'||lpad((p*100+i)::text,6,'0'),
               CASE WHEN p=0 THEN '2026-10-05T00:00:00+05:30' ELSE '2026-10-20T00:00:00+05:30' END,
               'M01', CASE WHEN i%2=0 THEN 'BANK_A' ELSE 'BANK_C' END, 'UPI','100','INR',
               CASE WHEN i<=a+b THEN 'FAILED' ELSE 'SUCCESS' END,
               CASE WHEN i<=a THEN 'INSUFFICIENT_FUNDS' WHEN i<=a+b THEN 'BANK_TIMEOUT' ELSE '' END
        FROM (VALUES (0,20,2),(1,14,5)) AS periods(p,a,b) CROSS JOIN generate_series(1,100) AS sequence(i);
        COMMIT;""")
    for permutation in ('original','swapped'):
        if permutation == 'swapped':
            pg.psql("""UPDATE scenario_a.payments SET failure_reason =
                CASE failure_reason WHEN 'INSUFFICIENT_FUNDS' THEN 'BANK_TIMEOUT' ELSE 'INSUFFICIENT_FUNDS' END
                WHERE status='FAILED'""")
        answers = {}
        for question, kind in ((VOLUME,'volume'), (DETERIORATION,'deterioration')):
            job, child = exchange(root, settings, question, follow=True)
            evidence, data = receipt(job, child=child)
            assert [r['successes'] for r in evidence.results['overall']]==[78,81]
            assert [r['attempts'] for r in evidence.results['overall']]==[100,100]
            high = 'INSUFFICIENT_FUNDS' if permutation=='original' else 'BANK_TIMEOUT'
            rising = 'BANK_TIMEOUT' if permutation=='original' else 'INSUFFICIENT_FUNDS'
            expected = high if kind=='volume' else rising
            assert data['guidance']['leaders']==[{'failure_reason':expected}], data['guidance']
            assert expected in data['guidance']['finding'] and expected in ' '.join(data['guidance']['recommendations'])
            assert data['plan']['objective']['kind']==kind
            answers[kind] = data
        assert answers['volume']['guidance']['recommendations'] != answers['deterioration']['guidance']['recommendations']
        report['cases']['rankings_'+permutation] = answers
        print('rankings',permutation,'passed',flush=True)


def three_bank_mix(report, root, settings):
    """The bank gaining the most traffic offsets the decline in this fixture."""
    require_disposable_database(root)
    pg.select_scenario('scenario_b')
    pg.psql("""BEGIN;
        TRUNCATE scenario_b.payments;
        INSERT INTO scenario_b.payments
        SELECT 'B'||lpad(row_number() OVER (ORDER BY p, bank, i)::text, 6, '0'),
               CASE WHEN p=0 THEN '2026-10-05T00:00:00+05:30' ELSE '2026-10-20T00:00:00+05:30' END,
               'M01', bank, 'UPI', '100', 'INR',
               CASE WHEN i<=failures THEN 'FAILED' ELSE 'SUCCESS' END,
               CASE WHEN i<=failures THEN 'BANK_TIMEOUT' ELSE '' END
        FROM (VALUES (0,'BANK_A',100,10), (1,'BANK_A',700,70), (0,'BANK_B',100,100),
                     (1,'BANK_B',150,150), (0,'BANK_C',800,80), (1,'BANK_C',150,15))
                AS portions(p,bank,attempts,failures)
        CROSS JOIN LATERAL generate_series(1,attempts) AS gen(i);
        COMMIT;""")
    parent, child = exchange(root, settings, 'Which bank contributed most to the change in attempt success?', follow=True)
    evidence, data = receipt(parent, child=child)
    assert [(row['successes'], row['attempts']) for row in evidence.results['overall']] == [(810, 1000), (765, 1000)]
    joint = evidence.results['decomposition']['joint']
    assert abs(joint['mix'] + .045) < 1e-8 and abs(joint['within']) < 1e-8
    assert data['guidance']['leaders'] == [{'payer_bank_id': 'BANK_B'}], data['guidance']['finding']
    assert '10.00% to 15.00%' in data['guidance']['finding']
    report['cases']['three_bank_offsets'] = data
    print('three-bank directional mix passed', flush=True)


def hosted_probe(dbroot, output):
    if dbroot.resolve().parent != (pg.ROOT/'.local/analyst/fence-tests').resolve():
        raise RuntimeError('Hosted verification requires a disposable evaluation root')
    load_env(pg.ROOT/'.env')
    settings = Settings.from_root(dbroot)
    probe = {'provider':'nvidia', 'model':settings.model}
    try:
        job, child = exchange(dbroot, settings, VOLUME, live=True, follow=True)
        probe.update(status=job['status'], error=job.get('error'), budget=job.get('budget'))
        if job['status']=='verified':
            _, checked = receipt(job, child=child)
            counts = Counter()
            with (pg.data_path('lifecycle_v1')/'payments.csv').open(encoding='utf8',newline='') as stream:
                for row in csv.DictReader(stream):
                    if '2026-10-15' <= row['attempted_at'][:10] < '2026-10-29' and row['status']=='FAILED':
                        counts[row['failure_reason']] += 1
            winners = sorted(key for key, value in counts.items() if value==max(counts.values()))
            assert checked['guidance']['leaders']==[{'failure_reason':name} for name in winners]
            probe.update(result=checked, independent_counts=counts)
    except Exception as exc:
        probe.update(status='failed', error_type=type(exc).__name__)
    write_report(output, probe)


def run(dbroot, output, live):
    require_disposable_database(dbroot)
    settings = Settings.from_root(dbroot)
    report = {'mode':'private FastAPI TestClient, native PostgreSQL, deterministic query planner',
              'protected_before':check_sources(), 'cases':{}, 'errors':{}, 'status':'running'}

    def attempt_case(name, exercise):
        try:
            exercise()
        except (AssertionError, RuntimeError, TimeoutError, HTTPStatusError) as exc:
            point = traceback.extract_tb(exc.__traceback__)[-1]
            report['errors'][name] = {'error_type':type(exc).__name__, 'message':str(exc)[:650],
                                      'location':f'{Path(point.filename).name}:{point.lineno}'}
            print(name, 'failed:', type(exc).__name__, flush=True)
        write_report(output, report)

    try:
        for name, question in [
            ('scenario_a', 'Which bank and payment method contributed most to the change in attempt success?'),
            ('scenario_b', 'Why did overall success change by payment method?'),
            ('scenario_a_dirty', 'Compare payment attempt success.')]:
            attempt_case(name, lambda: controlled_attempt(report, dbroot, settings, name, question))
        attempt_case('rankings', lambda: controlled_rankings(report, dbroot, settings))
        attempt_case('three_bank_offsets', lambda: three_bank_mix(report, dbroot, settings))
        pg.select_scenario('lifecycle_v1')
        truth, segments, health = independent_truth()

        def lifecycle_case(metric):
            question = 'Compare '+metric.replace('_',' ')+' by bank and payment method.'
            job, child = exchange(dbroot, settings, question, metric, follow=True)
            evidence, data = receipt(job, child=child)
            compare_lifecycle(evidence, truth, segments, health)
            assert data['guidance']['recommendations'] and data['chart_bindings']
            report['cases'][metric] = data
            print(metric,'passed',flush=True)

        for metric in truth:
            attempt_case(metric, lambda: lifecycle_case(metric))
        report['controlled_status'] = 'failed' if report['errors'] else 'passed'
        report['status'] = report['controlled_status']
        write_report(output, report)
        if live:
            probe_output = output.with_name(output.stem+'_hosted.json')
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--probe-root', str(dbroot),
                       '--report', str(probe_output)]
            try:
                subprocess.run(command, check=True, timeout=155)
                probe = json.loads(probe_output.read_text(encoding='utf8'))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                probe = {'status':'failed', 'error_type':type(exc).__name__}
                write_report(probe_output, probe)
            report['hosted_model'] = {'status':probe['status'], 'report':probe_output.name}
            if probe['status']!='verified' and report['status']=='passed':
                report['status'] = 'controlled_passed_hosted_unverified'
            print('hosted model',probe['status'],flush=True)
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__)
        raise
    finally:
        report['protected_after']=check_sources()
        write_report(output, report)
    if report['errors']:
        raise AssertionError(f"Journey validation failed in {list(report['errors'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--live-model', action='store_true')
    parser.add_argument('--probe-root', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe_root:
        hosted_probe(args.probe_root, args.report)
        return
    with disposable_cluster() as root:
        pg.create_database()
        pg.bootstrap()
        pg.psql(pg.ingestion_sql(), timeout=600)
        pg.psql('ANALYZE',timeout=180)
        pg.select_scenario('lifecycle_v1')
        setup.install()
        run(root, args.report, args.live_model)


if __name__=='__main__':
    main()
