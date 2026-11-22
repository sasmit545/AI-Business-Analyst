"""Decision guidance from a verified lifecycle cohort or its blocking diagnostics."""
from collections import defaultdict
from fractions import Fraction

from app.analytics.lifecycle import DEFINITIONS


# Each gap is denominator minus numerator, expressed in the measured stage's unit.
GAPS = {
    'order_conversion': 'mature orders unpaid at 24 hours',
    'first_attempt_success': 'mature orders without a successful first attempt',
    'retry_uptake': 'initially failed orders without an observed retry',
    'retry_recovery_all': 'initially failed orders unrecovered',
    'retry_recovery_retried': 'retried orders unrecovered',
    'settlement_count': 'due obligations outstanding',
    'settlement_amount': 'gross paise outstanding',
    'bank_health': 'unsuccessful observed attempts',
}

CHECKS = {
    'order_conversion':
        'Ask the analyst to compare first-attempt success for this order cohort. '
        'If the loss begins on the first attempt, examine first-attempt failures. '
        'If first-attempt success holds steady, compare retry uptake and recovery among retried orders.',
    'first_attempt_success':
        'Ask the analyst to compare retry uptake among initially failed orders in this cohort. '
        'Low uptake points to the retry opportunity. If orders were retried, measure recovery on those retried orders.',
    'retry_uptake':
        'Ask payment operations for retry eligibility and offer records for initially failed orders. '
        'Compare eligible orders offered a retry with orders that started one to locate the loss.',
    'retry_recovery_all':
        'Ask the analyst to compare retry uptake and recovery among retried orders at the same cutoff. '
        'If uptake fell, check retry eligibility and offers. If recovery after a retry fell, review retry outcomes.',
    'retry_recovery_retried':
        'Ask payment operations for retry attempt traces on the unrecovered retried orders. '
        'Compare outcome codes and completion times with recovered retries to distinguish repeated failures from late completion.',
    'settlement_count':
        'Ask settlement operations to reconcile the due attempt IDs with the settlement ledger and payout acknowledgements. '
        'A later acknowledgement points to timing. A missing acknowledgement calls for tracing that obligation.',
    'settlement_amount':
        'Ask settlement operations to reconcile outstanding due gross amounts against the settlement ledger, '
        'starting with the largest obligations. Match their payout acknowledgements to distinguish late postings from missing ones.',
    'bank_health':
        'Ask payment operations to match failed and successful attempt traces to the same bank, method and five-minute health intervals. '
        'Concentration in impaired intervals warrants a bank-side trace review. A similar pattern in healthy intervals calls for checking the payment path.',
}


def _answer(finding, recommendation, source='overall', leaders=()):
    return {'finding': finding, 'recommendations': [recommendation], 'source': source, 'leaders': list(leaders)}


def _groups(rows, dimension):
    keys = {'bank': ('payer_bank_id',), 'method': ('payment_method',)}.get(dimension, ('payer_bank_id', 'payment_method'))
    periods = [defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])]
    for row in rows:
        group = tuple(row[key] for key in keys)
        cell = periods[row['period']][group]
        cell[0] += row['numerator']
        cell[1] += row['denominator']
    return periods


def _label(group):
    return ' / '.join(str(value) if value is not None else '(unassigned)' for value in group)


def _leaders(values):
    maximum = max(values.values())
    return sorted((group for group, score in values.items() if score == maximum), key=_label)


def _declines(periods, metric, title):
    before, after = periods
    groups = before.keys() | after.keys()
    changes = {g: Fraction(*before[g]) - Fraction(*after[g]) for g in before.keys() & after.keys()
               if before[g][1] and after[g][1]}
    missing = len(groups) - len(changes)
    coverage = (f" {missing} group{'s' if missing != 1 else ''} lacked a denominator in one or both periods."
                if missing else '')
    if not changes or max(changes.values()) <= 0:
        finding = ('Every comparable group held steady or improved.' if changes else 'No group had eligible observations in both periods.')
        return _answer(f'{title}. {finding}{coverage}',
                       'Check exposure in the two windows before choosing a group for a performance investigation.', 'segments')
    winners = _leaders(changes)
    details = [f'{_label(g)} ({before[g][0]:,}/{before[g][1]:,} to {after[g][0]:,}/{after[g][1]:,})' for g in winners]
    finding = (f'{title} fell most for {", ".join(details)}, down {100 * changes[winners[0]]:.2f} percentage points.'
               + coverage)
    names = [_label(group) for group in winners]
    return _answer(finding, f'Begin with {", ".join(names)}. {CHECKS[metric]}', 'segments', names)


def _contribution(periods, totals, metric, title):
    # Gap / total eligible is additive across groups, even when a group appears in only one period.
    b, c = totals
    change = Fraction(c['numerator'], c['denominator']) - Fraction(b['numerator'], b['denominator'])
    if not change:
        return _answer(f'Overall {title} held steady across these windows.',
                       'Ask for within-group rate changes to see whether opposing movements offset one another.')
    b_groups, c_groups = periods
    effects = {}
    for group in b_groups.keys() | c_groups.keys():
        bn, bd = b_groups.get(group, (0, 0))
        cn, cd = c_groups.get(group, (0, 0))
        effects[group] = Fraction(bd - bn, b['denominator']) - Fraction(cd - cn, c['denominator'])
    aligned = {group: effect if change > 0 else -effect for group, effect in effects.items()}
    winners = _leaders(aligned)
    names = [_label(group) for group in winners]
    effect = effects[winners[0]]
    qualifier = ' each' if len(names) > 1 else ''
    finding = (f'{", ".join(names)} contributed {100 * effect:+.2f} percentage points{qualifier} to the '
               f'{100 * change:+.2f}-point overall change in {title}. '
               'Each contribution uses the group’s unmet outcomes as a share of the whole period’s eligible total.')
    return _answer(finding, 'Compare the group’s eligible volume and its own completion rate across the windows. '
                   'A shift in volume calls for checking the composition of the cohort. A rate decline calls for examining its measured stage.',
                   'segments', names)


def _health(evidence, selected):
    rows = evidence.results['overall']
    details = []
    missing = 0
    for label, row in zip(('baseline', 'comparison'), rows):
        total = row['denominator']
        if 'unmatched' not in row:
            details.append(f'{label} telemetry coverage unavailable')
            continue
        unmatched = row['unmatched']
        missing += unmatched
        measurements = [f'{total - unmatched:,}/{total:,} attempts aligned']
        latency = row.get('attempt_weighted_bucket_p95_ms')
        availability = row.get('attempt_weighted_availability_pct')
        if latency is not None:
            measurements.append(f'{latency:,.1f} ms mean bucket p95')
        if availability is not None:
            measurements.append(f'{availability:.3f}% mean availability')
        details.append(f'{label} {", ".join(measurements)}')
    finding = 'Attempt-weighted five-minute observations by period. ' + '. '.join(details) + '.'
    if missing:
        return _answer(finding, f'Ask the telemetry owner to trace the {missing:,} unmatched attempts to their bank, method and '
                       'containing five-minute intervals. Check for missing, duplicate or invalid observations, then repeat '
                       'the coverage comparison before interpreting latency or availability.')
    if any('unmatched' not in row for row in rows):
        return _answer(finding, 'Request the aligned-health measurement including matched and unmatched attempt counts '
                       'before comparing the telemetry for the two windows.')
    if selected['denominator'] == selected['numerator']:
        return _answer(finding, 'Monitor coverage, attempt success and latency in the next window. '
                       'Escalate a health check if failed attempts appear alongside degraded telemetry.')
    return _answer(finding, CHECKS['bank_health'])


def _empty(evidence, selected, period, denominator):
    metric = evidence.request.metric
    excluded = selected['excluded']
    if excluded:
        reason = ('obligations were not yet due' if metric.startswith('settlement_') else 'orders had less than 24 hours of observation')
        check = (f'{excluded:,} {reason} at this cutoff. Compare a cohort that is eligible by the available cutoff '
                 'before interpreting its rate.')
    elif metric.startswith('retry_'):
        check = 'Compare first-attempt success for these creation dates, then check whether the observed failed orders met the selected retry denominator.'
    else:
        check = 'Check the chosen dates, filters and observation cutoff against the recorded cohort. Repeat with a populated window to measure a rate.'
    return _answer(f'The {period} denominator is zero ({denominator}) at {evidence.observation_cutoff}.', check)


def lifecycle_guidance(evidence, objective):
    """Resolve a question against already verified overall and bank/method result rows."""
    metric = evidence.request.metric
    title, numerator, denominator = DEFINITIONS[metric]
    totals = evidence.results['overall']
    period = objective.period
    index = int(period == 'comparison')
    selected = totals[index]
    kind = objective.kind
    if objective.dimension in ('reason', 'merchant') or kind == 'trend':
        detail = 'daily trend' if kind == 'trend' else f'{objective.dimension} ranking'
        counts = ' and '.join(f'{name} {r["numerator"]:,}/{r["denominator"]:,}'
                              for name, r in zip(('baseline', 'comparison'), totals))
        return _answer(f'The verified {title} result shows {counts} across the requested periods. '
                       f'A {detail} needs a different breakdown.',
                       f'Ask the data owner for a separate {detail} measurement using the same denominator, dates and cutoff '
                       'before choosing a group or day.')
    measure = getattr(objective, 'measure', 'rate')
    if kind == 'count' and measure == 'rate':
        measure = 'numerator'
    if metric == 'bank_health':
        measure = {'attempts': 'denominator', 'successes': 'numerator'}.get(measure, measure)
    terms = {'numerator': (0, numerator), 'denominator': (1, denominator)}
    if kind == 'count' and measure in terms and objective.dimension == 'overall':
        return _answer(f'{title} in the {period} recorded {selected[measure]:,} {terms[measure][1]} '
                       f'(cutoff {evidence.observation_cutoff}).',
                       'Use the same cohort and cutoff for any comparison of this count.')
    if selected['denominator'] == 0:
        return _empty(evidence, selected, period, denominator)
    if kind in ('deterioration', 'contribution') and not all(r['denominator'] for r in totals):
        empty_index = next(i for i, row in enumerate(totals) if not row['denominator'])
        return _empty(evidence, totals[empty_index], ('baseline', 'comparison')[empty_index], denominator)
    periods = _groups(evidence.results['segments'], objective.dimension)
    if kind == 'deterioration':
        answer = _declines(periods, metric, title)
    elif kind == 'contribution':
        answer = _contribution(periods, totals, metric, title)
    elif metric == 'bank_health' and kind not in ('count', 'volume'):
        return _health(evidence, selected)
    else:
        if kind in ('count', 'volume') and measure in terms:
            field, label = terms[measure]
            value = selected[measure]
            values = {g: cell[field] for g, cell in periods[index].items() if cell[1]}
            leaders = _leaders(values)
            names = [_label(g) for g in leaders]
            qualifier = ' each' if len(names) > 1 else ''
            return _answer(f'{", ".join(names)} led the {period} with {values[leaders[0]]:,} {label}{qualifier} '
                           f'out of {value:,} in the selected scope.',
                           'Compare rates alongside these volumes to determine whether size or lower performance merits investigation.',
                           'segments', names)
        gap = selected['denominator'] - selected['numerator']
        if not gap:
            return _answer(f'In the {period}, all {selected["denominator"]:,} {denominator} met the measure by {evidence.observation_cutoff}.',
                           f'Monitor {title} for the next eligible cohort. Investigate if a gap appears at the same observation horizon.')
        stage = GAPS[metric]
        values = {g: d - n for g, (n, d) in periods[index].items() if d}
        leaders = _leaders(values)
        names = [_label(g) for g in leaders]
        qualifier = ' each' if len(names) > 1 else ''
        finding = (f'The {period} had {gap:,} {stage} by {evidence.observation_cutoff}. '
                   f'The largest share came from {", ".join(names)} ({values[leaders[0]]:,} of {gap:,}{qualifier}).')
        recommendation = (f'Begin with {", ".join(names)}, accounting for {values[leaders[0]]:,} of {gap:,} {stage}{qualifier}. '
                          + CHECKS[metric])
        answer = _answer(finding, recommendation, 'segments', names)
    if metric == 'bank_health':
        health = _health(evidence, selected)
        answer['finding'] += ' ' + health['finding']
        answer['recommendations'] = health['recommendations']
    return answer


QUALITY_CHECKS = {
    'duplicate_occurrences': 'Compare repeated attempt_id values with the originating event records to establish which occurrence belongs to each attempt.',
    'missing_attempt_id': 'Trace rows with an empty attempt_id to the source event identity.',
    'missing_timestamps': 'Find the attempted_at value in the source event before assigning the row to a payment window.',
    'malformed_timestamps': 'Check the timestamp and offset in the source attempt event before assigning a comparison window.',
    'orphan_merchants': 'Compare each unmatched merchant_id with the merchant directory for the selected import.',
    'orphan_banks': 'Compare each unmatched payer_bank_id with the bank directory for the selected import.',
    'duplicate_banks': 'Reconcile repeated bank_id entries with the source bank directory before joining payment records.',
    'duplicate_merchants': 'Reconcile repeated merchant_id entries with the source merchant directory before joining payment records.',
    'invalid_status_reason': 'Compare each incompatible status and failure reason with its source attempt outcome.',
    'invalid_amount_currency': 'Check the currency and integer amount in paise against the source transaction.',
    'invalid_method': 'Verify the payment method against the selected dataset’s registered methods.',
    'invalid_completion_time': 'Recover the completion timestamp and offset from the attempt event.',
    'invalid_observation_time': 'Compare the ingestion timestamp with the ingestion receipt to establish when the attempt was observable.',
    'invalid_order_time': 'Check the order creation timestamp and offset before assigning its maturity window.',
    'invalid_attempt_number': 'Trace attempt numbers within each affected order against the source sequence.',
    'duplicate_orders': 'Reconcile repeated order_id values against the originating orders before counting eligible orders.',
    'invalid_order_identity': 'Check order_id, amount and currency against the originating order.',
    'orphan_order_attempts': 'Match each affected attempt’s order_id to the order import.',
    'orders_without_attempts': 'Check whether the source contains a completed attempt for each unlinked order.',
    'order_attribute_mismatch': 'Compare merchant, amount and currency on each affected order and its associated attempts.',
    'invalid_settlement_fields': 'Compare the obligation ID, gross amount, status and settlement timestamp to the settlement ledger.',
    'duplicate_settlements': 'Reconcile multiple obligations on the same attempt with the settlement ledger.',
    'duplicate_settlement_ids': 'Resolve repeated settlement_id values against the obligation ledger.',
    'invalid_settlement_reference': 'Reconcile each obligation’s successful attempt ID and gross amount with the originating payment.',
    'missing_obligations': 'Match successful attempts lacking obligations to the settlement ledger.',
    'invalid_due_at': 'Verify the obligation due timestamp and offset in the settlement ledger.',
    'invalid_settled_at': 'Verify the settlement timestamp and status against the payout acknowledgement.',
    'completion_order': 'Compare attempt, completion and ingestion timestamps with the source event sequence.',
    'invalid_attempt_chains': 'Trace the initial attempt and numbered retries per order for skipped numbers, duplicate successes or route changes.',
    'attempt_before_order': 'Reconcile the order creation time and earliest attempt time in the source logs.',
    'invalid_retry_sequence': 'Verify whether each retry followed a completed failure in the source order history.',
    'invalid_due_or_settled_time': 'Reconcile due and settlement times against the attempt completion time and the obligation’s due rule.',
}


def blocked_guidance(evidence, objective):
    rules = [record for record in evidence.quality if record.status == 'BLOCK']
    details = ', '.join(f'{rule.rule} ({rule.count:,})' for rule in rules)
    steps = [f'{r.rule} ({r.count:,}). ' + QUALITY_CHECKS.get(r.rule, 'Inspect the rows and field constraints behind this diagnostic.')
             for r in rules]
    steps.append('Have the data owner verify the affected source records, then rerun the quality checks before using the metric.')
    return {'finding': f'The measurement is blocked by {details}.', 'recommendations': steps, 'source': 'quality', 'leaders': []}
