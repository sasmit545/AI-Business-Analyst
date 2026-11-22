"""Trusted projections of previously verified evidence. No database or rendering access."""
from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from app.quality.policy import blocked


@dataclass
class Result:
    rows: list[dict]
    dimension: str | None = None
    measures: tuple[str, ...] = ()
    action_field: str | None = None


ATTEMPT_MEASURES = ('rate', 'attempts', 'successes', 'failed_attempts')
LIFECYCLE_MEASURES = ('rate', 'numerator', 'denominator')
DIMENSIONS = {
    'overall': 'period', 'daily': 'day', 'banks': 'payer_bank_id', 'methods': 'payment_method',
    'merchants': 'merchant_id', 'merchant_categories': 'category',
}
FILTER_FIELDS = {'payer_bank_id', 'payment_method', 'merchant_id'}


def result_catalog(evidence):
    if blocked(evidence.quality):
        return {}
    sources = {}
    attempt = evidence.request.metric == 'attempt_success'
    for name, dimension in DIMENSIONS.items():
        if name not in evidence.results:
            continue
        rows = evidence.results[name]
        if attempt:
            rows = [dict(r, failed_attempts=r['attempts'] - r['successes']) for r in rows]
        action = dimension if dimension in FILTER_FIELDS else None
        sources[name] = Result(rows, dimension, ATTEMPT_MEASURES if attempt else LIFECYCLE_MEASURES, action)
    if not attempt:
        # Ratios must be recomputed from summed numerator/denominator, including paise.
        totals = defaultdict(lambda: [0, 0])
        for row in evidence.results['segments']:
            pair = totals[row['period'], row['payer_bank_id']]
            pair[0] += row['numerator']
            pair[1] += row['denominator']
        banks = [dict(period=p, payer_bank_id=b, numerator=n, denominator=d, rate=n/d if d else None)
                 for (p, b), (n, d) in sorted(totals.items())]
        sources['banks'] = Result(banks, 'payer_bank_id', LIFECYCLE_MEASURES, 'payer_bank_id')
    for name in ('segments', 'failures', 'transactions'):
        if name in evidence.results:
            sources[name] = Result(evidence.results[name])
    if 'daily' in sources:
        summary = []
        for period in (0, 1):
            rates = [row['rate'] for row in sources['daily'].rows
                     if row['period'] == period and row['rate'] is not None]
            if rates:
                summary.append(dict(period=period, observed_days=len(rates),
                                    min_daily_rate=min(rates), median_daily_rate=median(rates),
                                    max_daily_rate=max(rates)))
        sources['daily_summary'] = Result(summary)
    joint = evidence.results.get('decomposition', {}).get('joint', {})
    if joint.get('available'):
        sources['contributions'] = Result(joint['parts'])
    return sources


def selected_rows(block, source):
    if block.period is None:
        return source.rows
    period = ('baseline', 'comparison').index(block.period)
    return [row for row in source.rows if row['period'] == period]


def describe_sources(sources):
    return {name: {k: v for k, v in {
        'rows': len(source.rows), 'dimension': source.dimension, 'measures': source.measures,
        'drilldown': source.action_field,
    }.items() if v is not None} for name, source in sources.items()}
