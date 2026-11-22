import pytest
from app.analytics.attempts import analyze
from app.config import Settings
from app.contracts import Claim, Component, Dashboard, Scope
from app.evidence.render_claims import conversion_drop_finding, narrative
from app.evidence.store import EvidenceStore, checksum
from app.evidence.verify import verify_claim, verify_evidence
from app.query.executor import Authorization, Budget
from app.ui_specs.validate import validate_dashboard
from test_evidence import example


def test_rate_confidence_uses_each_verified_denominator_and_distinguishes_amounts():
    from app.analytics.lifecycle import derive
    from test_source_conflicts import measurement

    evidence = measurement()
    raw = {query.name: [dict(row, denominator=25) if row['period'] == 1 else row
                        for row in query.rows] for query in evidence.queries}
    queries = [query.model_copy(update={'rows': raw[query.name]}) for query in evidence.queries]
    evidence = evidence.model_copy(update={'queries': queries, 'results': derive(raw, evidence.request.metric)})
    evidence = evidence.model_copy(update={'checksum': checksum(evidence)})
    assert '10 pp in the baseline or 4 pp in the comparison' in narrative(evidence)['confidence']
    assert 'share of due gross paise' in narrative(measurement('settlement_amount'))['confidence']


def test_conversion_drop_compares_paired_rates_and_reports_exact_ties():
    def row(bank, period, paid, eligible):
        return dict(payer_bank_id=bank, payment_method='CARD', period=period, numerator=paid, denominator=eligible)

    segments = [row('A', 0, 3, 5), row('A', 1, 1, 2), row('B', 0, 4, 5), row('B', 1, 7, 10),
                row('C', 0, 0, 1), row('C', 1, 1, 1), row('D', 0, 1, 1), row('D', 1, 0, 0)]
    finding = conversion_drop_finding(segments)
    assert 'A / CARD (60.0000% to 50.0000%)' in finding and 'B / CARD (80.0000% to 70.0000%)' in finding
    assert '10.0000 percentage points' in finding and 'C / CARD' not in finding and 'D / CARD' not in finding
    assert 'held steady or rose' in conversion_drop_finding(segments[4:])
    assert 'No bank and payment method' in conversion_drop_finding(segments[6:])


@pytest.fixture(scope='module')
def executed(tmp_path_factory):
    settings = Settings.from_root()
    auth = Authorization(settings)
    try:
        raw = analyze(settings,auth,Scope(scenario=auth.scenario,session_id='claims'),example().request,Budget())
        return EvidenceStore(tmp_path_factory.mktemp('evidence')).put(raw,'one')
    finally:
        auth.close()


def test_claims_are_recomputed_and_bad_units_rejected(executed):
    verify_evidence(executed)
    value = executed.results['overall'][0]['rate']
    claim = Claim(evidence_id=executed.id,table='overall',row=0,field='rate',value=value,unit='fraction')
    assert verify_claim(claim,executed) == value
    for bad in (claim.model_copy(update={'value':value+0.1}),claim.model_copy(update={'unit':'count'})):
        with pytest.raises(ValueError):
            verify_claim(bad,executed)
    assert narrative(executed)['facts']


def test_rechecks_derived_counts_even_with_valid_checksum(executed):
    broken=executed.model_copy(deep=True)
    broken.results['overall'][0]['successes'] += 1
    broken=broken.model_copy(update={'checksum':checksum(broken)})
    with pytest.raises(ValueError):
        verify_evidence(broken)


def test_dashboard_rejects_unknown_field_or_other_source(executed):
    for component in (Component(kind='bar',evidence_id=executed.id,x='unknown',y='rate'),Component(kind='table',evidence_id='other')):
        with pytest.raises(ValueError):
            validate_dashboard(Dashboard(components=[component]),executed)
