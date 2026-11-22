"""Only trusted templates publish factual sentences. Model prose is never rendered."""
from fractions import Fraction
import hashlib
import json
import re

from app.agent.objective import Objective
from app.context.catalog import catalog
from app.evidence.verify import verify_evidence, verify_claim
from app.quality.policy import blocked


def render_claim(claim, evidence):
    value = verify_claim(claim, evidence)
    rendered = f'{100*value:.4f}%' if claim.unit == 'fraction' else f'{int(value):,}'
    return f'{claim.table}, row {claim.row + 1}, {claim.field}: {rendered}.'


def publication_narrative(evidence, layout):
    if layout is not None and layout.evidence_id != evidence.id:
        raise ValueError('Publication belongs to another result')
    objective = (layout.objective if layout else None) or Objective()
    content = narrative(evidence, objective)
    guidance = content['guidance']
    if layout and layout.finding_ref and layout.finding_ref != guidance['reference']:
        raise ValueError('The saved finding does not resolve to this evidence')
    if not blocked(evidence.quality):
        if layout and (layout.response == 'action' or objective.kind == 'next_steps'):
            content['answer'] = content['recommendations'][0]
        elif layout and (layout.response == 'explanation' or objective.joint_detail or
                         objective.kind in ('volume', 'deterioration', 'contribution', 'next_steps') or
                         (objective.kind == 'trend' and not layout.headline_measure)):
            content['answer'] = guidance['finding']
        elif objective.kind == 'count' and not (layout and layout.headline_measure):
            content['answer'] = guidance['finding']
        else:
            content['answer'] = publication_headline(evidence, layout, content['answer'])
    return content


def measure_label(metric, field):
    if metric == 'attempt_success':
        return {'rate':'Payment success rate', 'attempts':'Completed attempts', 'successes':'Successful attempts',
                'failed_attempts':'Failed attempts'}[field]
    from app.analytics.lifecycle import DEFINITIONS
    rate, numerator, denominator = DEFINITIONS[metric]
    name = {'rate':rate, 'numerator':numerator, 'denominator':denominator}[field]
    return name[:1].upper() + name[1:]


def publication_headline(evidence, layout, verified_answer):
    field = layout.headline_measure if layout else None
    if field is None:
        return verified_answer
    from app.ui_specs.results import result_catalog
    values = [r[field] for r in result_catalog(evidence)['overall'].rows]
    title = measure_label(evidence.request.metric, field)
    formatted = ['unavailable' if v is None else f'{100*v:.4f}%' if field == 'rate' else f'{v:,}' for v in values]
    return f'{title}: {formatted[0]} in the baseline and {formatted[1]} in the comparison.'


def insight_sentences(evidence, source):
    """Resolve only the verified result referenced by an insight block."""
    if source == 'contributions':
        parts = evidence.results['decomposition']['joint']['parts']
        part = max(parts, key=lambda row: abs(row['within']))
        return [f"Largest absolute within-segment contribution: {part['payer_bank_id']} / "
                f"{part['payment_method']}, {100*part['within']:+.4f} percentage points."]
    if source != 'overall':
        raise ValueError('Unknown insight source')
    sentences = []
    for row in evidence.results['overall']:
        n = row.get('numerator', row.get('successes'))
        d = row.get('denominator', row.get('attempts'))
        rate = 'unavailable' if row['rate'] is None else f"{100*row['rate']:.4f}%"
        period = ('Baseline','Comparison')[row['period']]
        sentences.append(f'{period}: {n:,} / {d:,}. Rate: {rate}.')
    return sentences


def conversion_drop_finding(segments):
    periods = [{}, {}]
    for row in segments:
        bank, method = row['payer_bank_id'], row['payment_method']
        if bank and method and row['denominator']:
            periods[row['period']][bank, method] = Fraction(row['numerator'], row['denominator'])
    baseline, comparison = periods
    changes = {pair: comparison[pair] - baseline[pair] for pair in baseline.keys() & comparison.keys()}
    if not changes:
        return 'No bank and payment method combination had eligible orders in both periods.'
    lowest = min(changes.values())
    if lowest >= 0:
        return 'Conversion held steady or rose for every bank and payment method with eligible orders in both periods.'
    leaders = [f'{bank} / {method} ({baseline[bank, method]:.4%} to {comparison[bank, method]:.4%})'
               for bank, method in sorted(changes) if changes[bank, method] == lowest]
    return f'Largest conversion drop: {", ".join(leaders)}, down {-100 * lowest:.4f} percentage points.'


def _rate_confidence(evidence):
    baseline, comparison = evidence.results['overall']
    empty = [name for name, row in (('baseline', baseline), ('comparison', comparison)) if row['rate'] is None]
    if empty:
        periods = 'both periods' if len(empty) == 2 else f'the {empty[0]} period'
        return f'The eligible denominator is zero in {periods}. A rate change requires observations in both periods.'
    if evidence.request.metric == 'settlement_amount':
        return ('The rate measures the share of due gross paise settled by the cutoff. '
                'A large obligation carries more weight than a small one.')
    denominator = 'attempts' if evidence.request.metric == 'attempt_success' else 'denominator'
    return ('These rates cover the eligible records in each observed period. With denominators fixed, '
            'changing one outcome would move the rate by about '
            f'{100 / baseline[denominator]:.3g} pp in the baseline or '
            f'{100 / comparison[denominator]:.3g} pp in the comparison (pp = percentage points).')


def narrative(evidence, objective=None):
    from app.evidence.attempt_guidance import attempt_guidance
    from app.evidence.lifecycle_guidance import blocked_guidance, lifecycle_guidance
    verify_evidence(evidence)
    objective = objective or Objective()
    warning_messages = {
        'unusable_health_rows': 'Bank-health rows unusable across the dataset',
        'duplicate_health_rows': 'Extra occurrences of repeated bank-health rows across the dataset',
        'unmatched_health_attempts': 'Attempts in the selected periods and filters without usable bank health',
    }
    warnings = [f"{warning_messages.get(q.rule, q.rule.replace('_', ' ').capitalize())} — {q.count:,}."
                for q in evidence.quality if q.status == 'WARN']
    if blocked(evidence.quality):
        details = ', '.join(f'{q.rule}: {q.count}' for q in evidence.quality if q.status == 'BLOCK')
        content = {'answer': 'Certified metrics blocked by data quality.', 'facts': [details],
                'confidence': 'The reported counts measure data defects. The affected records prevent a reliable rate comparison.',
                'quality_warnings': warnings, 'hypotheses': [],
                'caveats': ['The quality check covers the entire selected population, before filtering.']}
        guidance = blocked_guidance(evidence, objective)
    else:
        content = _measured_findings(evidence)
        content['confidence'] = _rate_confidence(evidence)
        if objective.joint_detail:
            daily = objective.joint_detail == 'reason_by_day'
            missing = 'daily counts for each failure reason' if daily else 'individual failed attempts joined to their bank-health observations'
            check = ('Group failures by local day and reason, and count all eligible attempts on each day to distinguish a spike from higher traffic.'
                     if daily else 'Match failed attempt times to their bank, payment method and five-minute health bucket. Compare coverage and latency with successful attempts before attributing a cause.')
            guidance = {'source':'overall', 'finding':f'This result does not measure {missing}.',
                        'recommendations':[f'Additional data needed: {check}']}
        else:
            guide = attempt_guidance if evidence.request.metric == 'attempt_success' else lifecycle_guidance
            guidance = guide(evidence, objective)
        if not guidance['recommendations']:
            # A count alone still has a meaningful scope-preserving next check.
            before, after = evidence.results['overall']
            if evidence.request.metric == 'attempt_success':
                guidance['recommendations'] = [
                    f"Compare failures per completed attempt for the same filters. The periods had {before['attempts']:,} "
                    f"and {after['attempts']:,} attempts. If that rate rose, inspect the reasons contributing to the rise."
                ]
            else:
                guidance['recommendations'] = ['Compare the numerator with the eligible cohort at the same cutoff before prioritizing a segment.']
    if guidance['source'] != 'quality' and guidance['source'] not in evidence.results:
        raise ValueError('Finding references an unavailable result')
    # Presentation wording can evolve without invalidating a saved evidence selection.
    identity = ['guidance-v1', evidence.id, evidence.checksum, objective.model_dump(),
                guidance['source'], guidance.get('leaders', [])]
    reference = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    content['guidance'] = {**guidance, 'evidence_id':evidence.id, 'reference':reference}
    content['recommendations'] = guidance['recommendations']
    if guidance['finding'] and guidance['finding'] not in content['facts']:
        content['facts'].append(guidance['finding'])
    request = evidence.request
    definition = catalog(evidence.scope.scenario)['metrics'][request.metric]
    # Only report tables actually referenced by the registered analytical SQL.
    tables = sorted({name for query in evidence.queries for name in
                     re.findall(re.escape(evidence.scope.scenario) + r'\.([a-z][a-z_0-9]*)\b', query.sql)})
    content['analysis_plan'] = {'objective':objective.model_dump(exclude_none=True), 'metric':request.metric,
                                'dataset':evidence.scope.scenario, 'grain':definition['grain'],
                                'time_field':definition['time_field'], 'tables':tables,
                                'numerator':definition['numerator'], 'denominator':definition['denominator'],
                                'baseline':request.baseline.model_dump(mode='json'),
                                'comparison':request.comparison.model_dump(mode='json'),
                                'filters':request.filters.model_dump(exclude_none=True),
                                'cutoff':evidence.observation_cutoff}
    content['quality_warnings'] = warnings
    return content


def _measured_findings(evidence):
    if evidence.request.metric != 'attempt_success':
        from app.analytics.lifecycle import DEFINITIONS
        title,numerator,denominator=DEFINITIONS[evidence.request.metric]
        facts=[]
        for label,row in zip(('Baseline','Comparison'),evidence.results['overall']):
            rate=f" = {100*row['rate']:.4f}%" if row['rate'] is not None else '; rate unavailable'
            facts.append(f"{label}: {row['numerator']:,} {numerator} / {row['denominator']:,} {denominator}{rate}.")
            if row['excluded']:
                facts.append(f"{label}: {row['excluded']:,} {'not-yet-due obligations' if evidence.request.metric.startswith('settlement_') else 'immature orders'} excluded from certification.")
            if evidence.request.metric=='bank_health':
                facts.append(f"{label}: {row.get('unmatched',0):,} attempts lack a usable aligned health observation.")
            if evidence.request.metric.startswith('settlement_'):
                unit='paise' if evidence.request.metric=='settlement_amount' else 'obligations'
                facts.append(f"{label}: due backlog is {row['denominator']-row['numerator']:,} {unit}.")
        a,b=evidence.results['overall']
        answer=title+': comparison unavailable because a denominator is empty.'
        if a['rate'] is not None and b['rate'] is not None:
            answer=f"{title}: {100*(b['rate']-a['rate']):+.4f} percentage points."
        content = {'answer':answer,'facts':facts,
            'hypotheses':['Aligned health is observational; correlation does not establish a cause.'] if evidence.request.metric=='bank_health' else [],
            'caveats':[f'Denominator: {denominator}.',f'Observation cutoff: {evidence.observation_cutoff}.',
                'Order and retry cohorts use creation dates; settlement and health cohorts use attempt dates.',
                'Bank/method order filters use the observed first attempt; immature orders are excluded.',
                'Telemetry summaries are attempt-weighted bucket observations, not an overall latency percentile.']}
        if evidence.request.metric == 'order_conversion':
            content['segment_finding'] = conversion_drop_finding(evidence.results['segments'])
        return content
    a, b = evidence.results['overall']
    facts = [f"{label}: {row['successes']:,} successful attempts / {row['attempts']:,} completed attempts" + (f" = {100*row['rate']:.4f}%." if row['rate'] is not None else '; rate unavailable.') for label, row in [('Baseline', a), ('Comparison', b)]]
    answer = 'Comparison unavailable because a window has no attempts.'
    if a['rate'] is not None and b['rate'] is not None:
        delta = 100*(b['rate']-a['rate'])
        answer = f"Attempt success {'fell' if delta < -1e-8 else 'rose' if delta > 1e-8 else 'was unchanged'}: {delta:+.4f} percentage points."
    for name in ('method','joint'):
        dec = evidence.results['decomposition'][name]
        if dec['available']:
            facts.append(f"{name.capitalize()} partition: mix contribution {100*dec['mix']:+.4f} pp; within-segment contribution {100*dec['within']:+.4f} pp.")
            if name == 'joint':
                worst = min(dec['parts'], key=lambda p:p['within'])
                if worst['within'] < -1e-10:
                    facts.append(f"Largest negative within-segment contribution: {worst['payer_bank_id']} / {worst['payment_method']}, {100*worst['within']:+.4f} pp.")
        else:
            facts.append(f'{name.capitalize()} decomposition unavailable: {dec["reason"]}.')
    if evidence.request.detail == 'transactions':
        rows = evidence.results['transactions']
        answer = f'{len(rows)} matching attempts shown, newest first (limit 50).'
        if rows:
            facts.insert(0, f"Latest matching attempt: {rows[0]['attempt_id']}, {rows[0]['status']}, {rows[0]['attempted_at']}.")
    if evidence.request.detail in ('merchant_categories', 'merchants'):
        key = 'category' if evidence.request.detail == 'merchant_categories' else 'merchant_id'
        for i, period in enumerate(('Baseline','Comparison')):
            rows = [r for r in evidence.results[evidence.request.detail] if r['period'] == i and r['rate'] is not None]
            if rows:
                row = min(rows, key=lambda r: (r['rate'], r[key]))
                facts.append(f"{period}: {row[key]} recorded {row['successes']:,}/{row['attempts']:,} "
                             f"successful attempts ({100*row['rate']:.4f}%), the lowest observed rate in this breakdown.")
    return {'answer': answer, 'facts': facts,
            'hypotheses': ['Failure labels identify observations to investigate; they do not establish an infrastructure root cause.'],
            'caveats': ['Denominator: all completed attempts in each explicit window and selected filters.',
                        'Attempt success does not measure order conversion or settlement completion.',
                        'Mix and within effects use symmetric midpoint weights; do not sum overlapping partitions.']}
