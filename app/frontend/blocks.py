"""Render a validated semantic block. All numerical inputs come from its bound result."""
from datetime import date
from html import escape
from math import ceil, log10

import plotly.graph_objects as go
import streamlit as st

from app.evidence.render_claims import insight_sentences, measure_label
from app.ui_specs.results import selected_rows
from app.ui_specs.validate import CHARTS

PERIODS = ('Baseline', 'Comparison')
LABELS = {
    'overall': 'Overall', 'daily': 'Daily trend', 'banks': 'Banks', 'methods': 'Payment methods',
    'segments': 'Bank and method detail', 'failures': 'Recorded failure labels',
    'merchants': 'Merchants', 'merchant_categories': 'Merchant categories',
    'transactions': 'Latest matching payment attempts (up to 50)',
    'contributions': 'Bank and method contributions to rate change',
    'daily_summary': 'Daily rates across observed days',
    'rate': 'Rate', 'attempts': 'Completed attempts', 'successes': 'Successful attempts',
    'failed_attempts': 'Failed attempts', 'payment_method': 'Payment method',
    'payer_bank_id': 'Bank', 'merchant_id': 'Merchant', 'day': 'Day (Asia/Kolkata)',
}
COLORS = ('#19765e', '#77639d')


def label(key):
    return LABELS.get(key, key.replace('_', ' ').capitalize())


def block_title(block, metric):
    if block.measure:
        suffix = {'daily': ' by day', 'banks': ' by bank', 'methods': ' by payment method',
                  'merchants': ' by merchant', 'merchant_categories': ' by merchant category'}
        name = measure_label(metric, block.measure) + suffix.get(block.source, '')
    else:
        name = label(block.source) if block.source != 'overall' else measure_label(metric, 'rate') + ' by period'
    return f'{name} ({block.period})' if block.period else name


def cell_label(value, dimension):
    if dimension == 'period':
        return PERIODS[value]
    return escape(str(value))


def scale_value_axis(figure, measure, values, fit_values):
    is_rate = measure == 'rate'
    bounds = (0, 1) if is_rate else None
    if fit_values:
        measured = [v for v in values if v is not None]
        if measured and min(measured) < max(measured):
            low, high = min(measured), max(measured)
            padding = max((high - low) * .15, .000001 if is_rate else .5)
            bounds = (max(0, low - padding), min(1, high + padding) if is_rate else high + padding)
    figure.update_yaxes(range=bounds, rangemode='normal' if bounds else 'tozero')
    if is_rate:
        # Keep neighboring ticks distinct even for changes below a basis point.
        precision = max(1, ceil(-log10((bounds[1] - bounds[0]) * 100 / 6)))
        figure.update_yaxes(tickformat=f'.{precision}%', hoverformat=f'.{max(4, precision)}%')
    elif bounds and bounds[1] - bounds[0] < 6:
        figure.update_yaxes(dtick=1, tickformat=',d')


def chart_figure(block, source, metric='attempt_success', *, fit_values=None):
    rows = selected_rows(block, source)
    figure = go.Figure()
    if block.kind == 'pie':
        figure.add_pie(labels=[cell_label(r[source.dimension], source.dimension) for r in rows],
                       values=[r[block.measure] for r in rows], sort=False, textinfo='label+percent')
    else:
        periods = [None] if source.dimension == 'period' else range(2)
        for period in periods:
            points = [(i, r) for i, r in enumerate(rows) if period is None or r['period'] == period]
            if not points:
                continue
            x, y, indices = [], [], []
            last_day = None
            for i, row in points:
                if source.dimension == 'day' and block.kind in ('line', 'area'):
                    day = date.fromisoformat(str(row['day']))
                    if last_day and (day - last_day).days > 1:
                        x.append(None)
                        y.append(None)
                        indices.append(None)
                    last_day = day
                x.append(cell_label(row[source.dimension], source.dimension))
                y.append(row[block.measure])
                indices.append(i)
            color = COLORS[period or 0]
            common = dict(x=x, y=y, name=PERIODS[period] if period is not None else measure_label(metric, block.measure),
                          customdata=indices)
            if block.kind == 'bar':
                bar_colors = [COLORS[r['period']] for _, r in points] if source.dimension == 'period' else color
                figure.add_bar(**common, marker_color=bar_colors)
            else:
                figure.add_scatter(**common, mode='lines+markers', line=dict(color=color, width=2.5),
                                   marker=dict(symbol='diamond' if period == 1 else 'circle', size=7), connectgaps=False,
                                   fill='tozeroy' if block.kind == 'area' else None)
        figure.update_xaxes(title=label(source.dimension), type='date' if source.dimension == 'day' else 'category')
        figure.update_yaxes(title=measure_label(metric, block.measure), automargin=True)
        scale_value_axis(figure, block.measure, (r[block.measure] for r in rows),
                         block.kind == 'line' if fit_values is None else fit_values)
    figure.update_layout(height=335, barmode='group', bargap=.28, barcornerradius=4, clickmode='event+select',
                         showlegend=block.kind == 'pie' or len(figure.data) > 1,
                         legend=dict(orientation='h', x=0, y=1.04, yanchor='bottom'),
                         margin=dict(l=8, r=8, t=18, b=12))
    return figure


def render_chart(block, source, evidence, key, interactive):
    rows = selected_rows(block, source)
    if not rows or all(r[block.measure] is None for r in rows):
        st.info('No measured values in this selection.')
        return
    if block.kind == 'pie' and not any(r[block.measure] for r in rows):
        st.info('Total is zero. Shares are unavailable.')
        return
    fit_values = block.kind == 'line'
    if block.kind != 'pie' and len({r[block.measure] for r in rows if r[block.measure] is not None}) > 1:
        fit_values = st.toggle('Fit y-axis to observed values', value=fit_values, key=key+'-fit-values',
                               help='Zoom in on differences across the plotted values. Switch off to start the scale at zero.')
    figure = chart_figure(block, source, evidence.request.metric, fit_values=fit_values)
    if not (block.drilldown and interactive):
        st.plotly_chart(figure, width='stretch', key=key)
        return
    pending = key + '-point'

    def on_selection():
        points = st.session_state[key]['selection']['points']
        if len(points) == 1:
            point = points[0]
            index = point.get('customdata')
            if index is None:
                curve, offset = point.get('curve_number', 0), point.get('point_index')
                if (type(curve) is int and 0 <= curve < len(figure.data) and type(offset) is int
                        and 0 <= offset < len(figure.data[curve].customdata)):
                    index = figure.data[curve].customdata[offset]
            if type(index) is int and 0 <= index < len(rows):
                st.session_state[pending] = index

    st.caption('Select a bar to run this comparison for its ' + label(source.action_field).lower() + '.')
    st.plotly_chart(figure, width='stretch', key=key, on_select=on_selection, selection_mode='points')
    return st.session_state.pop(pending, None)


def render_cards(block, source, evidence, key, interactive):
    rows = selected_rows(block, source)
    columns = st.columns(len(rows)) if len(rows) > 1 else [st]
    for column, row in zip(columns, rows):
        value = row[block.measure]
        formatted = 'Unavailable' if value is None else (
            f'{100*value:.4f}%' if block.measure == 'rate' else f'{value:,}')
        period = PERIODS[row['period']]
        with column.container(border=True, key=f'metric-card-{period.lower()}-{key}'):
            st.metric(period, formatted)
            if block.measure == 'rate':
                n = row.get('numerator', row.get('successes'))
                d = row.get('denominator', row.get('attempts'))
                st.caption(f'{n:,} / {d:,}')


def render_table(block, source, evidence, key, interactive):
    rows = selected_rows(block, source)
    if rows:
        if block.kind in CHARTS:
            fields = dict.fromkeys(('period', source.dimension, block.measure))
            rows = [{field: row[field] for field in fields} for row in rows]
        display = [dict(row, period=PERIODS[row['period']]) if 'period' in row else row for row in rows]
        config = {}
        for field in display[0]:
            if field == 'rate' or field in ('min_daily_rate', 'median_daily_rate', 'max_daily_rate'):
                heading = measure_label(evidence.request.metric, 'rate') if field == 'rate' else label(field)
                config[field] = st.column_config.NumberColumn(heading, format='percent')
            elif field in ('numerator', 'denominator') and evidence.request.metric != 'attempt_success':
                config[field] = measure_label(evidence.request.metric, field)
            else:
                config[field] = label(field)
        st.dataframe(display, column_config=config, width='stretch', hide_index=True, key=key)
    else:
        st.info('No matching rows.')


def render_insight(block, source, evidence, key, interactive):
    for sentence in insight_sentences(evidence, block.source):
        st.text(sentence)


REGISTRY = {
    'kpi': render_cards, 'comparison': render_cards, 'table': render_table, 'insight': render_insight,
    **dict.fromkeys(('line', 'bar', 'area', 'pie'), render_chart),
}


def render_layout(layout, sources, evidence, presentation, interactive):
    previous_section = None
    as_tables = None
    for index, block in enumerate(layout.blocks):
        if block.section and block.section != previous_section:
            st.caption(block.section)
        previous_section = block.section
        repeats_headline = (index == 0 and block.kind == 'comparison' and block.source == 'overall'
                            and block.measure == layout.headline_measure)
        if not repeats_headline:
            st.markdown('#### ' + block_title(block, evidence.request.metric))
        renderer = REGISTRY[block.kind]
        if block.kind in CHARTS:
            if as_tables is None:
                as_tables = st.toggle('Show chart data as tables', value=presentation == 'Table', key='tables-'+evidence.id)
            if as_tables:
                renderer = render_table
        try:
            selected = renderer(block, sources[block.source], evidence, f'view-{evidence.id}-{index}', interactive)
        except Exception:
            st.warning('This component could not be displayed. Its verified rows are available in provenance.')
            continue
        if selected is not None:
            return {'action':'point', 'block':index, 'row':selected}
