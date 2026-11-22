"""Evaluator process only: independent truths and administrative selection live here."""
import argparse
import hashlib
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import postgres_phase1 as admin
from app.analytics.attempts import analyze
from app.config import Settings
from app.contracts import AnalysisRequest, Evidence, Scope, Status
from app.evidence.render_claims import narrative, publication_narrative
from app.ui_specs.validate import read_layout
from app.evidence.store import EvidenceStore
from app.evidence.verify import verify_evidence
from app.query.executor import Authorization, Budget, StaleSession, connect

SCENARIOS = ['scenario_a','scenario_b','scenario_a_dirty','phase2_baseline','phase2_incident','lifecycle_v1']


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def check_sources():
    before = read('reports/analyst/protected_sources_before.json')
    changed = [name for name,digest in before.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if changed:
        raise AssertionError('Protected input changed: '+', '.join(changed))
    return {'files':len(before),'csv_files':len(list((ROOT/'data/synthetic').rglob('*.csv'))),'changed':changed}


def oracle(scenario):
    if scenario.startswith('scenario_'):
        return read('evaluation/phase1/expected_answers.json')['scenarios'][scenario]
    if scenario.startswith('phase2_'):
        return read('evaluation/phase2/expected_answers.json')['variants'][scenario.removeprefix('phase2_')]
    return read('evaluation/phase3/expected_answers.json')['metrics']


def compare(evidence, expected):
    periods = {r['period']:r for r in expected['periods']}
    for row in evidence.results['overall']:
        reference = periods[['baseline','comparison'][row['period']]]
        assert row['attempts']==reference['attempts']
        assert row['successes']==reference['successes']
        assert abs(row['rate']-reference['successes']/reference['attempts']) <= 1e-10
    reference = expected['bank_method']
    keys = ['payer_bank_id','payment_method']
    rows = evidence.results['segments']
    if 'period' not in reference[0]:
        merged = {}
        for row in rows:
            key = tuple(row[k] for k in keys)
            merged.setdefault(key, {'attempts':0,'successes':0})
            for count in ('attempts','successes'):
                merged[key][count] += row[count]
    else:
        keys = ['period',*keys]
        merged = {tuple((['baseline','comparison'][row[k]] if k=='period' else row[k]) for k in keys):row for row in rows}
    assert set(merged)=={tuple(row[k] for k in keys) for row in reference}
    for row in reference:
        actual = merged[tuple(row[k] for k in keys)]
        assert (actual['attempts'],actual['successes']) == (row['attempts'],row['successes'])


def permission_probes(settings, selected):
    import psycopg
    denied = 0
    with connect(settings) as connection:
        connection.execute('SET default_transaction_read_only=off')
        for scenario in SCENARIOS:
            if scenario == selected:
                continue
            for statement in (f'SELECT * FROM {scenario}.payments LIMIT 1', f'SET search_path={scenario}; SELECT * FROM {scenario}.payments LIMIT 1'):
                try:
                    connection.execute(statement)
                except psycopg.errors.InsufficientPrivilege:
                    denied += 1
                else:
                    raise AssertionError('Cross-schema privilege bypass')
        for statement in (f'DELETE FROM {selected}.payments WHERE false',f'UPDATE {selected}.payments SET status=status WHERE false',f'CREATE TABLE {selected}.analyst_forbidden_probe(x text)'):
            # Always roll back the probe, including a surprising allowed operation.
            connection.execute('BEGIN')
            try:
                try:
                    connection.execute(statement)
                except psycopg.errors.InsufficientPrivilege:
                    denied += 1
                else:
                    raise AssertionError('Write privilege bypass')
            finally:
                connection.execute('ROLLBACK')
    return denied


def continuity_probe(settings):
    admin.select_scenario('scenario_a')
    auth = Authorization(settings)
    try:
        admin.select_scenario('scenario_b')
        admin.select_scenario('scenario_a')
        try:
            auth.check()
        except StaleSession:
            return 'passed'
        raise AssertionError('Old authorization revived after A-B-A')
    finally:
        auth.close()


@contextmanager
def live_api(settings):
    from fastapi.testclient import TestClient
    from app.api.main import create_app
    service_root = ROOT / '.local/analyst/evaluation-service'
    with TestClient(create_app(settings=settings,root=service_root)) as client:
        client.headers['Authorization']='Bearer '+(service_root/'.local/analyst/api_token').read_text()
        yield client


def live_question(client, question):
    response=client.post('/sessions')
    response.raise_for_status()
    sid=response.json()['session_id']
    try:
        response=client.post(f'/sessions/{sid}/investigations',json={'question':question})
        response.raise_for_status()
        iid=response.json()['investigation_id']
        deadline=time.monotonic()+125
        while time.monotonic()<deadline:
            response=client.get(f'/sessions/{sid}/investigations/{iid}')
            response.raise_for_status()
            result=response.json()
            if result['status'] not in ('received','running'):
                return result
            time.sleep(.25)
        raise AssertionError('Live investigation did not stop within its deadline')
    finally:
        client.delete(f'/sessions/{sid}')


def published_evidence(answer, selected, request):
    expected_status = Status.BLOCKED if selected == 'scenario_a_dirty' else Status.VERIFIED
    if (answer.get('status') != expected_status or answer.get('error') is not None
            or not all(isinstance(answer.get(key),dict) for key in ('evidence','narrative','dashboard'))):
        reason = answer.get('error') or 'No published evidence'
        raise AssertionError(f"{selected}: expected {expected_status} with published evidence; got {answer.get('status')}: {reason}")
    evidence = Evidence.model_validate(answer['evidence'])
    assert evidence.scope.scenario == selected
    assert evidence.request == request, 'Model changed the requested metric/window/filter contract'
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-model', action='store_true', help='Run real NVIDIA questions through the API; requires private credentials and provider network access')
    parser.add_argument('--report',type=Path,help='Save this run to a separate report path, preserving earlier acceptance evidence')
    args = parser.parse_args()
    settings = Settings.from_root(ROOT)
    store = EvidenceStore(settings.evidence_dir)
    request = AnalysisRequest(baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'})
    question='Compare attempt success for 2026-10-01 inclusive to 2026-10-15 exclusive versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. Explain bank/method contributions and observed failure labels.'
    report = {'run_id':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'status':'running','mode':'live_model_api_sql' if args.live_model else 'deterministic_real_sql','scenarios':[],
              'provider':'nvidia' if args.live_model else None,'model':settings.model if args.live_model else None,
              'gates':{'foundation':'passed','complete_demo':'pending','first_analyst_breadth':'pending','target_v1':'pending'},
              'missing_evidence':['real model/API/UI journey','live model adversarial and safe-failure benchmarks','browser rendering proof']}
    report['protected_sources_before'] = check_sources()
    try:
        for selected in SCENARIOS:
            started = time.monotonic()
            admin.select_scenario(selected)
            auth = Authorization(settings)
            try:
                budget = Budget()
                if args.live_model:
                    with live_api(settings) as client:
                        answer=live_question(client,question)
                    report['last_investigation']={'schema':selected, **{key:answer.get(key) for key in
                        ('investigation_id','status','error','budget')}}
                    evidence=published_evidence(answer,selected,request)
                    statement_count=answer['budget']['sql_statements']
                else:
                    raw = analyze(settings,auth,Scope(scenario=selected,session_id='evaluation-'+report['run_id']),request,budget)
                    evidence = store.put(raw,'comparison')
                    statement_count=budget.statements
                verify_evidence(evidence)
                output = (publication_narrative(evidence, read_layout(answer['dashboard'], evidence))
                          if args.live_model else narrative(evidence))
                if selected == 'scenario_a_dirty':
                    defects = {q.rule:q.count for q in evidence.quality}
                    manifest = read('evaluation/phase1/defect_manifest.json')
                    assert defects['duplicate_occurrences']==manifest['additional_duplicate_occurrences']==20
                    assert defects['missing_timestamps']==10 and defects['orphan_merchants']==10
                    assert not evidence.results and 'blocked' in output['answer']
                else:
                    compare(evidence,oracle(selected))
                    assert all(q.status=='PASS' for q in evidence.quality)
                    if selected=='scenario_a':
                        worst=min(evidence.results['decomposition']['joint']['parts'],key=lambda p:p['within'])
                        assert (worst['payer_bank_id'],worst['payment_method'])==('BANK_B','UPI')
                    if selected=='scenario_b':
                        assert abs(evidence.results['decomposition']['method']['within']) < 1e-10
                        assert abs(evidence.results['decomposition']['method']['mix']+0.048) < 1e-10
                if args.live_model:
                    assert answer['narrative']==output
                report['scenarios'].append({'schema':selected,'status':'passed','evidence_id':evidence.id,'checksum':evidence.checksum,'statement_count':statement_count,
                                            'denial_probes':permission_probes(settings,selected),'elapsed_seconds':time.monotonic()-started,
                                            'question':question,
                                            'narrative':output})
                print(selected+': passed',flush=True)
            finally:
                auth.close()
        report['selection_continuity_A_B_A'] = continuity_probe(settings)
        if args.live_model:
            admin.select_scenario('lifecycle_v1')
            report['policy_cases']=[]
            with live_api(settings) as client:
                for case in read('evaluation/analyst/benchmark_questions.json')['policy_cases']:
                    result=live_question(client,case['question'])
                    assert result['status'] in case['allowed_statuses']
                    assert result['evidence'] is None
                    assert result['budget']['sql_statements']==0
                    report['policy_cases'].append({'id':case['id'],'status':'passed','observed_status':result['status']})
            report['missing_evidence']=['same-version real browser/model/API/SQL validation and final acceptance review']
        report['status']='passed'
    except Exception as exc:
        report['status']='failed'
        report['failure_type']=type(exc).__name__
        raise
    finally:
        admin.select_scenario('lifecycle_v1')
        auth = Authorization(settings)
        try:
            assert auth.scenario=='lifecycle_v1'
            report['restored_selection']={'schema':auth.scenario,'visible_tables':8}
        finally:
            auth.close()
        report['protected_sources_after']=check_sources()
        name='live_acceptance.json' if args.live_model else 'deterministic_acceptance.json'
        destination=args.report or ROOT/'reports/analyst'/name
        destination.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
