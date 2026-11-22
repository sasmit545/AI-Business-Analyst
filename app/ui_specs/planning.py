"""Enumerate grounded presentation choices for the model's publication tool."""
import re

from app.ui_specs.models import Block, Layout
from app.ui_specs.results import result_catalog

HEADINGS = {f'section.{name.lower().replace(" ", "_")}': name
            for name in ('Summary', 'Trend', 'Breakdown', 'Investigation detail')}


def text_only(question):
    return bool(re.search(r'\b(?:text[ -]only|no visuals?|no visualizations?)\b', question, re.I))


def view_options(evidence, question=''):
    options = {}
    if text_only(question):
        return options
    requested_selection = bool(re.search(r'\b(?:click(?:able)?|drill[ -]?down|(?:let me|can I) select)\b',
                                         question, re.I))

    def add(kind, source, measure=None, period=None, drilldown=False):
        parts = ['drill_bar' if drilldown else kind, source, measure, period]
        key = '.'.join(part for part in parts if part)
        options[key] = Block(kind=kind, source=source, measure=measure, period=period, drilldown=drilldown)

    for name, data in result_catalog(evidence).items():
        add('table', name)
        if name in ('overall', 'contributions'):
            add('insight', name)
        if not data.rows or len(data.rows) > 400:
            continue
        for measure in data.measures:
            if name == 'overall':
                add('comparison', name, measure)
                for period in ('baseline', 'comparison'):
                    add('kpi', name, measure, period)
            if name == 'daily':
                add('line', name, measure)
                if measure != 'rate':
                    add('area', name, measure)
            elif data.dimension:
                add('bar', name, measure)
                if data.action_field and getattr(evidence.request.filters, data.action_field) is None:
                    add('bar', name, measure, drilldown=True)
                    if requested_selection:
                        options[f'bar.{name}.{measure}'] = options[f'drill_bar.{name}.{measure}']
                if name != 'overall' and measure != 'rate':
                    for i, period in enumerate(('baseline', 'comparison')):
                        values = [r[measure] for r in data.rows if r['period'] == i]
                        if 0 < len(values) <= 8 and all(v is not None for v in values) and sum(values):
                            add('pie', name, measure, period)
    return options


def expand_views(evidence, views, headline_measure=None, question=''):
    options = view_options(evidence, question)
    section = None
    blocks = []
    requested = set(views)
    for view in views:
        if view in HEADINGS:
            section = HEADINGS[view]
        elif view in options:
            block = options[view]
            # A requested comparison already contains both KPI cards. An interactive
            # bar renders the same values as its static equivalent. Draw each once.
            if block.kind == 'kpi' and f'comparison.overall.{block.measure}' in requested:
                continue
            if view.startswith('bar.') and f'drill_{view}' in requested:
                continue
            blocks.append(block.model_copy(update={'section':section}))
        else:
            raise ValueError('View unavailable for this evidence')
    if views and views[-1] in HEADINGS:
        raise ValueError('Empty section')
    return Layout(version='1', evidence_id=evidence.id, blocks=blocks, headline_measure=headline_measure)


def publication_parameters(evidence, question=''):
    options = view_options(evidence, question)
    choices = [*options, *HEADINGS] if options else []
    required = ['evidence_id']
    properties = {'evidence_id':{'type':'string', 'enum':[evidence.id]}}
    if choices:
        required.append('views')
        properties['views'] = {'type':'array', 'maxItems':12, 'items':{'type':'string', 'enum':choices},
                               'description':'Ordered view IDs. At most six data blocks. Use [] for text alone.'}
    overall = result_catalog(evidence).get('overall')
    if overall is not None:
        properties['headline_measure'] = {'type':'string', 'enum':list(overall.measures),
                                          'description':'Optional overall measure for a factual headline.'}
    return {'type':'object', 'additionalProperties':False, 'required':required,
            'properties':properties}
