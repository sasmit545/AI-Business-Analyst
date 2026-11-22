from types import SimpleNamespace

import pytest

from app.analytics.adaptive import derive_observations
from app.evidence.attempt_guidance import attempt_guidance


def results(groups):
    observations = []
    for period, bank, method, attempts, reasons in groups:
        successes = attempts - sum(reasons.values())
        for reason, count in [(None, successes), *reasons.items()]:
            if count:
                observations.append(dict(period=period, payer_bank_id=bank, bank_name=bank, payment_method=method,
                                         day=('2026-01-01', '2026-02-01')[period],
                                         status='SUCCESS' if reason is None else 'FAILED', failure_reason=reason,
                                         attempts=count, successes=count if reason is None else 0))
    return SimpleNamespace(results=derive_observations(observations))


def guidance(evidence, kind, dimension='reason', period='comparison', measure='rate'):
    intent = SimpleNamespace(kind=kind, dimension=dimension, period=period, measure=measure)
    return attempt_guidance(evidence, intent)


@pytest.fixture
def mixed():
    return results([
        (0, 'Aster', 'P', 1000, {'Widget': 80}), (1, 'Aster', 'P', 1000, {'Widget': 80}),
        (0, 'Birch', 'Q', 1000, {'Widget': 40}), (1, 'Birch', 'Q', 1000, {'Widget': 40, 'Relay': 100}),
        (0, 'Cedar', 'Q', 2, {}), (1, 'Cedar', 'Q', 2, {'Retry': 1})])


def test_rankings_answer_different_questions_on_same_evidence(mixed):
    volume = guidance(mixed, 'volume')
    assert volume['leaders'] == [{'failure_reason':'Widget'}]
    assert '120' in volume['finding'] and '221' in volume['finding']
    assert 'of 120 (100.00%)' in volume['finding']
    assert 'Aster' in ' '.join(volume['recommendations'])
    assert guidance(mixed, 'deterioration')['leaders'] == [{'failure_reason':'Relay'}]
    assert guidance(mixed, 'deterioration', 'bank')['leaders'] == [{'payer_bank_id':'Cedar'}]
    within = guidance(mixed, 'contribution', 'segment')
    assert within['leaders'] == [{'payer_bank_id':'Birch','payment_method':'Q'}]
    assert 'Relay (0/1,000 to 100/1,000)' in within['recommendations'][0]
    assert guidance(mixed, 'contribution', 'reason')['leaders'] == [{'failure_reason':'Relay'}]
    assert guidance(mixed, 'volume', 'overall', measure='failed_attempts')['leaders'] == volume['leaders']


def test_period_measure_ties_and_distribution_follow_the_rows():
    data = results([(0, 'North', 'Q', 100, {'Old':9}), (0, 'South', 'Q', 40, {'New':2}),
                    (1, 'North', 'Q', 40, {'Moved':7}), (1, 'South', 'Q', 200, {'Other':7})])
    assert guidance(data, 'volume', period='baseline')['leaders'] == [{'failure_reason':'Old'}]
    result = guidance(data, 'volume')
    assert result['leaders'] == [{'failure_reason':'Moved'}, {'failure_reason':'Other'}]
    assert 'Other' in result['finding'] and 'Moved' in result['finding']
    assert guidance(data, 'volume', 'bank', measure='attempts')['leaders'] == [{'payer_bank_id':'South'}]
    assert '240' in guidance(data, 'count', 'overall', measure='attempts')['finding']


def test_mix_shift_changes_next_step():
    data = results([(0, 'One', 'Alpha', 80, {'Loss':8}), (0, 'One', 'Beta', 20, {'Loss':10}),
                    (1, 'One', 'Alpha', 20, {'Loss':2}), (1, 'One', 'Beta', 80, {'Loss':40})])
    outcome = guidance(data, 'contribution', 'method')
    assert 'mix' in outcome['finding'].lower() and '24.00' in outcome['finding']
    assert 'Beta' in ' '.join(outcome['recommendations']) and 'traffic' in ' '.join(outcome['recommendations']).lower()
    assert '0.00' in outcome['finding']


def test_largest_traffic_gain_can_offset_a_mix_driven_decline():
    data = results([(0,'A','M',100,{'Loss':10}), (1,'A','M',700,{'Loss':70}),
                    (0,'B','M',100,{'Loss':100}), (1,'B','M',150,{'Loss':150}),
                    (0,'C','M',800,{'Loss':80}), (1,'C','M',150,{'Loss':15})])
    answer = guidance(data, 'contribution', 'bank')
    assert answer['leaders'] == [{'payer_bank_id':'B'}]
    assert '10.00% to 15.00%' in answer['finding'] and '-4.5000' in answer['finding']


def test_redistributing_outcomes_changes_the_winner_and_the_next_check():
    def ranked(north, south):
        data = results([(0, 'North', 'Q', 100, {'Swing':2}), (0, 'South', 'P', 100, {'Signal':2}),
                        (1, 'North', 'Q', 100, {'Swing':north}), (1, 'South', 'P', 100, {'Signal':south})])
        return guidance(data, 'volume')

    first, second = ranked(11, 3), ranked(3, 11)
    assert first['leaders'] == [{'failure_reason':'Swing'}] and 'North / Q' in first['recommendations'][0]
    assert second['leaders'] == [{'failure_reason':'Signal'}] and 'South / P' in second['recommendations'][0]


def test_rate_ties_preserve_different_exposures():
    data = results([(0, 'West', 'L', 10, {}), (1, 'West', 'L', 10, {'Fault':1}),
                    (0, 'East', 'L', 500, {}), (1, 'East', 'L', 500, {'Fault':50})])
    outcome = guidance(data, 'deterioration', 'bank')
    assert outcome['leaders'] == [{'payer_bank_id':'East'}, {'payer_bank_id':'West'}]
    assert '50/500' in outcome['finding'] and '1/10' in outcome['finding']


def test_missing_population_and_absent_dimensions_are_explained():
    data = results([(0, 'One', 'Q', 100, {'Loss':4})])
    missing = guidance(data, 'deterioration')
    assert not missing['leaders'] and 'comparison' in missing['finding'].lower() and 'attempts' in missing['finding']
    assert guidance(data, 'volume', period='baseline')['leaders'] == [{'failure_reason':'Loss'}]
    data = results([(0, 'One', 'Q', 10, {}), (1, 'Two', 'Q', 10, {'Loss':2})])
    missing = guidance(data, 'deterioration', 'bank')
    assert not missing['leaders'] and 'both' in missing['finding'].lower()
    assert not guidance(data, 'contribution', 'segment')['leaders']
    merchant = guidance(data, 'volume', 'merchant')
    assert not merchant['leaders'] and 'merchant' in merchant['finding'].lower()


def test_improving_success_can_have_a_worsening_label():
    data = results([(0, 'Oak', 'Z', 100, {'First':15, 'Second':1}),
                    (1, 'Oak', 'Z', 150, {'First':2, 'Second':6})])
    summary = guidance(data, 'summary', 'overall')
    assert summary['leaders'] == [{'failure_reason':'Second'}]
    assert '1.00%' in summary['finding'] and '4.00%' in summary['finding']
    assert 'Second' in ' '.join(summary['recommendations'])


def test_neutral_and_no_failure_cases():
    data = results([(0, 'Oak', 'Z', 20, {}), (1, 'Oak', 'Z', 5, {})])
    for kind in ('deterioration', 'volume', 'contribution', 'summary'):
        result = guidance(data, kind)
        assert not result['leaders']
        assert 'outage' not in result['finding'].lower()


def test_a_trend_uses_only_days_with_eligible_attempts(mixed):
    result = guidance(mixed, 'trend', 'overall')
    assert result['source'] == 'daily' and '2026-02-01' in result['finding']
