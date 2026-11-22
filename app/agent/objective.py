"""The business question controls presentation independently of its SQL measurement."""
import re
from typing import Literal

from app.contracts import StrictModel


class Objective(StrictModel):
    kind: Literal['summary', 'volume', 'deterioration', 'contribution', 'next_steps', 'trend', 'count'] = 'summary'
    dimension: Literal['overall', 'reason', 'segment', 'bank', 'method', 'merchant'] = 'overall'
    period: Literal['baseline', 'comparison'] = 'comparison'
    measure: Literal['rate', 'attempts', 'successes', 'failed_attempts', 'numerator', 'denominator'] = 'rate'
    joint_detail: Literal['reason_by_day', 'reason_by_health'] | None = None


def inferred_objective(question):
    """Conservative fallback for typed requests and planners that omit objective."""
    q = question.casefold()
    def has(pattern):
        return bool(re.search(pattern, q))

    dimension = 'overall'
    for pattern, name in [(r'failure (?:reasons?|labels?|types?)|reasons? for fail|which reason|timeouts?', 'reason'),
                          (r'\bbanks?\s*(?:(?:and|by|with|/|[-×])\s*)?(?:payment[ -])?methods?\b|'
                           r'\b(?:payment[ -])?methods?\s*(?:and|by|/|[-×])\s*banks?\b|bank.method pair|\bsegments?\b', 'segment'),
                          (r'(?:which|by|each|across|rank) (?:payer )?banks?', 'bank'),
                          (r'(?:which|by|each|across|rank) (?:payment )?methods?', 'method'),
                          (r'(?:which|by|each|across|rank) merchants?', 'merchant')]:
        if has(pattern):
            dimension = name
            break
    period = 'baseline' if has(r'(?:in|during|for) (?:the )?(?:baseline|first period)\b') and not has(r'comparison period|second period') else 'comparison'
    measure = 'rate'
    if has(r'failed attempts?|number of failures|most failures|failure counts?|failed payments?|how many .*fail'):
        measure = 'failed_attempts'
    elif has(r'successful attempts?|how many .*succeed'):
        measure = 'successes'
    elif has(r'completed attempts?|how many attempts|attempt volume'):
        measure = 'attempts'
    elif has(r'how many .*eligible|(?:eligible|due) (?:orders|obligations)|\bdenominator\b') and not has(r'\bnumerator\b'):
        measure = 'denominator'
    elif has(r'(?:how many|number of).*?(?:paid|recovered|settled)|\bnumerator\b'):
        measure = 'numerator'
    if has(r'due.*backlog|outstanding|most (?:fail|common|frequent)|most .*fail|largest .*count|highest .*count|(?:largest|highest)[ -]volume|failure counts? by'):
        kind = 'volume'
    elif has(r'worsen|deteriorat|got worse|largest (?:drop|decline|increase in .*rate)|steepest|fell (?:the )?most'):
        kind = 'deterioration'
    elif has(r'contribut|driver|driv(?:es|ing)|drove|traffic mix|why did|what explains'):
        kind = 'contribution'
    elif has(r'how many|number of|total (?:completed|successful|failed|attempts)'):
        kind = 'count'
    elif has(r'\btrend\b|by day|day.by.day|\bdaily\b'):
        kind = 'trend'
    else:
        kind = 'summary'
    joint_detail = None
    if dimension == 'reason' and has(r'align|coincid|correlat') and has(r'latency|availability|health'):
        joint_detail = 'reason_by_health'
    elif dimension == 'reason' and has(
        r'\bdaily\s+(?:(?:bank|recorded)\s+)?(?:timeouts?|failures?(?:\s+(?:reasons?|labels?))?)\b|'
        r'\b(?:timeouts?|failure (?:counts?|reasons?|labels?|rates?))\s+(?:(?:broken down|grouped)\s+)?(?:by|per|each) day\b|'
        r'\b(?:by day and (?:failure )?reason|by (?:failure )?reason and day)\b'
    ):
        joint_detail = 'reason_by_day'
    return Objective(kind=kind, dimension=dimension, period=period, measure=measure, joint_detail=joint_detail)


def ambiguous_priority(question):
    q = question.casefold()
    return (bool(re.search(r'\b(?:by impact|biggest impact|greatest impact|largest impact)\b', q))
            and not re.search(r'\b(?:count|volume|amount|rate|change|contribution|percentage|paise)\b', q))


def continuation(question):
    """Only a complete scope-free request may bypass a fresh planning turn."""
    q = ' '.join(re.findall(r"[\w']+", question.casefold())).removeprefix('please ').strip()
    action = (r"(?:what (?:steps?|actions?) (?:should|can) (?:i|we) take(?: (?:next|to (?:address|fix|investigate) (?:this|it)))?"
              r"|what should (?:i|we) (?:do|check|investigate)(?: (?:about (?:this|it)|first|next|now))?"
              r"|what (?:are|were) (?:the |your )?(?:recommended (?:actions|steps)|recommendations|next steps)"
              r"|(?:show |give me )?(?:recommendations|recommended actions|next steps)|what next)")
    if re.fullmatch(action, q):
        return 'action'
    if re.fullmatch(r'why|why (?:is|was) that|(?:can you )?explain (?:this|that|the result|the finding)(?: further)?', q):
        return 'explanation'
    return None
