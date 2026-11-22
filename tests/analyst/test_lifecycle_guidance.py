from types import SimpleNamespace

import pytest

from app.analytics.lifecycle import derive
from app.contracts import QualityRecord
from app.evidence.lifecycle_guidance import blocked_guidance, lifecycle_guidance
from test_source_conflicts import measurement


def objective(kind='summary', dimension='overall', period='comparison', measure='rate'):
    return SimpleNamespace(kind=kind, dimension=dimension, period=period, measure=measure)


def result(metric, segments, *, health=None):
    rows = [dict(period=p, payer_bank_id=bank, payment_method=method, numerator=n, denominator=d, excluded=0)
            for p, bank, method, n, d in segments]
    overall = []
    for period in (0, 1):
        members = [row for row in rows if row['period'] == period]
        group = {key: sum(row[key] for row in members) for key in ('numerator', 'denominator', 'excluded')}
        if health:
            group.update(health[period])
        overall.append(dict(period=period, **group))
    return measurement(metric).model_copy(update={'results': derive({'segments': rows, 'overall': overall}, metric)})


@pytest.mark.parametrize('metric,description,check', [
    ('order_conversion', 'mature orders unpaid at 24 hours', 'first-attempt success'),
    ('first_attempt_success', 'mature orders without a successful first attempt', 'retry uptake'),
    ('retry_uptake', 'initially failed orders without an observed retry', 'retry eligibility'),
    ('retry_recovery_all', 'initially failed orders unrecovered', 'recovery among retried orders'),
    ('retry_recovery_retried', 'retried orders unrecovered', 'retry attempt traces'),
    ('settlement_count', 'due obligations outstanding', 'settlement ledger'),
    ('settlement_amount', 'gross paise outstanding', 'settlement ledger'),
])
def test_stage_guidance_uses_exact_measured_gap_and_named_check(metric, description, check):
    ev = result(metric, [(0, 'Quartz', 'UPI', 9, 10), (1, 'Quartz', 'UPI', 6, 10)])
    guidance = lifecycle_guidance(ev, objective())
    assert f'4 {description}' in guidance['finding']
    assert 'Quartz / UPI' in guidance['finding']
    assert ev.observation_cutoff in guidance['finding']
    assert check in ' '.join(guidance['recommendations'])
    assert 'Quartz / UPI' in guidance['recommendations'][0]


def test_rankings_use_requested_grain_denominators_and_ties():
    rows = [(0, 'Large', 'CARD', 90, 100), (1, 'Large', 'CARD', 150, 200),
            (0, 'Small', 'CARD', 4, 4), (1, 'Small', 'CARD', 1, 2),
            (0, 'Small', 'UPI', 1, 1), (1, 'Small', 'UPI', 5, 10),
            (1, 'New', 'UPI', 2, 8)]
    ev = result('order_conversion', rows)
    volume = lifecycle_guidance(ev, objective('volume', 'bank'))
    decline = lifecycle_guidance(ev, objective('deterioration', 'segment'))
    contribution = lifecycle_guidance(ev, objective('contribution', 'bank'))
    assert volume['leaders'] == ['Large']
    assert decline['leaders'] == ['Small / CARD', 'Small / UPI']
    assert '50.00 percentage points' in decline['finding'] and '1 group' in decline['finding']
    assert '1/2' in decline['finding'] and '5/10' in decline['finding']
    assert contribution['leaders'] == ['Large'] and 'overall' in contribution['finding']
    assert lifecycle_guidance(ev, objective('deterioration', 'bank'))['leaders'] == ['Small']


def test_amount_count_and_selected_period_can_prioritize_different_segments():
    counts = result('settlement_count', [(0, 'North', 'UPI', 0, 8), (0, 'East', 'UPI', 7, 8),
                                          (1, 'North', 'UPI', 6, 8), (1, 'East', 'UPI', 0, 8)])
    amounts = result('settlement_amount', [(1, 'North', 'UPI', 600, 2800), (1, 'East', 'UPI', 0, 80)])
    assert lifecycle_guidance(counts, objective('volume','bank'))['leaders'] == ['East']
    assert lifecycle_guidance(counts, objective('volume','bank','baseline'))['leaders'] == ['North']
    assert lifecycle_guidance(amounts, objective('volume','bank'))['leaders'] == ['North']
    assert lifecycle_guidance(counts, objective('volume','bank', measure='numerator'))['leaders'] == ['North']


def test_coverage_is_attempt_weighted_and_missing_intervals_prioritize_telemetry():
    telemetry = [dict(unmatched=0, attempt_weighted_bucket_p95_ms=152, attempt_weighted_availability_pct=99),
                 dict(unmatched=7, attempt_weighted_bucket_p95_ms=183, attempt_weighted_availability_pct=98)]
    ev = result('bank_health', [(0, 'X', 'UPI', 20, 20), (1, 'X', 'UPI', 15, 20)], health=telemetry)
    guidance = lifecycle_guidance(ev, objective())
    assert '13/20' in guidance['finding'] and '183' in guidance['finding']
    assert 'five-minute' in guidance['recommendations'][0] and '7' in guidance['recommendations'][0]
    assert 'trace' in guidance['recommendations'][0]


def test_empty_successful_and_unsupported_objectives_do_not_invent_interventions():
    empty = result('retry_uptake', [])
    assert 'zero' in lifecycle_guidance(empty, objective())['finding']
    complete = result('settlement_count', [(0, 'East', 'UPI', 5, 5), (1, 'East', 'UPI', 10, 10)])
    assert 'all 10' in lifecycle_guidance(complete, objective())['finding']
    for unsupported in (objective('trend'), objective('volume','reason'), objective('volume','merchant')):
        guidance = lifecycle_guidance(complete, unsupported)
        assert guidance['source'] == 'overall' and not guidance.get('leaders')
        assert 'separate' in guidance['recommendations'][0]


def test_simple_count_reports_measured_stage_numerator_even_with_zero_eligible():
    ev = result('retry_recovery_retried', [(0, 'X', 'UPI', 2, 6), (1, 'X', 'UPI', 3, 6)])
    count = lifecycle_guidance(ev, objective('count'))
    assert '3 initially failed mature orders recovered by cutoff' in count['finding'] and count['source'] == 'overall'
    empty = lifecycle_guidance(result('retry_recovery_retried', []), objective('count', measure='denominator'))
    assert '0 retried initially failed mature orders' in empty['finding']


def test_blocked_diagnostics_address_each_observed_rule_without_certifying_metrics():
    ev = measurement().model_copy(update={'results':{}, 'quality':[
        QualityRecord(rule='orphan_merchants', count=3, status='BLOCK'),
        QualityRecord(rule='missing_timestamps', count=4, status='BLOCK'),
        QualityRecord(rule='duplicate_occurrences', count=1, status='BLOCK'),
        QualityRecord(rule='invalid_method', count=0, status='PASS')]})
    guidance = blocked_guidance(ev, objective('next_steps'))
    assert guidance['source'] == 'quality'
    assert all(rule in guidance['finding'] for rule in ('orphan_merchants', 'missing_timestamps', 'duplicate_occurrences'))
    assert 'attempt_id' in str(guidance['recommendations']) and 'attempted_at' in str(guidance['recommendations'])
    assert 'merchant_id' in str(guidance['recommendations']) and 'invalid_method' not in str(guidance)
