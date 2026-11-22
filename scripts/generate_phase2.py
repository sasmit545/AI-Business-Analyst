"""Generate the versioned Phase 2 baseline and paired incident using existing dimensions."""
import argparse
import csv
from datetime import date, timedelta
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random

from validate_phase1 import SCHEMAS, save_json, sha256

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'profiles/realistic_v1.json'
VERSION = '1.0.0'


def allocate(total, weights):
    """Hamilton allocation with exact fractions and ascending identifier tie breaks."""
    weights = {key: Fraction(str(value)) for key, value in weights.items()}
    denominator = sum(weights.values())
    quotas = {key: total * weight / denominator for key, weight in weights.items()}
    counts = {key: int(quotas[key]) for key in sorted(weights)}
    remainder_order = sorted(weights, key=lambda key: (-(quotas[key] - counts[key]), key))
    for key in remainder_order[:total - sum(counts.values())]:
        counts[key] += 1
    return counts


def stream(seed, name):
    digest = hashlib.sha256(f'phase2:streams:v1:{seed}:{name}'.encode()).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def read_dimensions():
    result = {}
    for table in ('merchants', 'banks'):
        with (ROOT / f'data/synthetic/phase1/scenario_a/{table}.csv').open(newline='', encoding='utf-8') as file:
            result[table] = list(csv.DictReader(file))
    return result


def date_hour_weights(config, category):
    start, end = date.fromisoformat(config['start_date']), date.fromisoformat(config['end_date'])
    traffic = config['traffic']
    result = {}
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        weekend = traffic['weekend_weights'][category] if day.weekday() >= 5 else 1
        for hour in range(24):
            hourly = traffic['night_hour_weight'] if hour in traffic['night_hours'] else traffic['default_hour_weight']
            if category == 'dining' and hour in traffic['dining_peak_hours']:
                hourly = traffic['dining_peak_weight']
            result[f'{day.isoformat()}T{hour:02}'] = Fraction(str(weekend)) * Fraction(str(hourly))
    return result


def generate(root, config):
    if config['profile_id'] != 'realistic_v1' or config['attempts'] not in (100000, 200000):
        raise ValueError('This Phase 2 implementation accepts realistic_v1 at 100,000 or 200,000 attempts')
    dimensions = read_dimensions()
    seed, total = config['seed'], config['attempts']
    bank_counts = allocate(total, config['bank_weights'])
    bank_pool = [bank for bank, count in bank_counts.items() for _ in range(count)]
    stream(seed, 'traffic.banks').shuffle(bank_pool)
    merchant_counts = allocate(total, config['merchant_weights'])
    times = stream(seed, 'traffic.time')
    outcomes = stream(seed, 'outcomes.status')
    reasons = stream(seed, 'outcomes.reasons')
    amounts = {category: stream(seed, f'amounts.{category}') for category in config['amounts']['median_inr']}
    rows = []
    for merchant in dimensions['merchants']:
        merchant_id, category = merchant['merchant_id'], merchant['category']
        upi = Fraction(str(config['upi_share_by_category'][category]))
        methods = allocate(merchant_counts[merchant_id], {'CARD': 1 - upi, 'UPI': upi})
        method_pool = [method for method, count in methods.items() for _ in range(count)]
        stream(seed, f'traffic.methods.{merchant_id}').shuffle(method_pool)
        slots = allocate(merchant_counts[merchant_id], date_hour_weights(config, category))
        merchant_index = 0
        for slot, count in slots.items():
            for _ in range(count):
                index = len(rows)
                bank, method = bank_pool[index], method_pool[merchant_index]
                merchant_index += 1
                seconds = times.randrange(3600)
                timestamp = f'{slot}:{seconds // 60:02}:{seconds % 60:02}{config["timezone"]}'
                specification = config['amounts']
                value = amounts[category].lognormvariate(math.log(specification['median_inr'][category]), specification['sigma'])
                amount = round(100 * min(specification['max_inr'], max(specification['min_inr'], value)))
                success = outcomes.random() < config['success_probability'][method][bank]
                weights = config['failure_weights'][method]
                failure = '' if success else reasons.choices(list(weights), weights=list(weights.values()), k=1)[0]
                rows.append(dict(zip(SCHEMAS['payments'], [f'R{index + 1:08}', timestamp,
                    merchant_id, bank, method, str(amount), config['currency'],
                    'SUCCESS' if success else 'FAILED', failure])))
    incident = config['incident']
    eligible = [row['attempt_id'] for row in rows
                if row['payer_bank_id'] == incident['payer_bank_id'] and row['payment_method'] == incident['payment_method']
                and row['status'] == incident['eligible_status']
                and incident['start_date'] <= row['attempted_at'][:10] <= incident['end_date']]
    fraction = Fraction(str(incident['fraction']))
    selected_count = int(len(eligible) * fraction + Fraction(1, 2))
    rank = lambda attempt: (hashlib.sha256(f'phase2:incident:v1:{seed}:{attempt}'.encode()).hexdigest(), attempt)
    selected = set(sorted(eligible, key=rank)[:selected_count])
    changed = [dict(row, status=incident['replacement_status'], failure_reason=incident['replacement_failure_reason'])
               if row['attempt_id'] in selected else row.copy() for row in rows]
    manifest_files = {}
    for variant, payments in (('baseline', rows), ('incident', changed)):
        folder = root / f'data/synthetic/phase2/realistic_v1/{variant}'
        folder.mkdir(parents=True, exist_ok=True)
        for table, records in (('payments', payments), *dimensions.items()):
            path = folder / f'{table}.csv'
            with path.open('w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, SCHEMAS[table], lineterminator='\n')
                writer.writeheader()
                writer.writerows(records)
            manifest_files[path.relative_to(root).as_posix()] = {'rows': len(records), 'sha256': sha256(path)}
    evaluation = root / 'evaluation/phase2'
    incident_path = evaluation / 'incident_manifest.json'
    save_json(incident_path, {'profile_id': config['profile_id'], 'eligible_successes': len(eligible),
                              'converted_successes': selected_count, 'selected_attempt_ids': sorted(selected),
                              'intervention': incident, 'causal_scope': 'generator-known counterfactual; not proof of a real outage'})
    config_payload = json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    save_json(evaluation / 'generation_manifest.json', {
        'profile_id': config['profile_id'], 'schema_version': config['schema_version'], 'generator_version': VERSION,
        'seed': seed, 'configuration': config, 'configuration_sha256': hashlib.sha256(config_payload).hexdigest(),
        'files': manifest_files, 'incident_manifest_sha256': sha256(incident_path),
        'encoding': 'UTF-8', 'line_ending': 'LF', 'timestamp_timezone': config['timezone'],
        'reproducibility_scope': 'same generator/configuration and Python random implementation; no wall-clock metadata',
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT)
    args = parser.parse_args()
    configuration = json.loads(CONFIG.read_text(encoding='utf-8'))
    generate(args.output_root.resolve(), configuration)
    print(f'Generated {configuration["attempts"]:,} attempts per Phase 2 variant; Phase 1 untouched.')
