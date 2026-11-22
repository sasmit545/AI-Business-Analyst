from app.evidence.verify import verify_evidence
from app.quality.policy import blocked
from app.contracts import Dashboard
from app.ui_specs.models import Block, Layout
from app.ui_specs.results import result_catalog, selected_rows


def validate_dashboard(dashboard, evidence):
    verify_evidence(evidence)
    for component in dashboard.components:
        if component.evidence_id != evidence.id:
            raise ValueError('Dashboard source mismatch')
        if component.kind in ('quality', 'evidence'):
            continue
        if blocked(evidence.quality):
            raise ValueError('Quality block prevents metric rendering')
        rows = evidence.results[component.table]
        if len(rows) > 2000:
            raise ValueError('Dashboard row limit exceeded')
        if component.kind in ('bar', 'line'):
            if not component.x or not component.y:
                raise ValueError('Chart axes are required')
            if any(component.x not in row or component.y not in row for row in rows):
                raise ValueError('Chart field is not in result')
    return dashboard


CHARTS = {'line', 'bar', 'area', 'pie'}


def validate_layout(layout, evidence):
    verify_evidence(evidence)
    if layout.evidence_id != evidence.id:
        raise ValueError('Layout belongs to another result')
    sources = result_catalog(evidence)
    if layout.headline_measure and ('overall' not in sources or
                                   layout.headline_measure not in sources['overall'].measures):
        raise ValueError('Unavailable headline measure')
    seen = set()
    for block in layout.blocks:
        signature = (block.kind, block.source, block.measure, block.period)
        source = sources.get(block.source)
        if source is None or signature in seen:
            raise ValueError('Unavailable or repeated block')
        seen.add(signature)
        if block.period and block.source == 'contributions':
            raise ValueError('Contributions compare both periods')
        rows = selected_rows(block, source)
        if block.kind in ('table', 'insight'):
            if len(rows) > 2000:
                raise ValueError('Table exceeds row limit')
            if block.measure or block.drilldown:
                raise ValueError('Unexpected measure or action')
            if block.kind == 'insight' and (block.source not in ('overall', 'contributions') or block.period):
                raise ValueError('No verified insight for this source')
            continue
        if block.measure not in source.measures:
            raise ValueError('Measure is unavailable on this source')
        if any(block.measure not in row or source.dimension not in row for row in rows):
            raise ValueError('Unresolved encoding')
        if block.kind in ('kpi', 'comparison'):
            if block.source != 'overall' or (block.kind == 'kpi') != bool(block.period) or block.drilldown:
                raise ValueError('Cards require an unambiguous period selection')
            continue
        if len(rows) > 400:
            raise ValueError('Chart exceeds point limit')
        if block.kind in ('line', 'area') and block.source != 'daily':
            raise ValueError('Trends require a time dimension')
        if block.kind == 'area' and block.measure == 'rate':
            raise ValueError('Area requires an additive count')
        if block.kind == 'pie':
            if (block.source not in ('banks', 'methods', 'merchant_categories', 'merchants')
                    or block.measure == 'rate' or not block.period or len(rows) > 8
                    or any(row[block.measure] is None for row in rows)):
                raise ValueError('Composition requires one small partition of additive values')
        if block.drilldown and (block.kind != 'bar' or not source.action_field
                                or getattr(evidence.request.filters, source.action_field) is not None):
            raise ValueError('Unavailable chart action')
    return layout


def default_layout(evidence, chart='bar'):
    blocks = []
    if not blocked(evidence.quality):
        blocks.append(Block(kind='comparison', source='overall', measure='rate'))
        if chart == 'table':
            blocks.append(Block(kind='table', source='overall'))
        elif chart == 'line' and 'daily' in evidence.results:
            blocks.append(Block(kind='line', source='daily', measure='rate'))
        else:
            blocks.append(Block(kind='bar', source='overall', measure='rate'))
        blocks.append(Block(kind='table', source='segments'))
        if not evidence.request.filters.payer_bank_id:
            blocks.append(Block(kind='bar', source='banks', measure='rate', drilldown=True))
    return Layout(version='1', evidence_id=evidence.id, blocks=blocks)


def read_layout(payload, evidence):
    """Restore pre-versioned publications, and keep verified text on display errors."""
    verify_evidence(evidence)
    try:
        if isinstance(payload, dict) and 'components' in payload and 'version' not in payload:
            old = validate_dashboard(Dashboard.model_validate(payload), evidence)
            chart = next((c.kind for c in old.components if c.table == 'overall'
                          and c.kind in ('bar', 'line', 'table')), 'bar')
            return validate_layout(default_layout(evidence, chart), evidence)
        return validate_layout(Layout.model_validate(payload), evidence)
    except (ValueError, KeyError, TypeError):
        return Layout(version='1', evidence_id=evidence.id, blocks=[], fallback=True)
