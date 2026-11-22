"""Choose one observed segment and check its direction in a fresh analysis."""
from collections import defaultdict

from app.analytics.source_conflicts import checked_pair
from app.contracts import Filters
from app.evidence.verify import verify_evidence
from app.quality.policy import blocked


def propose_test(evidence):
    verify_evidence(evidence)
    if blocked(evidence.quality):
        raise ValueError('Segment testing requires a certified measurement.')
    current = evidence.request.filters
    if current.payer_bank_id and current.payment_method:
        raise ValueError('This analysis already covers a single bank and payment method.')
    rates = defaultdict(dict)
    for row in evidence.results['segments']:
        if row['rate'] is not None:
            rates[(row['payer_bank_id'], row['payment_method'])][row['period']] = row['rate']
    candidates = [(abs(values[1] - values[0]), bank, method, values[1] - values[0])
                  for (bank, method), values in rates.items() if 0 in values and 1 in values]
    if not candidates:
        raise ValueError('No segment has a measurable rate in both periods.')
    _, bank, method, change = min(candidates, key=lambda row: (-row[0], row[1], row[2]))
    direction = 'decreases' if change < 0 else 'increases' if change > 0 else 'stays constant'
    filters = Filters(payer_bank_id=bank, payment_method=method, merchant_id=current.merchant_id)
    return filters, f'Test whether the rate for {bank} / {method} {direction} in a fresh comparison.'


def assess_test(parent, child, *, left_epoch=None, right_epoch=None):
    checked_pair(parent, child)
    filters, hypothesis = propose_test(parent)
    expected = parent.request.model_copy(update={'filters': filters})
    if child.request != expected:
        raise ValueError('The test changed the parent metric contract or selected a different segment.')
    match = [r for r in parent.results['segments'] if r['payer_bank_id'] == filters.payer_bank_id
             and r['payment_method'] == filters.payment_method]
    before = {r['period']: r['rate'] for r in match}
    after = {r['period']: r['rate'] for r in child.results['overall']}
    status = 'inconclusive'
    observed_change = None
    if (left_epoch is not None and left_epoch == right_epoch
            and parent.semantic_version == child.semantic_version and all(after.get(i) is not None for i in (0, 1))):
        original_change = before[1] - before[0]
        observed_change = after[1] - after[0]
        same_direction = (observed_change > 0) == (original_change > 0) and (observed_change < 0) == (original_change < 0)
        status = 'supported' if same_direction else 'contradicted'
    return {
        'hypothesis': hypothesis, 'status': status, 'observed_change_pp': None if observed_change is None else 100 * observed_change,
        'evidence_ids': [parent.id, child.id],
        'limitation': 'This checks the direction of a measured rate change. Causal attribution requires independent operational evidence.',
    }
