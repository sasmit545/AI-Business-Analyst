"""Validate lifecycle CSVs and independent SQL answers without importing the generator."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

from lifecycle_schema import FIELDS, data_dir
from validate_phase1 import save_json, sha256
from validate_phase2 import queries

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'profiles/lifecycle_v1.json'
EVALUATION = ROOT / 'evaluation/phase3'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def parameters(config):
    return {'window_start': config['start_date']+'T00:00:00.000'+config['timezone'],
            'window_end': (datetime.fromisoformat(config['end_date'])+timedelta(days=1)).strftime('%Y-%m-%d')+'T00:00:00.000'+config['timezone'],
            'cutoff': config['observation_cutoff']}


def load_tables(folder):
    tables = {}
    for name, fields in FIELDS.items():
        with (folder / f'{name}.csv').open(newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            if tuple(reader.fieldnames or ()) != fields:
                raise ValueError(f'{name}: unexpected CSV fields')
            tables[name] = list(reader)
    return tables


def sql_answers(tables, params):
    with closing(sqlite3.connect(':memory:')) as db:
        db.row_factory = sqlite3.Row
        for name, fields in FIELDS.items():
            db.execute(f'CREATE TABLE {name} ({", ".join(field+" TEXT" for field in fields)})')
            db.executemany(f'INSERT INTO {name} VALUES ({",".join("?" for _ in fields)})',
                           ([row[field] for field in fields] for row in tables[name]))
        for name, cols in {'orders': 'order_id', 'payments': 'order_id', 'settlements': 'attempt_id',
                           'merchants': 'merchant_id', 'banks': 'bank_id', 'payment_methods': 'payment_method',
                           'failure_reasons': 'failure_reason', 'bank_health': 'bank_id,payment_method,observed_at'}.items():
            db.execute(f'CREATE INDEX {name}_lookup ON {name} ({cols})')
        return {name: [dict(row) for row in db.execute(sql, params)] for name, sql in queries(EVALUATION/'reference.sql').items()}


def check_quality(tables, config):
    issues = Counter()
    cutoff = datetime.fromisoformat(config['observation_cutoff'])
    start = datetime.fromisoformat(config['start_date']+'T00:00:00'+config['timezone'])
    end = datetime.fromisoformat(config['end_date']+'T00:00:00'+config['timezone'])+timedelta(days=1)
    def require(condition, label):
        if not condition:
            issues[label] += 1
    def timestamp(text):
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+05:30', text):
            raise ValueError('noncanonical timestamp')
        return datetime.fromisoformat(text)
    keys = {'merchants': ('merchant_id',), 'banks': ('bank_id',), 'payment_methods': ('payment_method',),
            'failure_reasons': ('failure_reason',), 'orders': ('order_id',), 'payments': ('attempt_id',),
            'settlements': ('settlement_id',), 'bank_health': ('bank_id','payment_method','observed_at')}
    for table, rows in tables.items():
        seen = set()
        for row in rows:
            require(set(row) == set(FIELDS[table]) and all(value is not None for value in row.values()), table+': columns')
            key = tuple(row[f] for f in keys[table])
            require(key not in seen, table+': duplicate key')
            seen.add(key)
    merchants = {row['merchant_id'] for row in tables['merchants']}
    banks = {row['bank_id'] for row in tables['banks']}
    methods = {row['payment_method'] for row in tables['payment_methods']}
    reasons = {row['failure_reason'] for row in tables['failure_reasons']}
    require(methods == {'CARD','UPI'}, 'method reference values')
    require({r['failure_reason']: r['category'] for r in tables['failure_reasons']} == {
        'BANK_TIMEOUT':'technical','AUTHENTICATION_FAILED':'authentication',
        'INSUFFICIENT_FUNDS':'customer','LIMIT_EXCEEDED':'customer'}, 'failure reference values')
    orders = {row['order_id']: row for row in tables['orders']}
    payments = {row['attempt_id']: row for row in tables['payments']}
    chains = defaultdict(list)
    for order in tables['orders']:
        try:
            require(bool(re.fullmatch(r'O\d{9}', order['order_id'])), 'order ID')
            require(order['merchant_id'] in merchants, 'order merchant FK')
            require(order['currency']=='INR' and order['amount_paise'].isdigit() and 1000 <= int(order['amount_paise']) <= 10000000, 'order amount/currency')
            require(start <= timestamp(order['created_at']) < end, 'order timestamp window')
        except (ValueError, TypeError):
            issues['invalid order value'] += 1
    for row in tables['payments']:
        try:
            require(bool(re.fullmatch(r'L\d{9}',row['attempt_id'])), 'attempt ID')
            require(row['payer_bank_id'] in banks and row['payment_method'] in methods, 'payment reference FK')
            order = orders.get(row['order_id'])
            require(order is not None, 'payment order FK')
            if order is None:
                continue
            chains[row['order_id']].append(row)
            require(all(row[k]==order[k] for k in ('merchant_id','amount_paise','currency')), 'attempt order attributes')
            attempted, completed, ingested = [timestamp(row[k]) for k in ('attempted_at','completed_at','ingested_at')]
            require(timestamp(order['created_at']) < attempted < completed <= ingested <= cutoff, 'attempt chronology')
            require(row['processing_duration_ms'].isdigit() and int(row['processing_duration_ms']) > 0
                    and completed-attempted == timedelta(milliseconds=int(row['processing_duration_ms'])), 'attempt duration')
            require(row['attempt_number'] in ('1','2','3'), 'attempt number')
            require((row['status']=='SUCCESS' and row['failure_reason']=='') or
                    (row['status']=='FAILED' and row['failure_reason'] in reasons), 'attempt outcome')
        except (ValueError, TypeError):
            issues['invalid attempt value'] += 1
    for order_id, order in orders.items():
        try:
            chain = sorted(chains[order_id], key=lambda r: int(r['attempt_number']))
            require(1 <= len(chain) <= 3, 'chain length')
            require([r['attempt_number'] for r in chain] == [str(i+1) for i in range(len(chain))], 'consecutive attempts')
            require(sum(r['status']=='SUCCESS' for r in chain) <= 1, 'multiple successes')
            require(len({(r['payment_method'],r['payer_bank_id']) for r in chain}) == 1, 'retry instrument changed')
            if chain:
                require(timestamp(chain[0]['attempted_at'])-timestamp(order['created_at']) == timedelta(seconds=config['initial_delay_seconds']), 'initial attempt delay')
            for previous, current in zip(chain, chain[1:]):
                require(previous['status']=='FAILED', 'retry after success')
                require(timestamp(current['attempted_at'])-timestamp(previous['completed_at']) == timedelta(minutes=5), 'retry delay')
        except (ValueError, TypeError):
            issues['invalid chain value'] += 1
    settled_attempts = set()
    for row in tables['settlements']:
        try:
            payment = payments.get(row['attempt_id'])
            require(payment is not None, 'settlement attempt FK')
            require(row['attempt_id'] not in settled_attempts, 'duplicate settlement attempt')
            require(bool(re.fullmatch(r'S\d{9}',row['settlement_id'])), 'settlement ID')
            settled_attempts.add(row['attempt_id'])
            if payment is None:
                continue
            require(payment['status']=='SUCCESS', 'settlement on failure')
            require(row['gross_amount_paise']==payment['amount_paise'], 'settlement full gross amount')
            due = timestamp(row['due_at'])
            require(due-timestamp(payment['completed_at']) == timedelta(hours=24), 'settlement due time')
            require((due <= cutoff and row['settlement_status']=='SETTLED' and row['settled_at']==row['due_at']) or
                    (due > cutoff and row['settlement_status']=='PENDING' and row['settled_at']==''), 'baseline settlement state')
        except (ValueError, TypeError):
            issues['invalid settlement value'] += 1
    require(settled_attempts == {r['attempt_id'] for r in tables['payments'] if r['status']=='SUCCESS'}, 'successful attempt settlement coverage')
    buckets = set()
    for row in tables['bank_health']:
        try:
            observed = timestamp(row['observed_at'])
            require(row['bank_id'] in banks and row['payment_method'] in methods, 'health reference FK')
            require(start <= observed < cutoff and observed.minute%5==0 and observed.second==0 and observed.microsecond==0, 'health bucket alignment')
            require(0 <= float(row['availability_pct']) <= 100 and int(row['p95_latency_ms']) > 0, 'health values')
            buckets.add((row['bank_id'],row['payment_method'],row['observed_at']))
        except (ValueError, TypeError):
            issues['invalid health value'] += 1
    for row in tables['payments']:
        try:
            at = timestamp(row['attempted_at'])
            bucket = at.replace(minute=at.minute//5*5, second=0, microsecond=0).isoformat(timespec='milliseconds')
            require((row['payer_bank_id'],row['payment_method'],bucket) in buckets, 'unmatched bank health')
        except (ValueError, TypeError):
            pass
    return dict(issues)


def prior_sources_unchanged():
    snapshot = read_json(ROOT/'reports/phase3_preexisting_source_snapshot.json')
    return all((ROOT/path).is_file() and sha256(ROOT/path)==digest for path,digest in snapshot.items())


def validate(root=ROOT, write_expected=False, check_reproducibility=False, write_report=True):
    config = read_json(CONFIG)
    tables = load_tables(data_dir(root))
    errors = []
    quality = check_quality(tables, config)
    if quality:
        errors.append(f'Lifecycle integrity failures: {quality}')
    manifest = read_json(root/'evaluation/phase3/generation_manifest.json')
    payload = json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    if manifest['configuration'] != config or manifest['configuration_sha256'] != hashlib.sha256(payload).hexdigest():
        errors.append('Configuration differs from generation manifest')
    expected_paths = {(data_dir(root)/f'{name}.csv').relative_to(root).as_posix() for name in FIELDS}
    if set(manifest['files']) != expected_paths:
        errors.append('Manifest does not cover exactly the eight CSVs')
    for path, entry in manifest['files'].items():
        if path not in expected_paths:
            continue
        if sha256(root/path) != entry['sha256'] or len(tables[Path(path).stem]) != entry['rows']:
            errors.append(f'Manifest mismatch: {path}')
    if len(tables['orders']) != config['orders'] or manifest['actual_orders'] != len(tables['orders']) or manifest['actual_attempts'] != len(tables['payments']):
        errors.append('Order/attempt count mismatch')
    expected_health = int((datetime.fromisoformat(config['observation_cutoff'])-datetime.fromisoformat(parameters(config)['window_start'])).total_seconds()/300)*10
    if len(tables['bank_health']) != expected_health:
        errors.append('Incomplete five-minute bank-health grid')
    for name in ('merchants','banks'):
        with (ROOT/f'data/synthetic/phase1/scenario_a/{name}.csv').open(newline='',encoding='utf-8') as file:
            if tables[name] != list(csv.DictReader(file)):
                errors.append(f'{name}: original dimension attributes changed')
    prior_ok = prior_sources_unchanged()
    if not prior_ok:
        errors.append('Earlier-phase data or ground truths changed')
    answers = {'schema_version':'1.0.0', 'parameters':parameters(config),
               'reference_sql_sha256':sha256(EVALUATION/'reference.sql'),
               'metrics':sql_answers(tables, parameters(config))}
    fixture = read_json(EVALUATION/'hand_fixture.json')
    hand = sql_answers(fixture['tables'], fixture['parameters'])
    answers['hand_fixture'] = hand
    answers['hand_fixture_sha256'] = sha256(EVALUATION/'hand_fixture.json')
    for section, fields in fixture['expected_checks'].items():
        for field, value in fields.items():
            if hand[section][0][field] != value:
                errors.append(f'Hand fixture mismatch: {section}.{field}')
    for key in ('joins','temporal_join'):
        metrics = answers['metrics'][key][0]
        n = answers['metrics']['attempts'][0]['attempts']
        if metrics['joined_rows'] != n or metrics['distinct_attempts'] != n or metrics.get('unmatched_attempts',0):
            errors.append(f'{key}: joins lose or multiply attempts')
    path = root/'evaluation/phase3/expected_answers.json'
    if write_expected and not errors:
        save_json(path, answers)
    elif not path.exists() or read_json(path) != answers:
        errors.append('Independent SQL differs from saved expected answers')
    repro = {'checked':False}
    if check_reproducibility:
        paths = sorted(expected_paths | {'evaluation/phase3/generation_manifest.json'})
        runs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as folder:
                subprocess.run([sys.executable,'-B',str(ROOT/'scripts/generate_phase3.py'),'--output-root',folder],check=True,capture_output=True)
                runs.append({path:sha256(Path(folder)/path) for path in paths})
        repro = {'checked':True,'runs':2,'identical':runs[0]==runs[1]=={path:sha256(root/path) for path in paths}}
        if not repro['identical']:
            errors.append('Reproducibility mismatch')
    report = {'dataset_gate':'failed' if errors else 'passed','analyst_gate':'pending','errors':errors,
              'quality':quality,'row_counts':{name:len(rows) for name,rows in tables.items()},
              'prior_phase_sources_unchanged':prior_ok,'reproducibility':repro,'metrics':answers['metrics']}
    if write_report:
        save_json(root/'evaluation/phase3/validation_report.json',report)
    return report, answers


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-expected',action='store_true')
    parser.add_argument('--check-reproducibility',action='store_true')
    args = parser.parse_args()
    report, _ = validate(write_expected=args.write_expected,check_reproducibility=args.check_reproducibility)
    print(json.dumps({k:report[k] for k in ('dataset_gate','errors','row_counts','reproducibility')},indent=2))
    sys.exit(report['dataset_gate']!='passed')
