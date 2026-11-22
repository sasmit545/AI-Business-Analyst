from datetime import time, timedelta
from html import escape
import re

import plotly.graph_objects as go
import streamlit as st

from app.context.banks import BankLookupError, matching_bank_ids, resolve_bank_id
from app.contracts import Evidence
from app.evidence.render_claims import publication_narrative
from app.evidence.verify import verify_evidence
from app.quality.policy import blocked
from app.ui_specs.validate import read_layout
from app.ui_specs.results import result_catalog
from app.ui_specs.models import Block
from app.frontend.blocks import COLORS, label, render_chart, render_layout, scale_value_axis


def chart(rows, x, y, kind):
    labels = [(['Baseline','Comparison'][row[x]] if x == 'period' else escape(str(row[x]))) for row in rows]
    values = [row[y] for row in rows]
    trace = go.Bar(x=labels,y=values,marker_color=COLORS[0]) if kind=='bar' else go.Scatter(x=labels,y=values,mode='lines+markers',line_color=COLORS[0])
    figure = go.Figure(trace)
    figure.update_layout(height=350,margin=dict(l=20,r=20,t=20,b=30),
                         paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',xaxis_title=x,yaxis_title=y)
    scale_value_axis(figure, y, values, fit_values=kind=='line')
    return figure


def followup_filters(text, evidence, banks=None):
    """Parse a complete narrowing request against the observed bank and method labels."""
    words = re.sub(r'^(?:(?:show(?: me)?|filter(?: to)?|only)\s+)+', '', text.strip(), flags=re.I)
    words = re.sub(r'\s+only$', '', words, flags=re.I).strip()
    old = evidence.request.filters
    segments = evidence.results['segments']
    if banks is None:
        banks = {r['payer_bank_id']:r.get('bank_name') or r['payer_bank_id'] for r in segments if r['payer_bank_id']}
    pairs = {(r['payer_bank_id'], r['payment_method']) for r in segments}
    methods = {method for _, method in pairs if method}
    merchants = {}
    for source in ('merchants', 'transactions'):
        for row in evidence.results.get(source, []):
            merchant = row['merchant_id']
            merchants[merchant.casefold()] = merchant
    if words.casefold() in merchants:
        filters = old.model_copy(update={'merchant_id':merchants[words.casefold()]})
    elif words.upper() in methods:
        filters = old.model_copy(update={'payment_method':words.upper()})
    else:
        method = old.payment_method
        if not matching_bank_ids(words, banks):
            for candidate in methods:
                # Accept the method on either side while preserving the exact bank ID.
                token = re.escape(candidate)
                match = re.fullmatch(rf'{token}[\s_,/]+(.+)|(.+?)[\s_,/]+{token}', words, re.I)
                if match:
                    words = match[1] or match[2]
                    method = candidate
                    break
        bank = resolve_bank_id(words, banks)
        if not any(b == bank and (method is None or method == m) for b, m in pairs):
            raise ValueError('Choose a bank and payment method shown in this result.')
        filters = old.model_copy(update={'payer_bank_id':bank, 'payment_method':method})
    if filters == old:
        raise ValueError('Choose a narrower bank or payment method.')
    return filters


def bank_chart_selection(evidence):
    if evidence.request.filters.payer_bank_id:
        return None
    source = result_catalog(evidence)['banks']
    block = Block(kind='bar', source='banks', measure='rate', drilldown=True)
    index = render_chart(block, source, evidence, 'bank-selection-'+evidence.id, True)
    if index is not None:
        return followup_filters(source.rows[index]['payer_bank_id'], evidence)


def window_label(window):
    if (window.start.time() == window.end.time() == time.min
            and window.start.utcoffset() == window.end.utcoffset()):
        last = window.end.date() - timedelta(days=1)
        first = window.start.date()
        if first == last:
            return f'{first:%d %b %Y}'
        start = first.strftime('%d' if (first.year, first.month) == (last.year, last.month) else '%d %b %Y')
        return f'{start}–{last:%d %b %Y}'
    return f'{window.start.isoformat()} to {window.end.isoformat()} (exclusive)'


def render_conversion_summary(evidence, as_text):
    rows = []
    windows = (evidence.request.baseline, evidence.request.comparison)
    for result in evidence.results['overall']:
        index = result['period']
        period = window_label(windows[index])
        name = ('Baseline', 'Comparison')[index]
        paid = f"{result['numerator']:,}"
        eligible = f"{result['denominator']:,}"
        rate = 'Unavailable' if result['rate'] is None else f"{result['rate']:.4%}"
        if as_text:
            st.text(f'{name} ({period}): {paid} of {eligible} eligible orders paid within 24 hours. Conversion: {rate}.')
        else:
            rows.append({'Period': name, 'Orders created': period, 'Paid within 24 hours': paid,
                         'Eligible orders': eligible, 'Conversion': rate})
    if rows:
        st.table(rows, hide_index=True)


def render_evidence(payload, presentation='Agent layout', dashboard_payload=None, interactive=False, banks=None):
    evidence = Evidence.model_validate(payload)
    verify_evidence(evidence)
    layout = read_layout(dashboard_payload, evidence)
    action = None
    request = evidence.request
    lifecycle=request.metric!='attempt_success'
    if lifecycle:
        from app.analytics.lifecycle import DEFINITIONS
        title, numerator, denominator=DEFINITIONS[request.metric]
    else:
        title,numerator,denominator='attempt success','successful attempts','all completed attempts in each window and selected filters'
    content = publication_narrative(evidence, layout)
    quality_blocked = blocked(evidence.quality)
    if quality_blocked:
        st.error(content['answer'])
    else:
        st.subheader(content['answer'])
        if request.metric == 'order_conversion':
            render_conversion_summary(evidence, as_text=not layout.blocks)
            st.text(content['segment_finding'])
    if request.metric != 'order_conversion' or quality_blocked:
        st.caption(f'Baseline: {window_label(request.baseline)}   ·   Comparison: {window_label(request.comparison)}')
    filters = request.filters.model_dump(exclude_none=True)
    scope_label = 'Dataset: ' + evidence.scope.scenario
    filter_label = ', '.join(f'{label(key)} = {value}' for key, value in filters.items()) or 'All'
    st.caption(f'{scope_label} · Filters: {filter_label}')
    if interactive and not quality_blocked and banks is not None and request.filters.payer_bank_id is not None:
        try:
            bank_id = resolve_bank_id(request.filters.payer_bank_id, banks)
        except BankLookupError as exc:
            st.info(f'The saved bank filter needs clarification. {exc}')
        else:
            if bank_id != request.filters.payer_bank_id:
                st.info(f'This saved query used the bank label "{request.filters.payer_bank_id}". '
                        f'Run the comparison again with the stored bank ID {bank_id}.')
                if st.button(f'Recalculate for {bank_id}', key='correct-bank-'+evidence.id):
                    return {'action':'filter', 'filters':{'payer_bank_id':bank_id}}
    for warning in content['quality_warnings']:
        st.warning(warning)
    if not quality_blocked:
        if layout.fallback:
            st.caption('The visual layout is unavailable. You can still read the verified findings.')
        try:
            action = render_layout(layout, result_catalog(evidence), evidence, presentation, interactive)
        except Exception:
            # Isolate presentation failures from the verified narrative and provenance.
            st.warning('A component could not be displayed. The measured findings are available below.')
    with st.expander('Measured findings and interpretation', expanded=blocked(evidence.quality) or layout.fallback):
        st.subheader('Observed facts')
        for sentence in content['facts']:
            st.text(sentence)
        st.subheader('Confidence and interpretation limits')
        st.text(content['confidence'])
        for sentence in content['hypotheses']:
            st.text(sentence)
        st.subheader('Recommendations')
        for sentence in content['recommendations']:
            st.text(sentence)
    with st.expander('SQL, quality and provenance', key='provenance-'+evidence.id, on_change='rerun') as provenance:
        st.text('Evidence ID: '+evidence.id)
        if not provenance.open:
            return action
        plan = content['analysis_plan']
        st.caption(f"Analysis plan · {plan['objective']['kind'].replace('_', ' ')} by {plan['objective']['dimension']} · "
                   f"{plan['grain']} grain using {plan['time_field']}")
        if plan['tables']:
            st.caption('Queried tables: ' + ', '.join(plan['tables']))
        st.caption('Finding evidence: ' + content['guidance']['source'])
        st.caption('Selected dataset: '+evidence.scope.scenario+' · Metric: '+title)
        for name, window in (('Baseline', request.baseline), ('Comparison', request.comparison)):
            st.text(f'{name}: {window.start.isoformat()} to {window.end.isoformat()} (exclusive)')
        st.caption('Numerator: '+numerator+' · Denominator: '+denominator)
        if 'daily' in evidence.results:
            st.caption('Daily grouping timezone: Asia/Kolkata')
        if evidence.observation_cutoff:
            st.caption('Observation cutoff: '+evidence.observation_cutoff)
        st.text('Checksum: '+evidence.checksum)
        if evidence.reused_from:
            st.text('Reused parent evidence: '+evidence.reused_from)
        st.json({'filters':filters,'snapshot':evidence.snapshot,'semantic_version':evidence.semantic_version,
                 'created_at':evidence.created_at.isoformat(),'observation_cutoff':evidence.observation_cutoff,
                 'caveats':content['caveats']})
        st.dataframe([q.model_dump() for q in evidence.quality],hide_index=True,width='stretch')
        for query in evidence.queries:
            st.write(query.name)
            st.code(query.sql,language='sql')
            st.json(query.parameters)
            st.dataframe(query.rows,hide_index=True,width='stretch')
    return action
