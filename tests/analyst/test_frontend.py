from app.frontend.renderers import chart


def test_chart_points_match_evidence_and_labels_escape_markup():
    rows=[{'bank':'<script>alert(1)</script>','rate':0.875}, {'bank':'B','rate':None}]
    figure=chart(rows,'bank','rate','bar')
    assert list(figure.data[0].y)==[0.875,None]
    assert '<script>' not in figure.data[0].x[0]


def test_initial_app_has_usable_session_control():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(Path('app/frontend/main.py').resolve()).run(timeout=15)
    assert not app.exception
    assert any(button.label=='Start new session' for button in app.button)


def test_quality_block_renders_no_kpi():
    from streamlit.testing.v1 import AppTest
    from app.contracts import QualityRecord
    from app.evidence.store import checksum
    from test_evidence import example
    evidence=example().model_copy(update={'quality':[QualityRecord(rule='missing_timestamps',count=1,status='BLOCK')]})
    evidence=evidence.model_copy(update={'checksum':checksum(evidence)})
    script=f"import json\nfrom app.frontend.renderers import render_evidence\nrender_evidence(json.loads({evidence.model_dump_json()!r}))"
    app=AppTest.from_string(script).run(timeout=15)
    assert not app.exception
    assert not app.metric
    assert any('blocked' in error.value.lower() for error in app.error)
    assert any('affected records prevent a reliable rate comparison' in item.value for item in app.text)


def test_health_warning_visible_with_provenance_closed():
    from app.contracts import QualityRecord
    from app.evidence.store import checksum
    from app.ui_specs.models import Layout
    from test_generative_ui import show
    from test_source_conflicts import measurement

    evidence = measurement('bank_health')
    warning = QualityRecord(rule='unusable_health_rows', status='WARN', count=3, metric='bank_health')
    evidence = evidence.model_copy(update={'quality': [warning]})
    evidence = evidence.model_copy(update={'checksum': checksum(evidence)})
    app = show(evidence, Layout(version='1', evidence_id=evidence.id, blocks=[]))
    assert not app.exception and not app.error and not app.code
    assert [node.value for node in app.warning] == ['Bank-health rows unusable across the dataset — 3.']
    assert any('Dataset: lifecycle_v1 · Filters: All' in node.value for node in app.caption)
    headings = [node.value for node in app.subheader]
    assert headings[-3:] == ['Observed facts', 'Confidence and interpretation limits', 'Recommendations']


def test_verified_answer_and_followup_stay_with_the_selected_question(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from app.frontend.api_client import ApiClient
    from app.ui_specs.planning import expand_views
    from test_source_conflicts import measurement

    evidence = measurement()
    layout = expand_views(evidence, ['bar.banks.rate'])
    question = 'How did order conversion compare across banks?'
    child_question = 'Which orders were eligible?'
    posts = []
    def request(self, method, path, **kwargs):
        if method == 'POST':
            posts.append((path, kwargs['json']))
            return {'investigation_id': 'child'}
        if path.endswith('/child'):
            return {'question': child_question, 'parent_id': 'parent', 'status': 'running'}
        return {'question': question, 'status': 'verified', 'version': 4, 'budget': {'sql_statements': 8},
                'evidence': evidence.model_dump(mode='json'), 'dashboard': layout.model_dump(mode='json')}
    monkeypatch.setattr(ApiClient, 'request', request)
    app = AppTest.from_file(str(Path('app/frontend/main.py').resolve()))
    app.session_state['session'] = {'session_id': 'test', 'scenario': 'lifecycle_v1'}
    app.session_state['history'] = ['parent']
    app.session_state['investigation'] = 'parent'
    app.run(timeout=30)
    assert not app.exception and not app.error
    assert app.chat_message[0].text[0].value == question and not app.text_area
    assert len(app.get('plotly_chart')) == 1
    assert any('24-hour order conversion by bank' in node.value for node in app.markdown)
    assert not app.date_input and not app.code
    app.toggle[0].set_value(True).run()
    assert list(app.dataframe[0].value.columns) == ['period','payer_bank_id','rate']
    assert not app.get('plotly_chart') and not posts
    app.session_state['options-parent'] = True
    app.run()
    app.selectbox(key='action-parent').select('Change dates').run()
    assert len(app.date_input) == 2
    next(w for w in app.text_input if w.label == 'Question about this result').set_value(child_question)
    next(b for b in app.button if b.label == 'Ask follow-up').click().run()
    assert posts == [('/sessions/test/investigations/parent/followup',
                      {'version': 4, 'action':'question', 'question': child_question})]
    assert app.chat_message[0].text[0].value == child_question
    assert app.title[0].value == 'Follow-up analysis' and not app.table
    next(b for b in app.button if b.label == 'New question').click().run()
    assert app.text_area[0].label == 'Business question' and not app.chat_message
    assert app.session_state['history'] == ['parent', 'child']


def test_period_label_preserves_intraday_bounds_and_midnight_end_exclusion():
    from app.frontend.renderers import window_label
    from test_source_conflicts import measurement
    window = measurement().request.baseline
    assert window_label(window) == '01–14 Oct 2026'
    intraday = window.model_copy(update={'end':window.end.replace(minute=30)})
    assert window_label(intraday) == '2026-10-01T00:00:00+05:30 to 2026-10-15T00:30:00+05:30 (exclusive)'
