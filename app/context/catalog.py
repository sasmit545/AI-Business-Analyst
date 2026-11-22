"""Curated definitions only; no developer documents or evaluator imports."""
from importlib.resources import files

import yaml
from app.contracts import LIFECYCLE_OBSERVATION_CUTOFF


def asset(name):
    return yaml.safe_load(files('app').joinpath('semantic', name + '.yaml').read_text(encoding='utf-8'))


def catalog(scenario: str) -> dict:
    mapping = asset('scenarios')
    if scenario not in mapping['scenarios']:
        raise ValueError('Unknown selected schema')
    kind = mapping['scenarios'][scenario]
    metrics=asset('metrics')['implemented']
    if kind!='lifecycle':
        metrics={'attempt_success':metrics['attempt_success']}
    return {'selected_schema': scenario, 'version': '1.0.0',
            'tables': mapping['adapters'][kind], 'metrics': metrics,
            'filter_values': mapping['filter_values'].get(kind, {}),
            'observation_cutoff':LIFECYCLE_OBSERVATION_CUTOFF.isoformat() if kind=='lifecycle' else None,
            'joins': asset('joins'), 'timezone': 'Asia/Kolkata',
            'notes': ['One row is one completed payment attempt.',
                      'Failure labels do not prove infrastructure root causes.',
                      'Windows are explicit, timezone-aware and half-open.',
                      'Retries are attempts with attempt_number greater than one; no retries table exists.']}
