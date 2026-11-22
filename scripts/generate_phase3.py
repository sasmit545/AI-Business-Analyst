"""Generate deterministic order/attempt/settlement chains; never rewrite earlier phases."""
import argparse
import csv
from datetime import datetime, timedelta
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random

from generate_phase2 import allocate, date_hour_weights, read_dimensions
from lifecycle_schema import FIELDS, SCHEMA_VERSION, data_dir
from validate_phase1 import save_json, sha256

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'profiles/lifecycle_v1.json'


def stream(seed, name):
    return random.Random(int.from_bytes(hashlib.sha256(f'phase3:streams:v1:{seed}:{name}'.encode()).digest(), 'big'))


def stamp(value):
    return value.isoformat(timespec='milliseconds')


def write_tables(folder, tables):
    folder.mkdir(parents=True, exist_ok=True)
    for name, fields in FIELDS.items():
        with (folder / f'{name}.csv').open('w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(tables[name])


def generate(root, config):
    if config['profile_id'] != 'lifecycle_v1' or config['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported lifecycle profile/schema')
    seed, total = config['seed'], config['orders']
    if total <= 0:
        raise ValueError('orders must be positive')
    cutoff = datetime.fromisoformat(config['observation_cutoff'])
    tables = {name: [] for name in FIELDS}
    tables.update(read_dimensions())
    tables['payment_methods'] = [dict(zip(FIELDS['payment_methods'], values)) for values in (
        ('CARD', 'Card', 'Customer payment instrument'), ('UPI', 'UPI', 'Customer payment instrument'))]
    tables['failure_reasons'] = [dict(zip(FIELDS['failure_reasons'], values)) for values in (
        ('BANK_TIMEOUT', 'Bank timeout', 'technical'),
        ('AUTHENTICATION_FAILED', 'Authentication failed', 'authentication'),
        ('INSUFFICIENT_FUNDS', 'Insufficient funds', 'customer'),
        ('LIMIT_EXCEEDED', 'Limit exceeded', 'customer'))]
    banks = [bank for bank, count in allocate(total, config['bank_weights']).items() for _ in range(count)]
    stream(seed, 'traffic.banks').shuffle(banks)
    merchant_counts = allocate(total, config['merchant_weights'])
    times, outcomes, reasons, retries, latency, ingestion = [stream(seed, name) for name in (
        'traffic.time', 'outcomes.status', 'outcomes.reasons', 'retries', 'latency', 'ingestion')]
    amounts = {category: stream(seed, f'amounts.{category}') for category in config['amounts']['median_inr']}
    for merchant in tables['merchants']:
        merchant_id, category = merchant['merchant_id'], merchant['category']
        share = Fraction(str(config['upi_share_by_category'][category]))
        methods = [method for method, count in allocate(merchant_counts[merchant_id], {'UPI': share, 'CARD': 1-share}).items() for _ in range(count)]
        stream(seed, f'traffic.methods.{merchant_id}').shuffle(methods)
        local_index = 0
        for slot, count in allocate(merchant_counts[merchant_id], date_hour_weights(config, category)).items():
            for _ in range(count):
                index = len(tables['orders'])
                order_id = f'O{index+1:09}'
                bank, method = banks[index], methods[local_index]
                local_index += 1
                created = datetime.fromisoformat(slot + ':00:00' + config['timezone']) + timedelta(seconds=times.randrange(3600))
                spec = config['amounts']
                amount = str(round(100 * min(spec['max_inr'], max(spec['min_inr'],
                    amounts[category].lognormvariate(math.log(spec['median_inr'][category]), spec['sigma'])))))
                tables['orders'].append(dict(zip(FIELDS['orders'], (order_id, merchant_id, stamp(created), amount, config['currency']))))
                attempted = created + timedelta(seconds=config['initial_delay_seconds'])
                for number in range(1, config['max_attempts'] + 1):
                    attempt_id = f'L{len(tables["payments"])+1:09}'
                    success = outcomes.random() < config['success_probability'][method][bank]
                    weights = config['failure_weights'][method]
                    reason = '' if success else reasons.choices(list(weights), weights=list(weights.values()), k=1)[0]
                    duration = round(min(config['latency']['max_ms'], max(config['latency']['min_ms'],
                        latency.lognormvariate(math.log(config['latency']['median_ms'][method]), config['latency']['sigma']))))
                    completed = attempted + timedelta(milliseconds=duration)
                    ingested = completed + timedelta(milliseconds=ingestion.randint(0, config['ingestion_max_delay_ms']))
                    if ingested > cutoff:
                        raise ValueError('Configured order/retry chain extends past observation cutoff')
                    tables['payments'].append(dict(zip(FIELDS['payments'], (attempt_id, stamp(attempted), merchant_id,
                        bank, method, amount, config['currency'], 'SUCCESS' if success else 'FAILED', reason,
                        order_id, str(number), stamp(completed), str(duration), stamp(ingested)))))
                    if success:
                        due = completed + timedelta(hours=24)
                        settled = due <= cutoff
                        tables['settlements'].append(dict(zip(FIELDS['settlements'], (f'S{attempt_id[1:]}', attempt_id,
                            stamp(due), stamp(due) if settled else '', 'SETTLED' if settled else 'PENDING', amount))))
                        break
                    if number == config['max_attempts'] or retries.random() >= config['retry_probability']:
                        break
                    attempted = completed + timedelta(seconds=config['retry_delay_seconds'])
    health = stream(seed, 'bank_health')
    observed = datetime.fromisoformat(config['start_date'] + 'T00:00:00' + config['timezone'])
    while observed < cutoff:
        for bank in sorted(config['bank_weights']):
            for method in ('CARD', 'UPI'):
                spec = config['bank_health']
                availability = round(health.uniform(spec['availability_min_pct'], spec['availability_max_pct']), 3)
                p95 = health.randint(*spec['p95_latency_range_ms'][method])
                tables['bank_health'].append(dict(zip(FIELDS['bank_health'], (bank, method, stamp(observed), f'{availability:.3f}', str(p95)))))
        observed += timedelta(minutes=5)
    folder = data_dir(root)
    write_tables(folder, tables)
    payload = json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    save_json(root / 'evaluation/phase3/generation_manifest.json', {
        'profile_id': 'lifecycle_v1', 'schema_version': SCHEMA_VERSION, 'generator_version': '1.0.0',
        'seed': seed, 'configuration': config, 'configuration_sha256': hashlib.sha256(payload).hexdigest(),
        'actual_orders': len(tables['orders']), 'actual_attempts': len(tables['payments']),
        'files': {(folder / f'{name}.csv').relative_to(root).as_posix():
                  {'rows': len(rows), 'sha256': sha256(folder / f'{name}.csv')} for name, rows in tables.items()},
        'encoding': 'UTF-8', 'line_ending': 'LF', 'reproducibility_scope': 'same configuration, code and Python random implementation',
    })
    return tables


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = generate(args.output_root.resolve(), json.loads(CONFIG.read_text(encoding='utf-8')))
    print(f'Generated {len(result["orders"]):,} orders and {len(result["payments"]):,} completed attempts.')
