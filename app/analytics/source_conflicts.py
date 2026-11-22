"""Compare two published measurements under their registered definitions."""
from app.context.catalog import catalog
from app.evidence.verify import verify_evidence
from app.quality.policy import blocked


def checked_pair(left, right):
    for field in ('subject', 'session_id', 'scenario'):
        if getattr(left.scope, field) != getattr(right.scope, field):
            raise ValueError('Both sources must belong to this authorized session and dataset.')
    for evidence in (left, right):
        verify_evidence(evidence)
        if blocked(evidence.quality):
            raise ValueError('Source comparison requires two certified measurements.')


def _source(evidence, epoch):
    req = evidence.request
    definition = catalog(evidence.scope.scenario)['metrics'][req.metric]
    periods = []
    for row in evidence.results['overall']:
        if req.metric == 'attempt_success':
            periods.append(dict(period=row['period'], numerator=row['successes'], denominator=row['attempts'], rate=row['rate']))
        else:
            periods.append(dict(row))
    return {
        'evidence_id': evidence.id, 'snapshot': evidence.snapshot, 'import_epoch': epoch,
        'semantic_version': evidence.semantic_version, 'metric': req.metric,
        **{k: definition[k] for k in ('numerator', 'denominator', 'grain', 'time_field')},
        'filters': req.filters.model_dump(exclude_none=True),
        'baseline': req.baseline.model_dump(mode='json'), 'comparison': req.comparison.model_dump(mode='json'),
        'observation_cutoff': evidence.observation_cutoff, 'periods': periods,
    }


def compare_sources(left_evidence, right_evidence, *, left_epoch=None, right_epoch=None):
    checked_pair(left_evidence, right_evidence)
    left, right = _source(left_evidence, left_epoch), _source(right_evidence, right_epoch)
    contract = ('metric', 'numerator', 'denominator', 'grain', 'time_field', 'filters', 'baseline',
                'comparison', 'observation_cutoff')
    differences = [k for k in contract if left[k] != right[k]]
    if differences:
        status = 'different_definitions'
        explanation = 'The measurements use different ' + ', '.join(k.replace('_', ' ') for k in differences) + '.'
    elif left_epoch is None or left_epoch != right_epoch:
        status = 'unresolved'
        explanation = 'A common fixture import could not be established. Recalculate both measurements together.'
    elif left['semantic_version'] != right['semantic_version']:
        status = 'unresolved'
        explanation = 'The sources use different semantic versions. Verify their historical definitions.'
    elif left['periods'] != right['periods']:
        status = 'unresolved'
        explanation = 'The period results disagree under the same recorded contract. Inspect both queries before relying on either result.'
    else:
        status = 'agrees'
        explanation = 'Both sources agree on the period results under the same metric contract and fixture import.'
    return {'status': status, 'explanation': explanation, 'left': left, 'right': right}
