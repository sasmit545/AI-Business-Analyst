"""Independently evaluate Phase 2 CSVs with SQLite; no generator imports or constants."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

import validate_phase1 as source

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / 'evaluation/phase2'
CONFIG = ROOT / 'profiles/realistic_v1.json'
VARIANTS = ('baseline', 'incident')


def data_dir(root):
    return root / 'data/synthetic/phase2/realistic_v1'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def queries(path):
    parts = re.split(r'^-- query: (\w+)\s*$', path.read_text(encoding='utf-8'), flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip().rstrip(';') for i in range(1, len(parts), 2)}


def sql_answers(table_rows, query_map):
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.row_factory = sqlite3.Row
        for table, rows in table_rows.items():
            fields = source.SCHEMAS['payments'] if table.endswith('_payments') else source.SCHEMAS[table]
            connection.execute(f'CREATE TABLE {table} ({", ".join(field + " TEXT" for field in fields)})')
            connection.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" for _ in fields)})',
                                   ([row[field] for field in fields] for row in rows))
        return {name: [dict(row) for row in connection.execute(sql)] for name, sql in query_map.items()}


def apportioned(total, weights):
    """Independent specification calculation, never imported from generation code."""
    items = sorted((key, Fraction(str(value))) for key, value in weights.items())
    total_weight = sum(value for _, value in items)
    quotas = [(key, total * weight / total_weight) for key, weight in items]
    result = {key: quota.numerator // quota.denominator for key, quota in quotas}
    fractions = sorted(quotas, key=lambda item: (-(item[1] % 1), item[0]))
    for key, _ in fractions[:total - sum(result.values())]:
        result[key] += 1
    return result


def check_quality(tables, config):
    issues = Counter()
    payments, merchants, banks = (tables[name] for name in ('payments', 'merchants', 'banks'))
    merchant_ids = {row['merchant_id'] for row in merchants}
    bank_ids = {row['bank_id'] for row in banks}
    issues['duplicate_ids'] = len(payments) - len({row['attempt_id'] for row in payments})
    issues['wrong_row_count'] = int(len(payments) != config['attempts'])
    issues['dimension_cardinality'] = int(len(merchants) != 20 or len(banks) != 5 or len(merchant_ids) != 20 or len(bank_ids) != 5)
    for table in ('merchants', 'banks'):
        original = source.load_tables(ROOT / 'data/synthetic/phase1/scenario_a')[table]
        issues['changed_dimensions'] += int(tables[table] != original)
    for row in payments:
        issues['invalid_identifiers'] += int(not re.fullmatch(r'R[0-9]{8}', row['attempt_id']))
        issues['orphan_merchants'] += int(row['merchant_id'] not in merchant_ids)
        issues['orphan_banks'] += int(row['payer_bank_id'] not in bank_ids)
        issues['invalid_methods'] += int(row['payment_method'] not in ('CARD', 'UPI'))
        issues['invalid_currency'] += int(row['currency'] != 'INR')
        amount = row['amount_paise']
        issues['invalid_amounts'] += int(not re.fullmatch(r'[1-9][0-9]*', amount) or not 1000 <= int(amount) <= 10000000)
        issues['invalid_outcomes'] += int(not ((row['status'] == 'SUCCESS' and row['failure_reason'] == '') or
            (row['status'] == 'FAILED' and row['failure_reason'] in source.VALID_REASONS)))
        try:
            stamp = row['attempted_at']
            if not re.fullmatch(r'2026-10-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+05:30', stamp):
                raise ValueError('format')
            parsed = datetime.fromisoformat(stamp)
            if not date.fromisoformat(config['start_date']) <= parsed.date() <= date.fromisoformat(config['end_date']):
                raise ValueError('range')
        except ValueError:
            issues['invalid_timestamps'] += 1
    return dict(issues)


def check_allocations(tables, metrics, config):
    errors = []
    total = config['attempts']
    expected_merchants = apportioned(total, config['merchant_weights'])
    observed_merchants = {row['merchant_id']: row['attempts'] for row in metrics['merchants']}
    if observed_merchants != expected_merchants:
        errors.append('merchant allocation differs from largest remainder specification')
    if {row['payer_bank_id']: row['attempts'] for row in metrics['banks']} != apportioned(total, config['bank_weights']):
        errors.append('bank allocation differs from global largest remainder specification')
    methods = {(r['merchant_id'], r['payment_method']): r['attempts'] for r in metrics['merchant_methods']}
    traffic = config['traffic']
    observed_slots = Counter((r['merchant_id'], r['attempted_at'][:13]) for r in tables['payments'])
    expected_slots = {}
    for merchant in tables['merchants']:
        key, category = merchant['merchant_id'], merchant['category']
        upi = Fraction(str(config['upi_share_by_category'][category]))
        expected_methods = apportioned(expected_merchants[key], {'CARD': 1 - upi, 'UPI': upi})
        if any(methods.get((key, method)) != count for method, count in expected_methods.items()):
            errors.append(f'method allocation incorrect for {key}')
        weights = {}
        for offset in range(28):
            day = date(2026, 10, 1) + timedelta(days=offset)
            day_weight = Fraction(str(traffic['weekend_weights'][category])) if day.weekday() in (5, 6) else Fraction(1)
            for hour in range(24):
                hour_weight = traffic['default_hour_weight']
                if hour in traffic['night_hours']:
                    hour_weight = traffic['night_hour_weight']
                if category == 'dining' and hour in traffic['dining_peak_hours']:
                    hour_weight = traffic['dining_peak_weight']
                weights[f'{day.isoformat()}T{hour:02}'] = day_weight * Fraction(str(hour_weight))
        expected_slots.update({(key, slot): count for slot, count in apportioned(expected_merchants[key], weights).items() if count})
    if dict(observed_slots) != expected_slots:
        errors.append('joint date/hour allocations differ from configured exposure weights')
    if metrics['joins'] != [{'payment_count': total, 'merchant_join_count': total,
                             'bank_join_count': total, 'combined_join_count': total}]:
        errors.append('joins do not preserve payment counts')
    if min(observed_merchants.get(f'M{i:02}', 0) for i in range(1, 5)) <= max(observed_merchants.get(f'M{i:02}', 0) for i in range(11, 21)):
        errors.append('high-volume merchant pattern missing')
    dining = {r['local_hour']: r['attempts'] for r in metrics['hourly'] if r['category'] == 'dining'}
    peak = traffic['dining_peak_hours']
    normal = [hour for hour in range(24) if hour not in peak and hour not in traffic['night_hours']]
    if sum(dining.get(h, 0) for h in peak) / len(peak) <= sum(dining.get(h, 0) for h in normal) / len(normal):
        errors.append('dining peak pattern missing')
    return errors


def reliability_diagnostics(metrics, config):
    result = []

    def add(population, successes, n, probability):
        standard_error = math.sqrt(probability * (1 - probability) / n)
        z = (successes / n - probability) / standard_error
        result.append({'population': population, 'numerator': successes, 'denominator': n,
                       'target_probability': probability, 'observed_probability': round(successes / n, 9),
                       'standard_error': round(standard_error, 9), 'standard_errors_from_target': round(z, 6),
                       'flagged': abs(z) > config['diagnostics']['standard_errors']})
    for row in metrics['bank_method']:
        add(row['payer_bank_id'] + '/' + row['payment_method'], row['successes'], row['attempts'],
            config['success_probability'][row['payment_method']][row['payer_bank_id']])
    for method in ('CARD', 'UPI'):
        counts = {r['failure_reason']: r['failures'] for r in metrics['failure_reasons'] if r['payment_method'] == method}
        n = sum(counts.values())
        if n:
            weights = config['failure_weights'][method]
            for reason, weight in weights.items():
                add(method + '/failures/' + reason, counts.get(reason, 0), n, weight / sum(weights.values()))
    return result


def check_pair(tables, paired, incident_manifest, config):
    errors = []
    baseline_ids = {r['attempt_id'] for r in tables['baseline']['payments']}
    incident_ids = {r['attempt_id'] for r in tables['incident']['payments']}
    if baseline_ids != incident_ids or paired['summary'][0]['matched_attempts'] != config['attempts']:
        errors.append('paired variants do not preserve one-to-one attempt IDs')
    if paired['summary'][0]['changed_non_outcome_rows']:
        errors.append('incident modified non-outcome fields')
    eligible = [r['attempt_id'] for r in paired['eligible']]
    n = int(Fraction(str(config['incident']['fraction'])) * len(eligible) + Fraction(1, 2))
    ranked = sorted(eligible, key=lambda value: (hashlib.sha256(
        f'phase2:incident:v1:{config["seed"]}:{value}'.encode()).hexdigest(), value))
    expected_ids = sorted(ranked[:n])
    changed_ids = [r['attempt_id'] for r in paired['changed']]
    if changed_ids != expected_ids or incident_manifest['selected_attempt_ids'] != expected_ids:
        errors.append('incident selection differs from independent SQL eligibility and stable ID ranking')
    if incident_manifest['eligible_successes'] != len(eligible) or incident_manifest['converted_successes'] != n:
        errors.append('incident manifest counts differ from actual paired records')
    for row in paired['changed']:
        if (row['payer_bank_id'], row['payment_method'], row['original_status'], row['incident_status'],
                row['original_reason'], row['incident_reason']) != ('BANK_B', 'UPI', 'SUCCESS', 'FAILED', '', 'BANK_TIMEOUT'):
            errors.append('incident changed an ineligible outcome/reason')
            break
        if not '2026-10-15' <= row['local_date'] <= '2026-10-21':
            errors.append('incident changed an attempt outside its window')
            break
    if paired['summary'][0]['converted_successes'] != n or paired['summary'][0]['changed_outcome_rows'] != n:
        errors.append('wrong total incident outcome changes')
    if any(tables['baseline'][t] != tables['incident'][t] for t in ('merchants', 'banks')):
        errors.append('incident changed dimensions')
    return errors


def reproducibility(root):
    with tempfile.TemporaryDirectory() as folder:
        roots = [Path(folder) / 'run1', Path(folder) / 'run2']
        for target in roots:
            subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/generate_phase2.py'), '--output-root', str(target)],
                           check=True, capture_output=True, text=True)
        names = list(read_json(root / 'evaluation/phase2/generation_manifest.json')['files'])
        names += ['evaluation/phase2/generation_manifest.json', 'evaluation/phase2/incident_manifest.json']
        hashes = {name: {'delivered': source.sha256(root / name), 'run1': source.sha256(roots[0] / name),
                         'run2': source.sha256(roots[1] / name)} for name in sorted(names)}
        return {'status': 'checked', 'identical': all(len(set(h.values())) == 1 for h in hashes.values()), 'files': hashes}


def validate(root=ROOT, write_expected=False, check_reproducibility=False, write_report=True):
    report = {'dataset_gate': 'failed', 'analyst_gate': 'pending', 'errors': [], 'variants': {},
              'diagnostics': [], 'reproducibility': {'status': 'not_run'}}
    answers = {}
    try:
        config = read_json(CONFIG)
        manifest = read_json(root / 'evaluation/phase2/generation_manifest.json')
        if manifest['configuration'] != config:
            report['errors'].append('recorded profile differs from versioned realistic_v1 configuration')
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if manifest['configuration_sha256'] != config_hash:
            report['errors'].append('configuration hash mismatch')
        protected = read_json(ROOT / 'reports/postgres_phase1_source_snapshot.json')
        report['phase1_files_unchanged'] = all(source.sha256(ROOT / name) == checksum for name, checksum in protected.items())
        if not report['phase1_files_unchanged']:
            report['errors'].append('protected Phase 1 files changed')
        expected_files = {f'data/synthetic/phase2/realistic_v1/{variant}/{table}.csv' for variant in VARIANTS for table in source.SCHEMAS}
        if set(manifest['files']) != expected_files:
            report['errors'].append('generation manifest must contain exactly the six Phase 2 CSVs')
        for name in expected_files:
            if source.sha256(root / name) != manifest['files'][name]['sha256']:
                report['errors'].append(f'CSV content hash mismatch: {name}')
        if source.sha256(root / 'evaluation/phase2/incident_manifest.json') != manifest['incident_manifest_sha256']:
            report['errors'].append('incident manifest hash mismatch')
        answers = {'profile_id': 'realistic_v1', 'configuration_sha256': config_hash,
                   'reference_sql_sha256': source.sha256(EVALUATION / 'reference.sql'),
                   'paired_reference_sql_sha256': source.sha256(EVALUATION / 'paired_reference.sql'), 'variants': {}}
        tables = {variant: source.load_tables(data_dir(root) / variant) for variant in VARIANTS}
        for variant in VARIANTS:
            quality = check_quality(tables[variant], config)
            report['variants'][variant] = {'quality': quality}
            for table, records in tables[variant].items():
                name = f'data/synthetic/phase2/realistic_v1/{variant}/{table}.csv'
                if manifest['files'][name]['rows'] != len(records):
                    report['errors'].append(f'manifest row count mismatch: {name}')
            if any(quality.values()):
                report['errors'].append(f'{variant}: invalid data; analysis blocked')
                continue
            metrics = sql_answers(tables[variant], queries(EVALUATION / 'reference.sql'))
            report['errors'].extend(f'{variant}: {error}' for error in check_allocations(tables[variant], metrics, config))
            answers['variants'][variant] = metrics
            report['variants'][variant]['totals'] = metrics['totals']
            report['variants'][variant]['periods'] = metrics['periods']
        if len(answers['variants']) == 2:
            paired = sql_answers({'baseline_payments': tables['baseline']['payments'],
                                  'incident_payments': tables['incident']['payments']}, queries(EVALUATION / 'paired_reference.sql'))
            report['errors'].extend(check_pair(tables, paired, read_json(root / 'evaluation/phase2/incident_manifest.json'), config))
            answers['paired'] = paired
            report['paired_summary'] = paired['summary']
            report['diagnostics'] = reliability_diagnostics(answers['variants']['baseline'], config)
            report['diagnostic_flags'] = sum(r['flagged'] for r in report['diagnostics'])
            report['diagnostic_policy'] = 'Baseline only. Four standard errors; flags are reported, not resampled. Incident deviations are intentional.'
        if check_reproducibility:
            report['reproducibility'] = reproducibility(root)
            if not report['reproducibility']['identical']:
                report['errors'].append('same-configuration regeneration differs')
        expected_path = root / 'evaluation/phase2/expected_answers.json'
        if write_expected:
            if not report['errors']:
                source.save_json(expected_path, answers)
        elif not expected_path.is_file() or read_json(expected_path) != answers:
            report['errors'].append('actual independent SQL results differ from saved expected answers (or answers are missing)')
        if not report['errors']:
            report['dataset_gate'] = 'passed'
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.CalledProcessError) as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    if write_report:
        source.save_json(root / 'evaluation/phase2/validation_report.json', report)
    return report, answers


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--write-expected', action='store_true')
    parser.add_argument('--check-reproducibility', action='store_true')
    args = parser.parse_args()
    result, _ = validate(args.root.resolve(), args.write_expected, args.check_reproducibility)
    print(json.dumps({'dataset_gate': result['dataset_gate'], 'errors': result['errors'],
                      'diagnostic_flags': result.get('diagnostic_flags'),
                      'report': str(args.root / 'evaluation/phase2/validation_report.json')}, indent=2))
    sys.exit(result['dataset_gate'] != 'passed')
