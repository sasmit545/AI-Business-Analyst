"""Exercise the publication, renderer and follow-up contracts with actual restricted SQL."""
import json
import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from app.agent.graph import Investigator
from app.agent.model import ModelUnavailable, ToolCall
from app.api.main import create_app
from app.api.session import Investigation
from app.config import Settings
from app.contracts import Scope
from app.evidence.store import EvidenceStore, checksum
from app.evidence.verify import verify_evidence
from app.frontend.blocks import REGISTRY, chart_figure
from app.query.executor import Authorization
from app.ui_specs.models import Block, Layout
from app.ui_specs.planning import expand_views, publication_parameters, view_options
from app.ui_specs.results import Result, result_catalog
from app.ui_specs.validate import read_layout, validate_layout
from test_evidence import example
from test_source_conflicts import measurement

WINDOWS = (' Compare 2026-10-01 inclusive to 2026-10-15 exclusive versus '
           '2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata.')
CASES = {
    'trend': ('Show the daily payment success rate trend.', None,
              [dict(kind='line', source='daily', measure='rate', section='Trend')]),
    'banks': ('Compare failed payment attempt counts bank by bank. Let me select a bank.', None,
              [dict(kind='bar', source='banks', measure='failed_attempts', drilldown=True)]),
    'category': ('Compare attempt success by merchant category.', 'merchant_categories',
                 [dict(kind='bar', source='merchant_categories', measure='rate', section='Breakdown')]),
    'cause': ('Investigate whether payment success fell and explain the segment contributions.', None,
              [dict(kind='comparison', source='overall', measure='rate'), dict(kind='insight', source='contributions'),
               dict(kind='table', source='failures')]),
    'detail': ('Show the latest individual payment attempts with their statuses.', 'transactions',
               [dict(kind='table', source='transactions')]),
    'fact': ('Just tell me how many completed attempts there were in both periods. Text only.', None, []),
}


class PresentationDouble:
    """A recorded tool contract, independent of provider availability."""
    def __init__(self, case):
        self.case = case

    def next(self, messages, tools, budget):
        question = next(m['content'] for m in messages if m['role']=='user')
        self.case = next((k for k, (prompt, _, _) in CASES.items() if question.startswith(prompt)), self.case)
        _, detail, blocks = CASES[self.case]
        if any(t['function']['name']=='analyze_attempts' for t in tools):
            args = example().request.model_dump(mode='json')
            if detail:
                args['detail'] = detail
            return ToolCall('query', 'analyze_attempts', args)
        observation = json.loads(messages[-1]['content'])
        assert all(block['source'] in observation['ui_sources'] for block in blocks)
        args = dict(evidence_id=observation['evidence_id'], blocks=blocks)
        if self.case == 'fact':
            args['headline_measure'] = 'attempts'
        return ToolCall('publish', 'publish_answer', args)


def run_case(tmp_path, case, live=False, model=None):
    settings = Settings.from_root()
    auth = Authorization(settings)
    runner = Investigator(settings, auth, EvidenceStore(tmp_path),
                          model=None if live else (model or PresentationDouble(case)))
    job = Investigation(CASES[case][0] + WINDOWS, Scope(scenario=auth.scenario, session_id='ui-test'))
    try:
        runner.run(job)
    finally:
        runner.close()
        auth.close()
    assert job.status == 'verified', (job.error, job.clarification, job.budget.repairs)
    return job


@pytest.mark.integration
@pytest.mark.parametrize('case', CASES)
def test_six_questions_sql_to_streamlit(tmp_path, case):
    job = run_case(tmp_path, case)
    spec = validate_layout(job.dashboard, job.evidence)
    assert spec.blocks == [Block(**b) for b in CASES[case][2]] and not spec.fallback
    sources = result_catalog(job.evidence)
    for block in spec.blocks:
        if block.kind in ('bar', 'line'):
            source = sources[block.source]
            figure = chart_figure(block, source)
            assert [v for t in figure.data for v in t.y] == [r[block.measure] for r in source.rows]
    if case == 'detail':
        assert 0 < len(sources['transactions'].rows) <= 50
        assert sources['transactions'].rows == job.evidence.queries[-1].rows
    if case == 'banks':
        failures = next(q.rows for q in job.evidence.queries if q.name=='failures')
        for row in sources['banks'].rows:
            assert row['failed_attempts'] == sum(f['count'] for f in failures
                if (f['period'], f['payer_bank_id']) == (row['period'], row['payer_bank_id']))
    if case == 'category':
        assert {r['category'] for r in sources['merchant_categories'].rows}
        changed = job.evidence.model_copy(deep=True)
        changed.results['merchant_categories'][0]['successes'] += 1
        with pytest.raises(ValueError):
            verify_evidence(changed.model_copy(update={'checksum':checksum(changed)}))
    app = show(job.evidence, spec)
    assert not app.exception and not app.warning
    assert len(app.get('plotly_chart')) == sum(b.kind in ('bar','line') for b in spec.blocks)
    assert any(job.evidence.id in w.value for w in app.text)
    if case == 'fact':
        assert any(w.value.startswith('Completed attempts:') for w in app.subheader)


def show(evidence, spec):
    code = ("import json\nfrom app.frontend.renderers import render_evidence\n"
            f"render_evidence(json.loads({evidence.model_dump_json()!r}), "
            f"dashboard_payload=json.loads({spec.model_dump_json()!r}))")
    return AppTest.from_string(code).run(timeout=25)


@pytest.mark.parametrize('views', [['table.segments'], []])
def test_conversion_answer_is_visible_before_the_audit_details(views):
    evidence = measurement()
    app = show(evidence, expand_views(evidence, views))
    assert not app.exception
    visible_text = [w.value for w in app.main.children.values() if w.type == 'text']
    assert any('BANK_E / CARD' in text and '20.0000 percentage points' in text for text in visible_text)
    if views:
        table = app.table[0].value
        assert list(table['Paid within 24 hours']) == ['9', '7']
        assert list(table['Eligible orders']) == ['10', '10']
        assert list(table['Conversion']) == ['90.0000%', '70.0000%']
        assert '14 Oct' in table['Orders created'].iloc[0]
        assert '28 Oct' in table['Orders created'].iloc[1]
    else:
        assert not app.table and not app.get('plotly_chart')
        assert any('9 of 10 eligible orders' in text for text in visible_text)
    assert not app.json and not app.code
    app.session_state['provenance-'+evidence.id] = True
    app.run()
    assert not app.exception and app.json
    assert [w.value for w in app.code] == [q.sql for q in evidence.queries]


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_LIVE_UI') != '1', reason='Opt-in NVIDIA visualization planning')
@pytest.mark.parametrize('case', CASES)
def test_real_provider_layout(tmp_path, case, record_property):
    job = run_case(tmp_path, case, live=True)
    calls = [json.loads(c['function']['arguments']) for m in job.messages
             for c in m.get('tool_calls', []) if c['function']['name']=='publish_answer' and c['id']!='text-only']
    assert calls and not job.dashboard.fallback, calls
    blocks = job.dashboard.blocks
    record_property('blocks', json.dumps([b.model_dump(exclude_none=True) for b in blocks]))
    record_property('evidence', job.evidence.id)
    record_property('sql_statements', job.budget.statements)
    assert blocks == expand_views(job.evidence, calls[-1].get('views', []), question=job.question).blocks
    if case == 'fact':
        assert blocks == [] and job.dashboard.headline_measure == 'attempts'
    elif case == 'banks':
        assert any(b.source=='banks' and b.measure=='failed_attempts' and b.drilldown for b in blocks)
    elif case == 'cause':
        assert any(b.source in ('segments', 'failures', 'contributions') for b in blocks)
    else:
        expected = {b['source'] for b in CASES[case][2]}
        assert any(b.source in expected for b in blocks), blocks


@pytest.mark.parametrize('bad', [
    {'kind':'html','source':'overall'}, {'kind':'table','source':'nonexistent'},
    {'kind':'kpi','source':'overall','measure':'rate','period':'baseline','value':42},
    {'kind':'bar','source':'banks','measure':'rate','url':'https://invalid.test'},
    {'kind':'table','source':'transactions'}, {'kind':'line','source':'banks','measure':'rate'},
    {'kind':'bar','source':'banks','measure':'successes'},
    {'kind':'pie','source':'banks','measure':'rate','period':'baseline'},
    {'kind':'bar','source':'overall','measure':'rate','drilldown':True},
])
def test_invalid_layout_preserves_verified_text(bad):
    evidence = measurement()
    payload = dict(version='1', evidence_id=evidence.id, blocks=[bad])
    with pytest.raises((ValidationError, ValueError)):
        validate_layout(Layout.model_validate(payload), evidence)
    assert read_layout(payload, evidence).fallback
    for invalid in (dict(payload, version='9'), dict(payload, evidence_id='other'),
                    dict(payload, blocks=[dict(kind='table',source='overall')]*7)):
        assert read_layout(invalid, evidence).blocks == []


def test_old_saved_chart_and_bad_checksum():
    e = measurement()
    payload = dict(components=[dict(kind='table', table='overall', evidence_id=e.id)])
    layout = read_layout(payload, e)
    assert layout.version == '1' and not layout.fallback
    assert layout.blocks[1].kind == 'table'
    with pytest.raises(ValueError, match='checksum'):
        read_layout(payload, e.model_copy(update={'checksum':'invalid'}))


def test_planning_menu_is_bound_to_the_verified_source():
    evidence = measurement()
    options = view_options(evidence)
    schema = publication_parameters(evidence)
    assert schema['properties']['evidence_id']['enum'] == [evidence.id]
    assert 'line.daily.rate' not in options
    assert 'views' not in publication_parameters(evidence, 'Answer in text only')['properties']
    clickable = expand_views(evidence, ['bar.banks.rate'], question='Let me select a bank')
    assert clickable.blocks[0].drilldown
    for option in options:
        validate_layout(expand_views(evidence, [option]), evidence)
    layout = expand_views(evidence, ['section.breakdown', 'drill_bar.banks.rate'])
    assert layout.blocks == [Block(kind='bar', source='banks', measure='rate', drilldown=True, section='Breakdown')]
    with pytest.raises(ValueError):
        expand_views(evidence, ['line.daily.rate'])


def test_chart_preserves_gaps_and_escapes_dimension_labels():
    daily = Result([dict(period=0, day='2026-10-01', rate=.5), dict(period=0, day='2026-10-03', rate=None)], 'day')
    trace = chart_figure(Block(kind='line', source='daily', measure='rate'), daily).data[0]
    assert list(trace.y)==[.5,None,None] and trace.connectgaps is False
    bank = Result([dict(period=1, payer_bank_id='<b>Bank</b>', rate=.2)], 'payer_bank_id')
    assert chart_figure(Block(kind='bar', source='banks', measure='rate'), bank).data[0].x[0]=='&lt;b&gt;Bank&lt;/b&gt;'


def test_daily_trend_fits_both_periods_and_formats_small_changes():
    daily = Result([
        dict(period=0, day='2026-10-01', rate=.97001),
        dict(period=0, day='2026-10-03', rate=None),
        dict(period=1, day='2026-10-15', rate=.97002),
    ], 'day')
    block = Block(kind='line', source='daily', measure='rate')
    figure = chart_figure(block, daily)
    low, high = figure.layout.yaxis.range
    assert .9699 < low < .97001 < .97002 < high < .9701
    assert format(.97001, figure.layout.yaxis.tickformat) != format(.97002, figure.layout.yaxis.tickformat)
    assert list(figure.data[0].y) == [.97001, None, None]
    assert list(figure.data[1].customdata) == [2]
    assert chart_figure(block, daily, fit_values=False).layout.yaxis.range == (0, 1)


@pytest.mark.parametrize(('rates', 'expected'), [
    ([None, None], (0, 1)), ([None, 1.0], (0, 1)), ([.95, .95], (0, 1)),
    ([0, .001], (0, None)), ([.999, 1], (None, 1)), ([0, 1], (0, 1)),
])
def test_focused_rate_range_respects_endpoints_and_flat_series(rates, expected):
    source = Result([dict(period=i, rate=r) for i, r in enumerate(rates)], 'period')
    block = Block(kind='bar', source='overall', measure='rate')
    assert chart_figure(block, source).layout.yaxis.range == (0, 1)
    low, high = chart_figure(block, source, fit_values=True).layout.yaxis.range
    assert 0 <= low < high <= 1
    assert expected[0] is None or low == expected[0]
    assert expected[1] is None or high == expected[1]
    for r in rates:
        assert r is None or low <= r <= high


def test_daily_counts_fit_lines_and_preserve_a_zero_baseline_for_area():
    daily = Result([dict(period=i, day=f'2026-10-{i+1:02}', attempts=1000+i) for i in (0, 1)], 'day')
    for kind in ('line', 'area'):
        block = Block(kind=kind, source='daily', measure='attempts')
        low, high = chart_figure(block, daily, fit_values=True).layout.yaxis.range
        assert 990 < low < 1000 < 1001 < high < 1010
        figure = chart_figure(block, daily)
        if kind == 'area':
            assert figure.layout.yaxis.rangemode == 'tozero'
        else:
            assert figure.layout.yaxis.range == (low, high)


def test_empty_periods_keep_missing_rates_and_empty_sources():
    from app.analytics.lifecycle import derive
    e = measurement()
    e = e.model_copy(update={'queries':[q.model_copy(update={'rows':[]}) for q in e.queries],
                             'results':derive({'overall':[], 'segments':[]}, e.request.metric)})
    e = e.model_copy(update={'checksum':checksum(e)})
    layout = Layout(version='1',evidence_id=e.id,blocks=[
        Block(kind='comparison', source='overall',measure='rate'), Block(kind='bar',source='banks',measure='rate'),
        Block(kind='table',source='segments')])
    app = show(e, layout)
    assert not app.exception and not app.get('plotly_chart')
    assert [m.value for m in app.metric]==['Unavailable','Unavailable']
    assert any('denominator is zero in both periods' in node.value for node in app.text)
    assert {m.value for m in app.info}=={'No matching rows.','No measured values in this selection.'}


def test_bad_model_view_discards_complete_layout_but_preserves_ownership(tmp_path):
    from app.agent.tools import Dispatcher, PolicyRejected
    from test_agent_flow import AuthorizationDouble
    e = measurement()
    store = EvidenceStore(tmp_path)
    job = Investigation('Show the evidence', e.scope, status='running', evidence=store.put(e, 'analysis'))
    dispatcher = Dispatcher(Settings(db_password='unused'), AuthorizationDouble(), store)
    preview = job.snapshot()
    assert preview['verified_finding'] and preview['dashboard'] is None and preview['evidence'] is None
    call = dict(evidence_id=e.id, views=['comparison.overall.rate','missing.view'])
    for _ in range(2):
        retry = dispatcher.call(ToolCall('p','publish_answer', call), job)
        assert retry['legal_requested_views']==['comparison.overall.rate']
        assert job.snapshot()['dashboard'] is None
    dispatcher.call(ToolCall('p','publish_answer', call), job)
    assert job.dashboard.fallback and not job.dashboard.blocks and job.snapshot()['narrative']['facts']
    with pytest.raises(PolicyRejected):
        dispatcher.call(ToolCall('foreign','publish_answer',dict(call,evidence_id='other')), job)


@pytest.mark.integration
def test_all_component_renderers_and_generation_fallback(tmp_path, monkeypatch):
    job = run_case(tmp_path, 'trend')
    evidence = job.evidence
    extra = [
        Block(kind='area', source='daily', measure='attempts'),
        Block(kind='pie', source='methods', measure='attempts', period='comparison'),
        Block(kind='kpi', source='overall', measure='rate', period='baseline'),
        Block(kind='table', source='daily_summary'),
    ]
    spec = Layout(version='1', evidence_id=evidence.id, blocks=extra)
    app = show(evidence, spec)
    assert len(app.metric)==1 and len(app.get('plotly_chart'))==2 and not app.exception and not app.warning
    def broken(*args):
        raise RuntimeError('Rendering failed')
    monkeypatch.setitem(REGISTRY, 'area', broken)
    app = show(evidence, spec)
    assert app.warning and not app.exception and any(evidence.id in x.value for x in app.text)
    class BrokenPlanner(PresentationDouble):
        def next(self, messages, tools, budget):
            if any(t['function']['name']=='publish_answer' for t in tools):
                raise ModelUnavailable('Provider timed out')
            return super().next(messages, tools, budget)
    text = run_case(tmp_path/'fallback', 'fact', model=BrokenPlanner('fact'))
    assert text.narrative['facts'] and text.dashboard.blocks == []


@pytest.mark.integration
def test_api_point_dates_breakdown_and_context_reuse(tmp_path):
    settings = Settings.from_root()
    api = create_app(settings, tmp_path, runner_factory=lambda auth, store:
                     Investigator(settings, auth, store, PresentationDouble('banks')),
                     store_factory=lambda: EvidenceStore(tmp_path/'artifacts'))
    with TestClient(api) as client:
        assert client.get('/ui/schema').status_code == 401
        client.headers['Authorization'] = 'Bearer '+(tmp_path/'.local/analyst/api_token').read_text()
        assert client.get('/ui/schema').json() == Layout.model_json_schema()
        sid = client.post('/sessions').json()['session_id']
        start = '/sessions/'+sid+'/investigations'
        def finish(response):
            assert response.status_code == 200, response.text
            iid = response.json()['investigation_id']
            api.state.sessions.sessions[sid].jobs[iid].future.result(timeout=125)
            data = client.get(start+'/'+iid).json()
            assert data['status']=='verified', data['error']
            return data
        parent = finish(client.post(start, json={'question':CASES['banks'][0]+WINDOWS}))
        path = start+'/'+parent['investigation_id']+'/followup'
        def post(version, **args):
            return client.post(path, json=dict(version=version, **args))
        assert post(1, action='point', block=0, row=399).status_code == 409
        assert post(1, action='point', block=0, row=0, filters={'merchant_id':'X'}).status_code == 422
        child = finish(post(1, action='point', block=0, row=0))
        e = child['evidence']
        assert child['parent_id'] == parent['investigation_id'] and child['budget']['sql_statements'] > 0
        assert e['request']['filters']['payer_bank_id'] == parent['evidence']['results']['banks'][0]['payer_bank_id']
        assert child['dashboard']['headline_measure']=='failed_attempts'
        assert post(1, action='point', block=0, row=0).status_code == 409
        detail = finish(post(2, action='breakdown', detail='merchants'))
        assert detail['evidence']['queries'][-1]['name']=='merchants'
        req = e['request']
        dates = finish(post(3, action='windows', baseline=req['baseline'], comparison={
            'start':'2027-01-15T00:00:00+05:30','end':'2027-01-16T00:00:00+05:30'}))
        assert dates['evidence']['results']['overall'][1]['rate'] is None
        reuse = finish(post(4, action='question', question='Show the same bank comparison again.'))
        assert reuse['budget']['sql_statements'] == 0 and reuse['evidence']['reused_from'] == parent['evidence']['id']
        assert reuse['evidence']['queries']==parent['evidence']['queries']
