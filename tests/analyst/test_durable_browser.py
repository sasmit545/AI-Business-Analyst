"""Real browser, model and database proof on private loopback ports."""
import json
import csv
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest


def _serve_api(project, runtime, port, *, model_double=False):
    import uvicorn
    from app.api.main import create_app
    from app.config import Settings

    settings = Settings.from_root(project)
    factory = None
    if model_double:
        from app.agent.graph import Investigator
        from test_agent_flow import CompareDouble
        factory = lambda auth, store: Investigator(settings, auth, store, CompareDouble())
    api = create_app(settings=settings, root=runtime, runner_factory=factory)
    uvicorn.run(api, host='127.0.0.1', port=port, log_level='warning', access_log=False)


def _serve_ui(project, runtime, api_port, ui_port):
    from streamlit.web import cli

    os.environ['ANALYST_RUNTIME_ROOT'] = str(runtime)
    os.environ['ANALYST_API_PORT'] = str(api_port)
    sys.argv = ['streamlit', 'run', str(project/'app/frontend/main.py'), '--server.address=127.0.0.1',
                f'--server.port={ui_port}', '--server.headless=true', '--server.fileWatcherType=none',
                '--browser.gatherUsageStats=false']
    cli.main()


def _stop(proc):
    if proc.is_alive():
        proc.terminate()
    proc.join(10)
    if proc.is_alive():
        proc.kill()
        proc.join(5)


def _port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_ready(process, url, token=None):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.is_alive():
        try:
            headers = {'Authorization': 'Bearer '+token.read_text().strip()} if token else {}
            with urlopen(Request(url, headers=headers), timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            time.sleep(.25)
    raise RuntimeError('Private test service failed to start')


def _attempt_counts(root):
    directory = root/'data/synthetic/phase3/lifecycle_v1'
    boundaries = [datetime.fromisoformat(f'2026-10-{day}T00:00:00+05:30') for day in ('01', '15', '29')]
    counts = defaultdict(lambda: [0, 0])
    with (directory/'payments.csv').open(newline='', encoding='utf8') as stream:
        for row in csv.DictReader(stream):
            attempted = datetime.fromisoformat(row['attempted_at'])
            if not boundaries[0] <= attempted < boundaries[2]:
                continue
            for bank in (None, row['payer_bank_id']):
                cell = counts[int(attempted >= boundaries[1]), bank]
                cell[1] += 1
                cell[0] += row['status'] == 'SUCCESS'
    return counts


def _saved_attempt_comparison(base, token):
    """Prepare a real saved result before running the browser and database together."""
    def request(method, path, body=None):
        headers = {'Authorization': 'Bearer '+token.read_text().strip(), 'Content-Type': 'application/json'}
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base+path, method=method, data=data, headers=headers), timeout=30) as response:
            return json.load(response)

    # An explicit private test receipt permits a browser-only retry of the same
    # real investigation without another paid/provider-side operation.
    receipt_name = os.environ.get('ANALYST_DURABLE_BROWSER_RECEIPT')
    receipt = None
    if receipt_name:
        directory = Path('.local/analyst/test-temp').resolve()
        receipt = Path(receipt_name).resolve()
        if not receipt.is_relative_to(directory):
            raise ValueError('Browser test receipt must be in the private test-temp directory.')
        if receipt.exists():
            return json.loads(receipt.read_text())
    session = request('POST', '/sessions')
    path = '/sessions/'+session['session_id']
    try:
        question = ('Compare attempt success for 2026-10-01 inclusive to 2026-10-15 exclusive '
                    'versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. '
                    'Show an overall rate comparison with two metric cards and a grouped bar chart '
                    'of success rates by bank that I can click to drill down.')
        job = request('POST', path+'/investigations', {'question': question})
        deadline = time.monotonic()+140
        while job['status'] in ('received', 'running'):
            if time.monotonic() >= deadline:
                raise TimeoutError('The saved investigation did not finish.')
            time.sleep(.5)
            job = request('GET', path+'/investigations/'+job['investigation_id'])
        if job['status'] != 'verified':
            raise RuntimeError('Saved attempt comparison '+job['status']+': '+str(job.get('error')))
        assert any(b['drilldown'] and b['source']=='banks' for b in job['dashboard']['blocks']), job['dashboard']
        saved = {'resume_id': session['resume_id'], 'resume_key': session['resume_key'],
                 'parent_id': job['investigation_id'], 'evidence_id': job['evidence']['id']}
        if receipt:
            receipt.write_text(json.dumps(saved))
        return saved
    finally:
        request('POST', path+'/detach')


def _rates(counts, bank):
    return [counts[period, bank][0] / counts[period, bank][1] for period in range(2)]


def _button(page, name):
    control = page.get_by_role('button', name=name, exact=True)
    control.wait_for(state='visible', timeout=90000)
    control.press('Enter')


def _resume_page(page, url, saved_id, status='Verified'):
    page.goto(url, wait_until='commit', timeout=90000)
    page.get_by_role('heading', name='Payments analyst',exact=True).wait_for(timeout=90000)
    row = page.locator('.st-key-saved-session-'+saved_id).get_by_role('button')
    row.click(timeout=90000)
    page.get_by_text('Status: '+status, exact=True).wait_for(state='attached', timeout=90000)


def _read_id(page):
    provenance = page.get_by_text('Evidence ID:', exact=False)
    provenance.wait_for(state='attached', timeout=90000)
    return provenance.text_content().removeprefix('Evidence ID: ')


def _failure_oracle(project):
    """Independent counts from the supplied fixture, outside the analyst process."""
    from collections import Counter
    counts = Counter()
    attempts = [0, 0]
    successes = [0, 0]
    csv_path = project/'data/synthetic/phase3/lifecycle_v1/payments.csv'
    with csv_path.open(encoding='utf-8', newline='') as source:
        for row in csv.DictReader(source):
            day = row['attempted_at'][:10]
            if not '2026-10-01' <= day < '2026-10-29':
                continue
            period = int(day >= '2026-10-15')
            attempts[period] += 1
            successes[period] += row['status'] == 'SUCCESS'
            if period == 1 and row['status'] == 'FAILED':
                counts[row['failure_reason']] += 1
    return attempts, successes, counts


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_RECOMMENDATION_BROWSER') != '1',
                    reason='Opt-in Chromium, restricted PostgreSQL and durable API with a model double')
def test_ranked_recommendation_followup_survives_restart(tmp_path, monkeypatch, record_property):
    from uuid import uuid4
    from app.frontend.api_client import ApiClient

    project = Path.cwd()
    attempts, successes, counts = _failure_oracle(project)
    winners = sorted(label for label in counts if counts[label] == max(counts.values()))
    question = f'Which failure reason accounted for the most failures? Oct 1–14 vs 15–28, 2026 IST. {uuid4().hex[:8]}'
    followup = 'What steps should I take to address this?'
    ctx = multiprocessing.get_context('spawn')
    api_port, ui_port = _port(), _port()
    base, url = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{ui_port}'
    token = tmp_path/'.local/analyst/api_token'
    monkeypatch.setenv('ANALYST_RUNTIME_ROOT', str(tmp_path))
    monkeypatch.setenv('ANALYST_API_PORT', str(api_port))
    client = ApiClient()

    def start_api():
        process = ctx.Process(target=_serve_api, args=(project, tmp_path, api_port), kwargs={'model_double':True})
        process.start()
        return process

    api = start_api()
    ui = ctx.Process(target=_serve_ui, args=(project, tmp_path, api_port, ui_port))
    ui.start()
    try:
        _wait_ready(api, base+'/health', token)
        _wait_ready(ui, url+'/_stcore/health')
        with _browser() as browser:
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            page.goto(url, wait_until='commit')
            _button(page, 'Start new session')
            page.get_by_role('textbox', name='Business question').fill(question)
            _button(page, 'Analyze')
            page.get_by_text('Status: Verified', exact=True).wait_for(timeout=135000)
            from playwright.sync_api import TimeoutError as BrowserTimeout
            try:
                parent_evidence = _read_id(page)
            except BrowserTimeout as exc:
                raise AssertionError(page.get_by_test_id('stAlert').all_inner_texts()) from exc
            heading = page.get_by_role('heading').filter(has_text='accounted for the most failed attempts').inner_text()
            assert all(w in heading for w in winners) and f'{max(counts.values()):,}' in heading
            chart_values = page.locator('.js-plotly-plot').first.evaluate('(el) => Array.from(el.data[0].y)')
            assert chart_values == [n/d for n, d in zip(successes, attempts)]
            page.get_by_role('textbox', name='Question about this result').fill(followup)
            _button(page, 'Ask follow-up')
            page.get_by_text('Evidence ID: '+parent_evidence, exact=True).wait_for(state='detached', timeout=90000)
            page.get_by_text('Status: Verified', exact=True).wait_for(timeout=90000)
            child_evidence = _read_id(page)
            assert child_evidence != parent_evidence
            _button(page, 'Saved sessions')
            page.get_by_role('heading', name='Payments analyst', exact=True).wait_for()
            saved_id = next(r['session_id'] for r in client.request('GET','/local/sessions')['sessions']
                            if r['title'] == question)
            reopened = client.request('POST','/local/sessions/'+saved_id+'/open')
            handle = '/sessions/'+reopened['session_id']
            parent, child = [client.request('GET',handle+'/investigations/'+i) for i in reopened['investigation_ids']]
            assert parent['evidence']['id'] == parent_evidence
            assert child['evidence']['id'] == child_evidence and child['evidence']['reused_from'] == parent_evidence
            assert child['evidence']['snapshot'] == parent['evidence']['snapshot']
            assert child['evidence']['request'] == parent['evidence']['request']
            assert child['evidence']['queries'] == parent['evidence']['queries']
            assert [r['attempts'] for r in child['evidence']['results']['overall']] == attempts
            assert [r['successes'] for r in child['evidence']['results']['overall']] == successes
            assert parent['budget']['sql_statements'] > 0 and child['budget']['sql_statements'] == 0
            for row in (parent, child):
                guidance = row['narrative']['guidance']
                assert guidance['source'] == 'failures' and guidance['evidence_id'] == row['evidence']['id']
                assert row['dashboard']['finding_ref'] == guidance['reference']
                assert sorted(k['failure_reason'] for k in guidance['leaders']) == winners
                assert row['narrative']['analysis_plan']['objective']['kind'] == 'volume'
            assert child['narrative']['recommendations'] == parent['narrative']['recommendations']
            action = child['narrative']['recommendations'][0]
            assert child['narrative']['answer'] == action and all(w in action for w in winners)
            assert child['dashboard']['response'] == 'action'
            client.request('POST', handle+'/detach')
            _stop(api)
            api = start_api()
            _wait_ready(api, base+'/health', token)
            mobile = browser.new_page(viewport={'width':390, 'height':844})
            _resume_page(mobile, url, saved_id)
            assert _read_id(mobile) == child_evidence
            mobile.get_by_role('heading', name=action, exact=True).wait_for(timeout=60000)
            mobile.get_by_text('SQL, quality and provenance', exact=True).click()
            mobile.get_by_text('Reused parent evidence: '+parent_evidence, exact=True).wait_for(timeout=60000)
            for name, value in [('verified_parent', parent_evidence), ('verified_child', child_evidence),
                                ('winning_labels', winners), ('comparison_failed_volume', max(counts.values())),
                                ('plotted_attempt_success_rates', chart_values),
                                ('child_sql_statements', 0), ('reopened_mobile_headline', action)]:
                record_property(name, value)
    finally:
        try:
            if api.is_alive() and token.exists():
                rows = client.request('GET', '/local/sessions')['sessions']
                for row in rows:
                    if row['title'] == question:
                        opened = client.request('POST', '/local/sessions/'+row['session_id']+'/open')
                        client.request('DELETE','/sessions/'+opened['session_id'])
        finally:
            _stop(ui)
            _stop(api)


def _select_bank(browser, url, saved, bank, counts):
    page = browser.new_page(viewport={'width':1440,'height':1000})
    _resume_page(page, url, saved['resume_id'])
    if _read_id(page) != saved['evidence_id']:
        _button(page, 'Chat history')
        page.get_by_role('button', name='Open investigation', exact=True).first.press('Enter')
    page.get_by_text('Evidence ID: '+saved['evidence_id'],exact=True).wait_for(state='attached',timeout=90000)
    for rate in _rates(counts, None):
        page.get_by_text(f"{100*rate:.4f}%",exact=True).first.wait_for(timeout=90000)
    plot = page.locator('.js-plotly-plot').filter(has=page.locator('g.xtick text').filter(has_text=bank))
    plot.wait_for(state='visible',timeout=90000)
    assert plot.evaluate('(el) => el.data[0].x[0]') == bank
    bar = plot.locator('.barlayer .trace').first.locator('.point path').first
    bar.scroll_into_view_if_needed()
    box = bar.bounding_box()
    assert box
    page.mouse.click(box['x']+box['width']/2,box['y']+box['height']/2)
    page.get_by_text('Select a bar to run this comparison for its bank.').wait_for(state='detached',timeout=135000)
    page.get_by_text('Status: Verified',exact=True).wait_for(timeout=135000)
    child_id = _read_id(page)
    assert child_id != saved['evidence_id']
    assert page.locator('.js-plotly-plot').first.evaluate('(el) => Array.from(el.data[0].y)') == _rates(counts, bank)
    _button(page,'Saved sessions')
    page.get_by_role('heading', name='Payments analyst',exact=True).wait_for(timeout=90000)
    page.close()
    return child_id


def _validate_saved_child(base, token, saved, evidence_id, bank, counts):
    from app.contracts import Evidence
    from app.evidence.verify import verify_evidence

    def request(method, path, data=None):
        headers={'Content-Type':'application/json','Authorization':'Bearer '+token.read_text().strip()}
        body = json.dumps(data).encode() if data else None
        with urlopen(Request(base+path, method=method, headers=headers, data=body), timeout=30) as result:
            return json.load(result)
    session = request('POST','/sessions/resume',{'session_id':saved['resume_id'],'resume_key':saved['resume_key']})
    path='/sessions/'+session['session_id']
    try:
        parent = request('GET',path+'/investigations/'+saved['parent_id'])
        child = next(r for i in reversed(session['investigation_ids'])
                     if (r := request('GET',path+'/investigations/'+i)).get('evidence',{}).get('id') == evidence_id)
        e = Evidence.model_validate(child['evidence'])
        verify_evidence(e)
        assert child['parent_id'] == saved['parent_id'] and parent['evidence']['id'] == saved['evidence_id']
        expected = dict(parent['evidence']['request'])
        expected['filters'] = dict(expected['filters'], payer_bank_id=bank)
        assert child['evidence']['request'] == expected
        for r in e.results['overall']:
            assert [r['successes'],r['attempts']] == counts[r['period'],bank]
        assert e.checksum and child['status'] == 'verified'
        return e.checksum
    finally:
        request('POST',path+'/detach')


@contextmanager
def _browser():
    """If Chromium hangs on shutdown, release only the processes this launch owns."""
    import _winapi
    from threading import Timer
    from playwright.sync_api import sync_playwright

    driver=sync_playwright().start()
    browser=driver.chromium.launch(
        executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True,
        args=['--disable-gpu','--disable-extensions','--renderer-process-limit=1','--disable-background-networking'])
    cdp=browser.new_browser_cdp_session()
    processes=cdp.send('SystemInfo.getProcessInfo')['processInfo']
    cdp.detach()
    handles=[]
    for pid in {p['id'] for p in processes}:
        try:
            handles.append(_winapi.OpenProcess(_winapi.SYNCHRONIZE | 1,False,pid))
        except OSError:
            pass

    def reap():
        for handle in handles:
            if _winapi.WaitForSingleObject(handle,0)==_winapi.WAIT_TIMEOUT:
                try:
                    _winapi.TerminateProcess(handle,0)
                except OSError:
                    pass
    try:
        yield browser
    finally:
        timer=Timer(15,reap)
        timer.start()
        try:
            try:
                browser.close()
            finally:
                driver.stop()
        finally:
            timer.cancel()
            timer.join()
            for handle in handles:
                _winapi.CloseHandle(handle)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_LOCAL_SESSION_BROWSER') != '1', reason='Opt-in local session browser')
def test_open_local_sessions_without_credentials(tmp_path, monkeypatch):
    from uuid import uuid4
    from app.frontend.api_client import ApiClient

    project = Path.cwd()
    ctx = multiprocessing.get_context('spawn')
    api_port, ui_port = _port(), _port()
    base, url = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{ui_port}'
    token = tmp_path/'.local/analyst/api_token'
    api = ctx.Process(target=_serve_api, args=(project,tmp_path,api_port))
    ui = ctx.Process(target=_serve_ui, args=(project,tmp_path,api_port,ui_port))
    monkeypatch.setenv('ANALYST_RUNTIME_ROOT', str(tmp_path))
    monkeypatch.setenv('ANALYST_API_PORT', str(api_port))
    client = ApiClient()
    suffix = uuid4().hex[:8]
    questions = [f'How did {metric} perform last week? ({suffix})' for metric in ('orders', 'payments')]
    api.start()
    ui.start()
    try:
        _wait_ready(api,base+'/health',token)
        _wait_ready(ui,url+'/_stcore/health')
        with _browser() as browser:
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.goto(url, wait_until='commit')
            for question in questions:
                _button(page, 'Start new session')
                page.get_by_role('textbox', name='Business question').fill(question)
                _button(page, 'Analyze')
                page.get_by_text('Status: Needs clarification', exact=True).wait_for()
            rows = client.request('GET', '/local/sessions')['sessions']
            first = next(row['session_id'] for row in rows if row['title'] == questions[0])
            _stop(api)
            api = ctx.Process(target=_serve_api, args=(project,tmp_path,api_port))
            api.start()
            _wait_ready(api,base+'/health',token)
            fresh = browser.new_page(viewport={'width':390,'height':844})
            _resume_page(fresh, url, first, 'Needs clarification')
            fresh.get_by_text(questions[0], exact=True).wait_for()
            assert fresh.get_by_label('Session key', exact=True).count() == 0
    finally:
        try:
            if api.is_alive() and token.exists():
                for row in client.request('GET', '/local/sessions')['sessions']:
                    if row['title'] in questions:
                        opened = client.request('POST', '/local/sessions/'+row['session_id']+'/open')
                        client.request('DELETE', '/sessions/'+opened['session_id'])
        finally:
            _stop(ui)
            _stop(api)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_DURABLE_BROWSER') != '1', reason='Opt-in real model and browser')
def test_chart_selection_and_restart(tmp_path):
    root = Path.cwd()
    ctx = multiprocessing.get_context('spawn')
    api_port = _port()
    token = tmp_path/'.local/analyst/api_token'
    base = f'http://127.0.0.1:{api_port}'
    api = ctx.Process(target=_serve_api, args=(root, tmp_path, api_port))
    api.start()
    ui = None
    try:
        _wait_ready(api, base+'/health', token)
        saved = _saved_attempt_comparison(base, token)
        counts = _attempt_counts(root)
        bank = min(bank for _, bank in counts if bank is not None)
        ui_port = _port()
        ui = ctx.Process(target=_serve_ui, args=(root, tmp_path, api_port, ui_port))
        ui.start()
        url = f'http://127.0.0.1:{ui_port}'
        _wait_ready(ui,url+'/_stcore/health')
        prior_child = os.environ.get('ANALYST_DURABLE_BROWSER_CHILD')
        if prior_child:
            child_id = prior_child
        else:
            with _browser() as browser:
                child_id = _select_bank(browser,url,saved,bank,counts)
            print('Chart click produced fresh bank evidence.',flush=True)
        # Confirm the parent, exact inherited request and actual SQL row counts
        # before testing an independent replacement API and fresh mobile browser.
        checksum = _validate_saved_child(base,token,saved,child_id,bank,counts)
        print('Confirmed saved parent, selected bank, and unrounded CSV counts.',flush=True)
        old_pid = api.pid
        _stop(api)
        api = ctx.Process(target=_serve_api,args=(root,tmp_path,api_port))
        api.start()
        _wait_ready(api,base+'/health',token)
        assert old_pid != api.pid
        with _browser() as browser:
            page=browser.new_page(viewport={'width':390,'height':844})
            _resume_page(page,url,saved['resume_id'])
            collapse=page.get_by_test_id('stSidebarCollapseButton').get_by_role('button')
            if collapse.is_visible():
                collapse.press('Enter')
            assert _read_id(page) == child_id
            page.get_by_text('Status: Verified',exact=True).wait_for(timeout=90000)
            chart=page.locator('.js-plotly-plot').first
            chart.wait_for(state='visible',timeout=90000)
            assert chart.evaluate('(el) => Array.from(el.data[0].y)') == _rates(counts,bank)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
            print('The mobile browser restored the selected bank and correct chart.',flush=True)
        artifact={
            'status':'passed','mode':'live NVIDIA/API/PostgreSQL/Chromium','selected_bank':bank,
            'source_evidence_id':saved['evidence_id'],'child_evidence_id':child_id,'checksum':checksum,
            'independent_csv_counts':[counts[p,bank] for p in (0,1)],'independent_csv_rates':_rates(counts,bank),
            'desktop_click':'previous browser run; this run revalidated its saved child' if prior_child else 'performed this run',
            'checks':['Child inherits the exact parent request plus the selected bank',
                      'Both filtered period counts match independent source CSV calculations',
                      'Replacement API process and fresh mobile browser recovered the same evidence and chart values']}
        (root/'reports/analyst/generative_ui_browser.json').write_text(json.dumps(artifact,indent=2)+'\n')
    finally:
        if ui is not None:
            _stop(ui)
        _stop(api)
