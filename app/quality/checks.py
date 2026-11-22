"""Inspect raw text and references before any metric casts or filtering."""
from app.contracts import QualityRecord
from app.context.catalog import catalog


def quality_sql(scenario):
    catalog(scenario)
    p, b, m = (f'{scenario}.{table}' for table in ('payments', 'banks', 'merchants'))
    tests = {
        'duplicate_occurrences': f'(SELECT COUNT(*) - COUNT(DISTINCT attempt_id) FROM {p})',
        'missing_attempt_id': f"(SELECT COUNT(*) FROM {p} WHERE attempt_id IS NULL OR attempt_id = '')",
        'missing_timestamps': f"(SELECT COUNT(*) FROM {p} WHERE attempted_at IS NULL OR attempted_at = '')",
        'malformed_timestamps': f"(SELECT COUNT(*) FROM {p} WHERE attempted_at <> '' AND (NOT pg_input_is_valid(attempted_at, 'timestamp with time zone') OR NOT attempted_at ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]+)?[+]05:30$'))",
        'invalid_status_reason': f"(SELECT COUNT(*) FROM {p} WHERE status IS NULL OR failure_reason IS NULL OR NOT ((status = 'SUCCESS' AND failure_reason = '') OR (status = 'FAILED' AND failure_reason IN ('BANK_TIMEOUT','INSUFFICIENT_FUNDS','AUTHENTICATION_FAILED','LIMIT_EXCEEDED'))))",
        'invalid_amount_currency': f"(SELECT COUNT(*) FROM {p} WHERE amount_paise IS NULL OR NOT amount_paise ~ '^[1-9][0-9]*$' OR currency IS NULL OR currency <> 'INR')",
        'invalid_method': f"(SELECT COUNT(*) FROM {p} WHERE payment_method IS NULL OR payment_method NOT IN ('CARD','UPI'))",
        'orphan_merchants': f'(SELECT COUNT(*) FROM {p} p LEFT JOIN {m} m ON p.merchant_id = m.merchant_id WHERE m.merchant_id IS NULL)',
        'orphan_banks': f'(SELECT COUNT(*) FROM {p} p LEFT JOIN {b} b ON p.payer_bank_id = b.bank_id WHERE b.bank_id IS NULL)',
        'duplicate_banks': f'(SELECT COUNT(*) - COUNT(DISTINCT bank_id) FROM {b})',
        'duplicate_merchants': f'(SELECT COUNT(*) - COUNT(DISTINCT merchant_id) FROM {m})',
    }
    return 'SELECT ' + ', '.join(f'{expr} AS {name}' for name, expr in tests.items())


def check_quality(bundle):
    row = bundle.query('quality', quality_sql(bundle.authorization.scenario))[0]
    return [QualityRecord(rule=k, count=v, status='BLOCK' if v else 'PASS') for k, v in row.items()]
