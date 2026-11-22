from pathlib import Path
from datetime import datetime, time, timedelta, timezone
from collections import Counter
from html import escape
from string import punctuation
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

import streamlit as st
from app.frontend.api_client import ApiClient, ResultVersionChanged
from app.frontend.renderers import followup_filters, render_evidence
from app.contracts import Evidence

st.set_page_config(page_title='Payments Analyst', page_icon=':material/finance:', layout='wide')
st.html(Path(__file__).with_name('style.css'))
client=ApiClient(ROOT)
MARKDOWN_ESCAPES = str.maketrans({char: '\\' + char for char in punctuation})
STATUS_LABELS = {'received': 'Queued', 'running': 'Running', 'verified': 'Verified', 'blocked': 'Blocked',
                 'limited': 'Limited', 'failed': 'Failed', 'clarification_required': 'Needs clarification',
                 'stale': 'Outdated', 'cancelled': 'Cancelled'}
TITLE_LIMIT = 100  # app/api/recovery.py stores left(question, 100)

EXAMPLE_QUESTION = (
    'Compare attempt success for October 1–14 and October 15–28, 2026, in Asia/Kolkata. '
    'Which bank and payment method contributed most to the change?'
)


def remember(investigation_id):
    st.session_state.pop('show_history', None)
    st.session_state['investigation'] = investigation_id
    history = st.session_state.setdefault('history', [])
    if investigation_id not in history:
        history.append(investigation_id)


def open_session(session):
    st.session_state.pop('show_history', None)
    st.session_state['session'] = session
    st.session_state['history'] = list(session.get('investigation_ids', []))
    st.session_state.pop('comparison', None)
    st.session_state.pop('investigation', None)
    if st.session_state['history']:
        remember(st.session_state['history'][-1])


def leave_session():
    previous = st.session_state.get('session')
    if previous:
        path = '/sessions/'+previous['session_id']
        if previous.get('resume_id'):
            client.request('POST', path+'/detach')
        else:
            client.request('DELETE', path)
        for key in ('session', 'investigation', 'history', 'comparison', 'show_history'):
            st.session_state.pop(key, None)


def next_investigation(prefix, version, **arguments):
    try:
        result = client.request('POST', prefix+'/followup', json={'version': version, **arguments})
    except ResultVersionChanged as exc:
        st.session_state['changed_result'] = str(exc)
        st.rerun()
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    remember(result['investigation_id'])
    st.rerun()


def start_session():
    try:
        leave_session()
        open_session(client.request('POST','/local/sessions'))
        st.rerun()
    except RuntimeError as exc:
        st.error(str(exc))


def open_saved_session(session_id):
    try:
        open_session(client.request('POST', f'/local/sessions/{session_id}/open'))
    except RuntimeError as exc:
        st.session_state['open_session_error'] = str(exc)


def saved_session_list():
    st.subheader(':material/folder_open: Saved sessions', anchor='saved-sessions')
    if error := st.session_state.pop('open_session_error', None):
        st.error(error)
    try:
        saved = client.request('GET', '/local/sessions')['sessions']
    except RuntimeError as exc:
        st.error(str(exc))
        return
    if not saved:
        st.write('No saved sessions yet.')
        st.caption('Start a session above. Your conversations will appear here.')
        return
    st.caption(f'{len(saved):,} saved {"conversation" if len(saved) == 1 else "conversations"} on this device')
    seen = Counter()
    rows = st.container(height=520 if len(saved) > 5 else 'content', border=False)
    for row in saved:
        label = 'Empty session'
        if row['last_question_at'] is not None:
            date = datetime.fromtimestamp(row['last_question_at'], timezone.utc).astimezone()
            title = ' '.join(row['title'].split())
            if len(row['title']) >= TITLE_LIMIT:
                title = title.rsplit(' ', 1)[0].rstrip(punctuation) + '…'
            title = title.translate(MARKDOWN_ESCAPES)
            label = f'{title}  \n*{date:%d %b %Y, %H:%M}*'
        seen[label] += 1
        if seen[label] > 1:
            label = f'({seen[label]}) {label}'
        session_id = row['session_id']
        rows.button(label, key='saved-session-'+session_id, width='stretch',
                  on_click=open_saved_session, args=(session_id,))


def analysis_options(iid, prefix, current, evidence):
    choices = ['Filter this result', 'Change dates']
    if evidence.request.metric == 'attempt_success':
        choices.append('Change breakdown')
        if current.get('can_test_segment', False):
            choices.append('Test the largest segment change')
    if any(other != iid for other in st.session_state['history']):
        choices.append('Compare saved results')
    choice = st.selectbox('Analysis action', choices, key='action-'+iid)
    version = current['version']
    if choice == 'Filter this result':
        fields = {'Observed combination':None, 'Bank':'payer_bank_id', 'Payment method':'payment_method', 'Merchant':'merchant_id'}
        dimension = st.selectbox('Filter dimension', list(fields), key='filter-dimension-'+iid)
        with st.form('narrow-'+iid):
            field = fields[dimension]
            text = st.text_input(f'{dimension} name or ID' if field else 'Bank, payment method or merchant ID',
                                 max_chars=64 if field else 128)
            if st.form_submit_button('Analyze selection') and text.strip():
                if field:
                    next_investigation(prefix, version, filters={field:text.strip()})
                else:
                    try:
                        filters = followup_filters(text, evidence, st.session_state['session'].get('banks'))
                    except ValueError as exc:
                        st.warning(str(exc))
                    else:
                        next_investigation(prefix, version, filters=filters.model_dump(exclude_none=True))
    elif choice == 'Change dates':
        with st.form('periods-'+iid):
            windows = {}
            for field in ('baseline', 'comparison'):
                window = getattr(evidence.request, field)
                dates = st.date_input(f'{field.capitalize()} dates (inclusive, local time)',
                    (window.start.date(), (window.end - timedelta(microseconds=1)).date()),
                    help=f'Midnight boundaries use UTC offsets {window.start:%z} and {window.end:%z}.')
                if len(dates) == 2:
                    windows[field] = {
                        'start': datetime.combine(dates[0], time.min, window.start.tzinfo).isoformat(),
                        'end': datetime.combine(dates[1]+timedelta(days=1), time.min, window.end.tzinfo).isoformat()}
            if st.form_submit_button('Analyze dates'):
                if len(windows) == 2:
                    next_investigation(prefix, version, action='windows', **windows)
                else:
                    st.warning('Select both endpoints for each window.')
    elif choice == 'Change breakdown':
        with st.form('breakdown-'+iid):
            detail = st.selectbox('Breakdown', ['merchant_categories','merchants','transactions'],
                                  format_func=lambda s: s.replace('_',' ').capitalize())
            if st.form_submit_button('Analyze breakdown'):
                next_investigation(prefix, version, action='breakdown', detail=detail)
    elif choice == 'Test the largest segment change':
        if st.button('Run segment test', key='test-'+iid):
            next_investigation(prefix, version, action='test_hypothesis')
    else:
        entries = client.request('GET', prefix.split('/investigations/')[0]+'/history')['investigations']
        others = {entry['investigation_id']: entry for entry in entries
                  if entry['investigation_id'] != iid and entry['status'] == 'verified'}
        if not others:
            st.info('This session has no other verified result to compare.')
            return
        def choice_label(other_id):
            entry = others[other_id]
            started = datetime.fromtimestamp(entry['created_at'], timezone.utc).astimezone()
            return f"{entry['turns'][0]['text']} ({started:%d %b, %H:%M:%S})"
        with st.form('compare-'+iid):
            other = st.selectbox('Compare with question', list(others), format_func=choice_label)
            if st.form_submit_button('Compare measurements'):
                comparison = client.request('POST', prefix+'/compare', json={
                    'version': version, 'other_investigation_id': other})
                st.session_state['comparison'] = (iid, other, comparison)
        saved = st.session_state.get('comparison', ())
        if saved[:2] == (iid, other):
            st.text(saved[2]['explanation'])
            st.json({'Current measurement': saved[2]['left'], 'Other measurement': saved[2]['right']})


session = st.session_state.get('session')
if session:
    showing_history = st.session_state.get('show_history', False)
    with st.sidebar:
        st.header('Workspace', anchor=False)
        st.divider()
        if (showing_history or st.session_state.get('investigation')) and st.button(
                'New question', type='primary', icon=':material/edit_square:', width='stretch'):
            st.session_state.pop('investigation', None)
            st.session_state.pop('show_history', None)
            st.rerun()
        if st.button('Back to analysis' if showing_history else 'Chat history', icon=':material/history:', width='stretch'):
            st.session_state['show_history'] = not showing_history
            st.rerun()
        st.divider()
        if st.button('Start new session', icon=':material/add:', width='stretch'):
            start_session()
        if session.get('resume_id') and st.button('Saved sessions', icon=':material/folder_open:', width='stretch'):
            try:
                leave_session()
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))

mast_detail = (f'<span>Dataset · <strong>{escape(session["scenario"])}</strong></span>'
               if session else '<a href="#saved-sessions">Saved sessions <span aria-hidden="true">↓</span></a>')
st.html(f'''
    <div class="workspace-mast">
        <div class="workspace-brand">
            <span class="workspace-mark" aria-hidden="true"><i></i><i></i><i></i></span>
            <strong>Payments</strong><span class="workspace-location">Analyst workspace</span>
        </div>
        <div class="workspace-detail">{mast_detail}</div>
    </div>
''')
if not session:
    with st.container(key='home-hero'):
        with st.container():
            st.title('Payments *analyst*', anchor=False)
            st.write('Compare payment performance across banks, methods, and time periods. '
                     'Trace each finding to the data behind it.')
        if st.button('Start new session', type='primary', icon=':material/add:'):
            start_session()
    with st.container(key='session-library', border=True):
        saved_session_list()
elif st.session_state.get('show_history'):
    st.title('Chat history')
    @st.fragment(run_every=3)
    def history_panel():
        try:
            entries = client.request('GET', f"/sessions/{session['session_id']}/history")['investigations']
        except RuntimeError as exc:
            st.error(str(exc))
            return
        if not entries:
            st.info('Your questions and answers will appear here after you start an investigation.')
            return
        questions = {entry['investigation_id']: entry['turns'][0]['text'] for entry in entries}
        for entry in entries:
            iid = entry['investigation_id']
            with st.container(border=True, key='history-entry-'+iid):
                parent = questions.get(entry['parent_id'])
                if parent:
                    st.text('Follow-up to: ' + parent)
                for turn in entry['turns']:
                    avatar = ':material/person:' if turn['role'] == 'user' else ':material/finance:'
                    with st.chat_message(turn['role'], avatar=avatar):
                        st.text(turn['text'])
                started = datetime.fromtimestamp(entry['created_at'], timezone.utc).astimezone()
                st.caption(f"{started:%d %b %Y, %H:%M %Z} · {STATUS_LABELS.get(entry['status'], entry['status'])}")
                if st.button('Open investigation', key='history-open-'+iid):
                    remember(iid)
                    st.rerun()

    history_panel()
elif not st.session_state.get('investigation'):
    st.title('Ask a business question')
    with st.form('question'):
        question=st.text_area('Business question', placeholder=EXAMPLE_QUESTION, height=145, max_chars=4000)
        submit=st.form_submit_button('Analyze',type='primary')
    if submit and question.strip():
        try:
            result=client.request('POST',f"/sessions/{session['session_id']}/investigations",json={'question':question})
            remember(result['investigation_id'])
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))
else:
    @st.fragment(run_every=3)
    def investigation_panel():
        iid=st.session_state.get('investigation')
        if not iid:
            return
        prefix=f"/sessions/{session['session_id']}/investigations/{iid}"
        try:
            current=client.request('GET',prefix)
            if notice := st.session_state.pop('changed_result', None):
                st.info(notice)
            status=current['status']
            st.title('Follow-up analysis' if current.get('parent_id') else 'Payment analysis')
            with st.chat_message('user', avatar=':material/person:'):
                st.text(current['question'])
            with st.container(key='investigation-status-'+status):
                st.caption('Status: '+STATUS_LABELS.get(status, status.replace('_', ' ').capitalize()))
            if status in ('received','running'):
                st.info(current.get('progress', 'Resolving the question and checking its evidence…'))
                if current.get('verified_finding'):
                    st.text(current['verified_finding'])
                if st.button('Cancel investigation',key='cancel'):
                    client.request('POST',prefix+'/cancel')
                    st.rerun(scope='fragment')
            elif status=='clarification_required':
                with st.chat_message('assistant', avatar=':material/finance:'):
                    st.text(current.get('clarification') or 'Please specify the metric and explicit comparison dates.')
                with st.form('clarification'):
                    answer=st.text_input('Clarification reply',max_chars=4000,
                                         placeholder='For example: October 1–14 vs October 15–28, 2026, Asia/Kolkata')
                    if st.form_submit_button('Continue',type='primary') and answer.strip():
                        client.request('POST',prefix+'/reply',json={'version':current['version'],'answer':answer})
                        st.rerun(scope='fragment')
            elif status in ('verified','blocked','limited') and current.get('evidence'):
                action = render_evidence(current['evidence'], dashboard_payload=current.get('dashboard'),
                                         interactive=status == 'verified', banks=session.get('banks'))
                if status == 'verified':
                    evidence = Evidence.model_validate(current['evidence'])
                    if current.get('hypothesis'):
                        test = current['hypothesis']
                        st.subheader('Hypothesis test')
                        st.write(test.get('hypothesis', 'Segment rate comparison'))
                        st.write('Result:', test['status'])
                        if test.get('observed_change_pp') is not None:
                            st.write(f"Observed change: {test['observed_change_pp']:+.4f} percentage points.")
                        st.caption(test.get('limitation', ''))
                    if action:
                        next_investigation(prefix, current['version'], **action)
                    with st.form('followup-question-'+iid):
                        query = st.text_input('Question about this result', max_chars=4000)
                        if st.form_submit_button('Ask follow-up') and query.strip():
                            next_investigation(prefix, current['version'], action='question', question=query.strip())
                    with st.expander('Filters, dates and comparisons', key='options-'+iid, on_change='rerun') as options:
                        if options.open:
                            analysis_options(iid, prefix, current, evidence)
            else:
                st.warning(current.get('error') or f'Investigation {status}. No certified answer is available.')
                if current.get('verified_finding'):
                    st.caption('Verified before the investigation stopped')
                    st.text(current['verified_finding'])
        except (RuntimeError,ValueError,KeyError) as exc:
            st.error(str(exc) if isinstance(exc,RuntimeError) else 'The result could not be verified.')

    investigation_panel()
