import json

import pytest
from pydantic import ValidationError

from app.contracts import AnalysisRequest, Window
from app.context.catalog import catalog


def test_catalog_contains_only_selected_scope():
    data = catalog('lifecycle_v1')
    assert len(data['tables']) == 8
    assert 'retries' not in data['tables']
    assert data['metrics']['attempt_success']['denominator'] == 'All completed attempts in the requested window and filters'
    assert 'scenario_a' not in json.dumps(data)
    assert len(catalog('scenario_b')['tables']) == 3


def test_scope_override_and_unknown_metric_rejected():
    args = dict(baseline={'start': '2026-10-01T00:00:00+05:30', 'end': '2026-10-15T00:00:00+05:30'}, comparison={'start': '2026-10-15T00:00:00+05:30', 'end': '2026-10-29T00:00:00+05:30'})
    assert AnalysisRequest(**args).metric == 'attempt_success'
    for extra in ({'schema': 'scenario_b'}, {'metric': 'order_conversion'}, {'filters': {'sql': '1=1'}}):
        with pytest.raises(ValidationError):
            AnalysisRequest(**(args | extra))


def test_window_requires_offsets_and_positive_duration():
    with pytest.raises(ValidationError):
        Window(start='2026-10-01', end='2026-10-02')
    with pytest.raises(ValidationError):
        Window(start='2026-10-02T00:00:00+05:30', end='2026-10-01T00:00:00+05:30')
