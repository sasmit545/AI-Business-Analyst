import json
from pathlib import Path
from app.analytics.contributions import decompose


def test_independent_hand_decomposition():
    case=json.loads(Path('evaluation/analyst/decomposition_cases.json').read_text())['case']
    rows=[dict(period=i,key=key,**counts) for i,period in enumerate(('baseline','comparison')) for key,counts in case[period].items()]
    result=decompose(rows,['key'])
    for name,expected in case['expected'].items():
        assert abs(result[name]-expected) < 1e-10


def test_saved_deterministic_report_does_not_certify_live_demo():
    report=json.loads(Path('reports/analyst/deterministic_acceptance.json').read_text())
    assert report['status']=='passed'
    assert report['gates']['complete_demo']=='pending'
    assert report['restored_selection']=={'schema':'lifecycle_v1','visible_tables':8}
    assert report['protected_sources_after']['changed']==[]
    assert len(report['scenarios'])==6
