"""Rank measured attempt outcomes and derive the next check from the selected business objective."""
from collections import Counter
from fractions import Fraction

from app.analytics.contributions import decompose


GROUPS = {
    'reason': ('failures', ('failure_reason',)),
    'segment': ('segments', ('payer_bank_id', 'payment_method')),
    'bank': ('banks', ('payer_bank_id',)),
    'method': ('methods', ('payment_method',)),
    'merchant': ('merchants', ('merchant_id',)),
    'overall': ('overall', ()),
}
MEASURES = {'attempts':'completed attempts', 'successes':'successful attempts', 'failed_attempts':'failed attempts'}


def _result(source, finding, recommendations=(), keys=(), leaders=()):
    return {'source':source, 'finding':finding, 'recommendations':list(recommendations),
            'leaders':[dict(zip(keys, key)) for key in leaders]}


def _leaders(scores):
    if not scores:
        return []
    highest = max(scores.values())
    return sorted(key for key, value in scores.items() if value == highest)


def _name(key):
    return ' / '.join(str(part) for part in key) or 'all eligible attempts'


def _cells(results, dimension):
    """Two dictionaries of (failures, eligible attempts), keyed at the requested grain."""
    source, fields = GROUPS[dimension]
    cells = [{}, {}]
    for row in results[source]:
        period = row['period']
        key = tuple(row[field] for field in fields)
        if dimension == 'reason':
            failures, attempts = cells[period].get(key, (0, results['overall'][period]['attempts']))
            cells[period][key] = (failures + row['count'], attempts)
        else:
            cells[period][key] = (row['attempts'] - row['successes'], row['attempts'])
    if dimension == 'reason':
        # The failure partition reconciles to every failed attempt. A missing label
        # is a measured zero whenever that period's population has attempts.
        labels = cells[0].keys() | cells[1].keys()
        for period, group in enumerate(cells):
            for label in labels:
                group.setdefault(label, (0, results['overall'][period]['attempts']))
    return cells


def _missing_exposure(rows, needed):
    empty = [name for index, name in enumerate(('baseline', 'comparison'))
             if index in needed and not rows[index]['attempts']]
    if empty:
        periods = ' and '.join(empty)
        interval = 'windows have' if len(empty) == 2 else 'window has'
        return _result('overall', f'The {periods} {interval} zero completed attempts in this scope.',
                       [f'Check the {periods} dates and selected filters. If traffic was expected there, '
                        'reconcile the attempt import for that interval before comparing performance.'])


def _failure_locations(results, labels, period):
    locations = {label:Counter() for label in labels}
    for row in results['failures']:
        key = (row['failure_reason'],)
        if row['period'] == period and key in locations:
            locations[key][(row['payer_bank_id'], row['payment_method'])] += row['count']
    return locations


def _volume(results, dimension, period, measure):
    source, fields = GROUPS[dimension]
    groups = _cells(results, dimension)
    cells = groups[period]
    period_name = ('baseline', 'comparison')[period]
    if dimension == 'reason' or measure not in MEASURES:
        measure = 'failed_attempts'
    values = {key:{'failed_attempts':failed, 'successes':attempts-failed, 'attempts':attempts}[measure]
              for key, (failed, attempts) in cells.items()}
    total = sum(values.values())
    if not total:
        return _result(source, f'There were zero {MEASURES[measure]} in the {period_name} for the selected scope.')
    leaders = _leaders(values)
    amount = values[leaders[0]]
    labels = ', '.join(map(_name, leaders))
    each = ' each' if len(leaders) > 1 else ''
    finding = (f'{labels} accounted for the most {MEASURES[measure]} in the {period_name}, '
               f'{amount:,} of {total:,}{each} ({Fraction(amount, total):.2%}).')
    if dimension == 'reason':
        other = 1-period
        other_row = results['overall'][other]
        other_total = other_row['attempts']-other_row['successes']
        if other_total:
            previous_shares = [f'{_name(key)} accounted for {groups[other][key][0]:,} of {other_total:,} '
                               f'({Fraction(groups[other][key][0], other_total):.2%})' for key in leaders]
            finding += f' In the {("baseline", "comparison")[other]}, ' + ' and '.join(previous_shares) + '.'
        elif other_row['attempts']:
            finding += f' The {("baseline", "comparison")[other]} had zero failed attempts.'
        locations = _failure_locations(results, leaders, period)
        detail = []
        for label in leaders:
            top = _leaders(locations[label])
            if top:
                detail.append(f'{_name(label)} in {", ".join(map(_name, top))} '
                              f'({locations[label][top[0]]:,} occurrences{" each" if len(top) > 1 else ""})')
        checks = ['Start with ' + ' and '.join(detail) + '. Match representative failed attempt IDs to the '
                  'operational response traces for this period. If failures cluster at one processing step, '
                  'inspect that step. If several responses share the label, split the cases by response before escalation.']
    elif measure == 'failed_attempts':
        checks = [f'Compare the share of failures with the share of traffic for {labels}. '
                  'If failure share exceeds traffic share, examine the recorded reasons in that group. '
                  'If the shares track, volume helps explain its high count.']
    else:
        checks = [f'Use the period totals to compare the traffic share of {labels} across windows. '
                  'If the share shifted, examine the traffic allocation before interpreting count changes as performance changes.']
    return _result(source, finding, checks, fields, leaders)


def _deterioration(results, dimension):
    source, fields = GROUPS[dimension]
    before, after = _cells(results, dimension)
    comparable = sorted(k for k in before.keys() & after.keys() if before[k][1] and after[k][1])
    if dimension == 'reason' and not comparable:
        return _result(source, 'No failure reason was recorded in either window.')
    omitted = len(before.keys() | after.keys()) - len(comparable)
    coverage = (f' Groups with exposure in only one window were excluded ({omitted:,}).' if omitted else '')
    if not comparable:
        return _result(source, 'No observed group has eligible attempts in both windows.' + coverage,
                       ['Compare counts for groups entering or leaving the population. An estimate of rate change '
                        'requires exposure for the same group in both windows.'])
    changes = {key:Fraction(*after[key]) - Fraction(*before[key]) for key in comparable}
    leaders = _leaders(changes)
    increase = changes[leaders[0]]
    if increase <= 0:
        return _result(source, 'The failure rate held steady or fell in every comparable group.' + coverage,
                       ['Use the comparison-period failure counts to prioritize remaining workload if reducing the '
                        'number of failures is the objective.'])
    detail = []
    for key in leaders:
        baseline, comparison = before[key], after[key]
        detail.append(f'{_name(key)} ({baseline[0]:,}/{baseline[1]:,}, {Fraction(*baseline):.2%}, '
                      f'to {comparison[0]:,}/{comparison[1]:,}, {Fraction(*comparison):.2%})')
    finding = (f'The largest increase in failures per completed attempt was {100*increase:.4f} percentage points '
               f'for {", ".join(detail)}.' + coverage)
    if len(leaders) == 1:
        finding += f' One comparison outcome represents {100/after[leaders[0]][1]:.3g} pp for this group.'
    named = ', '.join(map(_name, leaders))
    if dimension == 'reason':
        recommendation = (f'Check whether the increase for {named} persists in a follow-up comparison over shorter windows '
                          'with the same filters. If it is concentrated in one interval, inspect operational traces for '
                          'that interval. If it persists, compare the affected processing stages across intervals.')
    else:
        recommendation = (f'Compare the recorded failure reasons for {named} across the same windows. '
                          'A rising reason per attempt narrows the trace review to that outcome. '
                          'If several reasons moved, compare their individual contributions before choosing an intervention.')
    return _result(source, finding, [recommendation], fields, leaders)


def _reason_contribution(results):
    before, after = _cells(results, 'reason')
    changes = {key:Fraction(*before[key])-Fraction(*after[key]) for key in before}
    change = sum(changes.values())
    if not change:
        return _result('failures', 'The recorded reason rates sum to zero net change in overall success.',
                       ['Compare the counts and rates for each label when prioritizing remaining failures.'])
    direction = 1 if change > 0 else -1
    leaders = _leaders({key:direction*value for key, value in changes.items()})
    named = ', '.join(map(_name, leaders))
    detail = [f'{_name(k)} ({before[k][0]:,}/{before[k][1]:,} to {after[k][0]:,}/{after[k][1]:,} attempts)'
              for k in leaders]
    each = ' each' if len(leaders) > 1 else ''
    groups = {(row['payer_bank_id'], row['payment_method']) for row in results['segments'] if row['attempts']}
    if len(groups) == 1:
        bank, method = next(iter(groups))
        check = (f'Track {named} per completed attempt for {bank} / {method} in the next comparable window. '
                 'If the shift reverses, compare response traces from the two windows to identify which outcomes changed.')
    else:
        check = (f'Compare the counts for {named} by bank and payment method in the recorded failure breakdown. '
                 'If one group accounts for the movement, compare that group’s reason rate in a filtered analysis.')
    return _result('failures', f'Across all recorded failure reasons, overall success changed by {100*change:+.4f} pp. '
                   f'The largest contribution in that direction came from {", ".join(detail)}, '
                   f'{100*changes[leaders[0]]:+.4f} pp{each}.',
                   [check],
                   GROUPS['reason'][1], leaders)


def _contribution(results, dimension):
    if dimension == 'reason':
        return _reason_contribution(results)
    dimension = dimension if dimension in ('bank','method','segment','merchant') else 'segment'
    source, fields = GROUPS[dimension]
    if dimension == 'merchant':
        decomposition = decompose(results[source], fields)
        reference = source
    else:
        partition = {'bank':'bank', 'method':'method', 'segment':'joint'}[dimension]
        decomposition = results['decomposition'][partition]
        reference = 'decomposition'
    if not decomposition['available']:
        return _result(reference, 'The two windows lack a common, complete partition for this rate decomposition.',
                       ['Compare traffic in groups that appear or disappear. Use periods with exposure in the same '
                        'groups to distinguish traffic shifts from changes in their success rates.'])
    before, after = _cells(results, dimension)
    left, right = [r['attempts'] for r in results['overall']]
    # Rank the signed, symmetric contributions using the underlying integer counts
    # to preserve ties. The same verified partition supplies the published totals.
    within, shares, mix = {}, {}, {}
    for key, (failed, attempts) in before.items():
        other_failed, other_attempts = after[key]
        w0, w1 = Fraction(attempts, left), Fraction(other_attempts, right)
        r0, r1 = 1-Fraction(failed, attempts), 1-Fraction(other_failed, other_attempts)
        shares[key] = w1 - w0
        mix[key] = (w1 - w0) * (r0 + r1) / 2
        within[key] = (w1 + w0) * (r1 - r0) / 2
    mix_total, within_total = sum(mix.values()), sum(within.values())
    change = mix_total + within_total
    finding = (f'The {dimension} partition accounts for {100*change:+.4f} percentage points of success-rate change. '
               f'Traffic mix contributed {100*mix_total:+.4f} pp and within-group rates {100*within_total:+.4f} pp.')
    if not change:
        if not any(shares.values()) and not any(within.values()):
            return _result(reference, finding, ['The measured traffic shares and group success rates were stable. '
                                                       'Use failure volume to prioritize remaining workload.'])
        return _result(reference, finding, ['Compare the positive and negative group contributions in the '
                                                   'decomposition to identify movements that offset one another.'])
    direction = 1 if change > 0 else -1
    if direction*mix_total > direction*within_total:
        # Center both periods on one success rate. The shares sum to zero, so this
        # preserves the mix total and distinguishes adverse shifts from offsets.
        benchmark = sum(Fraction(row['successes'], row['attempts']) for row in results['overall']) / 2
        effects = {key:direction * (mix[key] - shares[key] * benchmark) for key in shares}
        growing = {key:effect for key, effect in effects.items() if effect > 0 and shares[key] > 0}
        leaders = _leaders(growing or effects)
        share_details = [f'{_name(k)} ({Fraction(before[k][1], left):.2%} to {Fraction(after[k][1], right):.2%} of attempts, '
                         f'group success {1 - Fraction(*before[k]):.2%} to {1 - Fraction(*after[k]):.2%})'
                         for k in leaders]
        finding += f' A traffic shift in the direction of the overall change was {", ".join(share_details)}.'
        check = (f'Check the traffic allocation for {", ".join(map(_name, leaders))}. '
                 'Compare the verified group rates to see how the changed shares moved overall success. '
                 'Use operational allocation records to establish why the traffic shifted.')
    else:
        leaders = _leaders({key:direction*value for key, value in within.items()})
        named = ', '.join(map(_name, leaders))
        each = ' each' if len(leaders) > 1 else ''
        finding += f' {named} contributed {100*within[leaders[0]]:+.4f} pp{each} through changes in group success.'
        check = (f'Compare failures per completed attempt for {named} across both windows. '
                 'Use the recorded reasons there to identify which outcomes moved in the same direction as the '
                 'measured contribution before inspecting operational traces.')
        if dimension != 'merchant':
            # Attribute movement within the selected group(s) before advising
            # an operational check. Both periods retain their own exposures.
            totals = [sum(cells[k][1] for k in leaders) for cells in (before, after)]
            counts = [Counter(), Counter()]
            selected = set(leaders)
            for row in results['failures']:
                if tuple(row[f] for f in fields) in selected:
                    counts[row['period']][row['failure_reason']] += row['count']
            deltas = {reason:direction*(Fraction(counts[0][reason], totals[0])-Fraction(counts[1][reason], totals[1]))
                      for reason in counts[0].keys() | counts[1].keys()}
            reasons = _leaders(deltas)
            if reasons and deltas[reasons[0]] > 0:
                names = ', '.join(reasons)
                change_text = ', '.join(f'{label} ({counts[0][label]:,}/{totals[0]:,} to '
                                        f'{counts[1][label]:,}/{totals[1]:,})' for label in reasons)
                check = (f'Start with {change_text} in {named}. Their failure rates made the largest contribution '
                         'in the direction of the observed change in group success. '
                         f'Ask payment operations to compare the processing stages attached to {names} in both windows. '
                         'A concentration at one stage narrows trace review to that stage.')
    return _result(reference, finding, [check], fields, leaders)


def _trend(results, period, measure):
    rows = [row for row in results['daily'] if row['period'] == period and row['attempts']]
    period_name = ('baseline', 'comparison')[period]
    if not rows:
        return _result('daily', f'The {period_name} has no daily observations with completed attempts.')
    days = {}
    for row in rows:
        n, s = row['attempts'], row['successes']
        if measure in MEASURES:
            value = {'attempts':n, 'successes':s, 'failed_attempts':n-s}[measure]
        else:
            value = Fraction(s, n)
        days[(str(row['day']),)] = value
    sorted_days = sorted(days)
    first, last = sorted_days[0], sorted_days[-1]
    if measure in MEASURES:
        values = [f'{days[d]:,}' for d in (first, last)]
        label = MEASURES[measure]
    else:
        values = [f'{days[d]:.2%}' for d in (first, last)]
        label = 'payment success'
    if first == last:
        return _result('daily', f'The only observed {period_name} day was {_name(first)}, with {label} of {values[0]}.',
                       ['A daily trend needs a second observed date. Extend the window if the decision depends on direction.'],
                       ('day',), [first])
    if measure == 'failed_attempts':
        extremes, extreme = _leaders(days), 'highest'
    else:
        extremes, extreme = _leaders({k:-v for k, v in days.items()}), 'lowest'
    dates = ', '.join(map(_name, extremes))
    extreme_value = f'{days[extremes[0]]:,}' if measure in MEASURES else f'{days[extremes[0]]:.2%}'
    return _result('daily', f'Across {len(days)} observed {period_name} dates, daily {label} went from {values[0]} '
                   f'on {_name(first)} to {values[1]} on {_name(last)}. The {extreme} value was {extreme_value} on {dates}.',
                   [f'Compare daily traffic for {dates} with neighboring observed dates. If the volume is comparable, '
                    'use the same filters to compare outcomes across those days.'],
                   ('day',), extremes)


def attempt_guidance(evidence, objective):
    """Use only the caller's verified, quality-approved attempt evidence."""
    results = evidence.results
    kind, dimension = objective.kind, objective.dimension
    period = 0 if objective.period == 'baseline' else 1
    measure = objective.measure
    if dimension == 'overall' and (kind == 'count' or (kind == 'volume' and measure in ('attempts','successes'))):
        field = measure if measure in MEASURES else 'attempts'
        counts = [dict(row, failed_attempts=row['attempts']-row['successes'])[field] for row in results['overall']]
        return _result('overall', f'{MEASURES[field].capitalize()} totaled {counts[0]:,} in the baseline and '
                       f'{counts[1]:,} in the comparison.')
    needed = (period,) if kind in ('volume', 'count', 'trend') else (0, 1)
    missing = _missing_exposure(results['overall'], needed)
    if missing:
        return missing
    if dimension == 'merchant' and 'merchants' not in results:
        return _result('overall', 'The current result does not contain a merchant breakdown.',
                       ['Request a merchant breakdown for the same dates and filters to rank the merchants.'])
    if kind in ('volume', 'count'):
        return _volume(results, 'reason' if dimension == 'overall' else dimension, period, measure)
    if kind == 'trend':
        return _trend(results, period, measure)
    if kind == 'contribution':
        return _contribution(results, dimension)
    if kind == 'deterioration':
        return _deterioration(results, 'segment' if dimension == 'overall' else dimension)

    # A general "what should I do?" weighs an overall decline first. If overall
    # success improved, an individual outcome can still merit investigation.
    before, after = results['overall']
    if Fraction(after['successes'], after['attempts']) < Fraction(before['successes'], before['attempts']):
        return _contribution(results, dimension)
    deterioration = _deterioration(results, 'reason')
    if deterioration['leaders']:
        return deterioration
    return _volume(results, 'reason', period, 'failed_attempts')
