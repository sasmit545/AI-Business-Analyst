import pytest
from app.analytics.contributions import decompose


def test_symmetric_both_weights_and_rates_change():
    rows = [dict(period=0, key='a', attempts=80, successes=72),
            dict(period=0, key='b', attempts=20, successes=10),
            dict(period=1, key='a', attempts=40, successes=32),
            dict(period=1, key='b', attempts=60, successes=36)]
    result = decompose(rows, ['key'])
    assert result['available']
    assert result['mix'] == pytest.approx(-0.12)
    assert result['within'] == pytest.approx(-0.02)
    assert result['change'] == pytest.approx(-0.14)


def test_missing_segment_or_empty_population_unavailable():
    assert not decompose([], ['key'])['available']
    assert not decompose([dict(period=0,key='a',attempts=1,successes=1), dict(period=1,key='b',attempts=1,successes=0)], ['key'])['available']
