import pytest

from app.agent.objective import Objective, ambiguous_priority, continuation, inferred_objective
from app.evidence.render_claims import publication_narrative
from app.ui_specs.models import Layout
from test_source_conflicts import measurement


def test_interrupted_publication_only_exposes_a_verified_measurement():
    from app.api.session import Investigation
    evidence = measurement()
    job = Investigation('Compare orders', evidence.scope, evidence=evidence)
    for status in ('limited', 'failed'):
        job.fail(status, 'Publication interrupted')
        result = job.snapshot()
        assert result['verified_finding'] and result['error'] == 'Publication interrupted'
        assert result['evidence'] is result['narrative'] is result['dashboard'] is None
    job.evidence = evidence.model_copy(update={'checksum':'invalid'})
    assert 'verified_finding' not in job.snapshot()
    job.evidence = evidence
    job.invalidate()
    assert 'verified_finding' not in job.snapshot()


def test_publication_verifies_saved_finding_and_carries_scope():
    e = measurement('settlement_amount')
    layout = Layout(version='1', evidence_id=e.id, blocks=[], objective=Objective(kind='volume', dimension='bank'))
    content = publication_narrative(e, layout)
    assert content['analysis_plan']['metric'] == 'settlement_amount'
    assert content['analysis_plan']['cutoff'] == e.observation_cutoff
    assert content['analysis_plan']['objective']['dimension'] == 'bank'
    bound = layout.model_copy(update={'finding_ref':content['guidance']['reference']})
    assert publication_narrative(e, Layout.model_validate_json(bound.model_dump_json())) == content
    for change in ({'evidence_id':'other'}, {'finding_ref':'0'*64}, {'objective':Objective(kind='count')}):
        with pytest.raises(ValueError):
            publication_narrative(e, bound.model_copy(update=change))


def test_saved_selection_survives_reworded_guidance(monkeypatch):
    from app.evidence import lifecycle_guidance
    e = measurement()
    layout = Layout(version='1', evidence_id=e.id, blocks=[], objective=Objective(kind='volume'))
    ref = publication_narrative(e, layout)['guidance']['reference']
    original = lifecycle_guidance.lifecycle_guidance
    def reworded(evidence, objective):
        result = original(evidence, objective)
        return dict(result, finding=result['finding'] + ' See the comparison table.')
    monkeypatch.setattr(lifecycle_guidance, 'lifecycle_guidance', reworded)
    restored = publication_narrative(e, layout.model_copy(update={'finding_ref':ref}))
    assert restored['answer'].endswith('See the comparison table.')


def test_scope_free_actions_inherit_priority_but_new_requests_still_require_planning():
    assert continuation('What steps should I take to address this?') == 'action'
    assert continuation('Why?') == 'explanation'
    assert continuation('What should I do about this for another bank?') is None
    assert ambiguous_priority('Rank banks by impact.')
    assert not ambiguous_priority('Rank banks by impact on the overall rate change.')
    assert inferred_objective('Which failure reason was most frequent during the baseline?') == Objective(
        kind='volume', dimension='reason', period='baseline')
    assert inferred_objective('Which failure reason worsened the most?').kind == 'deterioration'
    drivers = inferred_objective('Which bank and payment method contributed most to the change in attempt success?')
    assert (drivers.kind, drivers.dimension) == ('contribution', 'segment')
    assert inferred_objective('How many orders were eligible?').measure == 'denominator'
    assert inferred_objective('Show the daily success trend and a breakdown of failure reasons.').joint_detail is None
    assert inferred_objective('Show failure rates by day for timeouts.').joint_detail == 'reason_by_day'


def test_missing_joint_breakdown_explicitly_names_the_needed_evidence():
    e = measurement('bank_health')
    question = 'Did timeouts coincide with higher latency?'
    layout = Layout(version='1', evidence_id=e.id, blocks=[], objective=inferred_objective(question))
    answer = publication_narrative(e, layout)
    assert 'does not measure individual failed attempts' in answer['answer']
    assert 'five-minute' in answer['recommendations'][0]
