"""Opt-in browser/API/database journeys with explicit model-double or live modes."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest


def activate_button(page, name):
    button=page.get_by_role('button',name=name,exact=True)
    button.wait_for(state='visible')
    assert button.is_enabled()
    button.press('Enter')


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_BROWSER_TEST')!='1',reason='Opt-in browser processes; model double does not certify live acceptance')
def test_browser_real_api_database_and_visible_evidence():
    from playwright.sync_api import sync_playwright
    root=Path.cwd()
    report_dir=root/'reports/analyst'
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    children=[]
    logs=[]
    live_model=os.environ.get('ANALYST_BROWSER_REAL_MODEL')=='1'
    image_prefix='browser-live' if live_model else 'browser'
    scenario=os.environ.get('ANALYST_BROWSER_SCENARIO','lifecycle_v1')
    metric=os.environ.get('ANALYST_BROWSER_METRIC','attempt_success')
    lifecycle=metric!='attempt_success'
    if lifecycle:
        assert live_model and scenario=='lifecycle_v1'
        from scripts.evaluate_lifecycle import independent_truth
        from app.analytics.lifecycle import DEFINITIONS
        truth,_,_=independent_truth()
        expected_rates=[r['numerator']/r['denominator'] for r in truth[metric]]
        image_prefix='browser-live-'+metric
    else:
        expected_rates=[97462/100402,96485/99331]
    assert scenario in ('lifecycle_v1','scenario_a_dirty')
    api_module='app.api.main:app' if live_model else 'browser_harness:app'
    api_directory='.' if live_model else 'tests/analyst'
    # Never drive an operator's already-running application as a test service.
    for port in (8000,8501):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1',port))
            except OSError:
                pytest.fail(f'Port {port} is occupied or unavailable; stop your application before this browser test')
    try:
        for name,command in [
            ('browser-api',[sys.executable,'-m','uvicorn',api_module,'--app-dir',api_directory,'--host','127.0.0.1','--port','8000','--log-level','warning']),
            ('browser-ui',[sys.executable,'-m','streamlit','run','app/frontend/main.py','--server.address','127.0.0.1','--server.port','8501','--server.headless','true','--browser.gatherUsageStats','false'])]:
            log=(report_dir/(name+'.log')).open('w')
            logs.append(log)
            children.append(subprocess.Popen(command,stdout=log,stderr=log,creationflags=flags))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if any(child.poll() is not None for child in children):
                pytest.fail('Browser service failed to start; see reports/analyst/browser-*.log')
            try:
                if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=1).status==200:
                    break
            except OSError:
                time.sleep(.25)
        with sync_playwright() as playwright:
            if any(child.poll() is not None for child in children):
                pytest.fail('Test services exited before browser startup; see reports/analyst/browser-*.log')
            browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1050})
            page.goto('http://127.0.0.1:8501')
            activate_button(page,'Start new session')
            question=(f'Compare {DEFINITIONS[metric][0]} for 2026-10-01 inclusive to 2026-10-15 exclusive versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. Use observation cutoff 2026-11-01T00:00:00+05:30.'
                      if lifecycle else 'Compare attempt success for October 1-14 and October 15-28, 2026 in Asia/Kolkata.')
            question += (' Show both overall rates as comparison cards, then an overall rate bar chart, '
                         'and a bank and method detail table.')
            page.get_by_role('textbox',name='Business question').fill(question)
            activate_button(page,'Analyze')
            if scenario=='scenario_a_dirty':
                page.get_by_text('Status: Blocked',exact=True).wait_for(timeout=125000)
                page.get_by_text('Certified metrics blocked by data quality.',exact=True).wait_for()
                for diagnostic in ('duplicate_occurrences: 20','missing_timestamps: 10','orphan_merchants: 10'):
                    page.get_by_text(diagnostic,exact=False).wait_for()
                assert page.get_by_test_id('stMetric').count()==0
                assert page.locator('.js-plotly-plot').count()==0
                page.get_by_text('SQL, quality and provenance',exact=True).click()
                evidence_text=page.get_by_text('Evidence ID:',exact=False).inner_text()
                page.screenshot(path=str(report_dir/(image_prefix+'-dirty.png')),full_page=True)
                browser.close()
                name='browser_dirty_live_validation.json' if live_model else 'browser_dirty_validation.json'
                (report_dir/name).write_text(json.dumps({'status':'passed','live_model':live_model,
                    'recorded_at':datetime.now(timezone.utc).isoformat(),'scenario':scenario,
                    'evidence_id':evidence_text.removeprefix('Evidence ID: '),'visible_status':'blocked',
                    'defects':{'duplicate_occurrences':20,'missing_timestamps':10,'orphan_merchants':10},
                    'certified_metrics_visible':False,'screenshot':image_prefix+'-dirty.png'},indent=2)+'\n')
                return
            terminal=page.get_by_text(re.compile(r'^Status: (Verified|Blocked|Failed|Limited|Needs clarification|Outdated|Cancelled)$'))
            terminal.wait_for(timeout=125000)
            assert terminal.inner_text()=='Status: Verified'
            page.get_by_text(question, exact=True).wait_for()
            for rate in set(expected_rates):
                page.get_by_text(f'{100*rate:.4f}%',exact=True).first.wait_for()
            page.get_by_text('SQL, quality and provenance',exact=True).click()
            if lifecycle:
                page.get_by_text('Denominator:',exact=False).wait_for()
                page.get_by_text('Observation cutoff:',exact=False).first.wait_for()
            page.get_by_text('Evidence ID:',exact=False).wait_for()
            evidence_text=page.get_by_text('Evidence ID:',exact=False).inner_text()
            page.get_by_role('heading', name='Payment analysis',exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(report_dir/(image_prefix+'-desktop.png')),full_page=True)
            # Chart data is the exact unrounded database numerator/denominator.
            data=page.locator('.js-plotly-plot').first.evaluate('(el) => el.data.map(trace => ({x:Array.from(trace.x),y:Array.from(trace.y)}))')
            assert data[0]['y']==expected_rates
            if lifecycle:
                page.get_by_text('Bank and method detail',exact=True).wait_for(state='visible')
                page.get_by_test_id('stDataFrame').first.wait_for(state='visible')
            collapse=page.get_by_test_id('stSidebarCollapseButton')
            if collapse.is_visible():
                collapse.get_by_role('button').press('Enter')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('heading', name='Payment analysis',exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(report_dir/(image_prefix+'-mobile.png')),full_page=True)
            # A consequential date ambiguity must clear the previous answer.
            expand_sidebar = page.get_by_test_id('stExpandSidebarButton')
            if expand_sidebar.is_visible():
                expand_sidebar.press('Enter')
            activate_button(page,'New question')
            page.get_by_role('textbox',name='Business question').fill('Why did success rate fall last week?')
            activate_button(page,'Analyze')
            page.get_by_text('Status: Needs clarification',exact=True).wait_for(timeout=15000)
            page.get_by_role('textbox',name='Clarification reply').wait_for()
            assert page.get_by_test_id('stMetric').count()==0
            assert page.locator('.js-plotly-plot').count()==0
            assert page.get_by_text('Evidence ID:',exact=False).count()==0
            page.screenshot(path=str(report_dir/(image_prefix+'-safe-failure.png')),full_page=True)
            browser.close()
            report_name=('browser_'+metric+'_validation.json' if lifecycle else 'browser_live_validation.json') if live_model else 'browser_validation.json'
            (report_dir/report_name).write_text(json.dumps({'status':'passed','mode':'real_model_browser_api_database' if live_model else 'real_browser_api_database_with_model_double','live_model':live_model,'recorded_at':datetime.now(timezone.utc).isoformat(),'evidence_id':evidence_text.removeprefix('Evidence ID: '),'chart_data':data,'safe_failure':{'status':'clarification_required','previous_metrics_cleared':True},'screenshots':[image_prefix+suffix for suffix in ('-desktop.png','-mobile.png','-safe-failure.png')],'complete_demo':'pending'},indent=2)+'\n')
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for log in logs:
            log.close()
