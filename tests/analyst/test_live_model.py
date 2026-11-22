"""Opt-in real model/API/SQL smoke. Never substitute a double for this check."""
import os
import pytest

from app.agent.graph import Investigator
from app.api.session import Investigation
from app.config import Settings
from app.contracts import Scope
from app.evidence.store import EvidenceStore
from app.query.executor import Authorization


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('ANALYST_LIVE_MODEL') != '1',reason='Set ANALYST_LIVE_MODEL=1 to authorize a real NVIDIA request')
def test_real_nemotron_calls_tools_and_publishes_executed_evidence(tmp_path):
    settings=Settings.from_root()
    auth=Authorization(settings)
    runner=Investigator(settings,auth,EvidenceStore(tmp_path))
    job=Investigation('Compare attempt success rate for 2026-10-01 inclusive through 2026-10-15 exclusive versus 2026-10-15 inclusive through 2026-10-29 exclusive in Asia/Kolkata. Explain bank and method contributions from the data.',Scope(scenario=auth.scenario,session_id='live-smoke'))
    try:
        runner.run(job)
        assert job.status in ('verified','blocked'),job.error
        assert job.evidence is not None
        assert job.evidence.queries
        assert job.narrative
        assert job.budget.tokens_reserved > 0
    finally:
        runner.close()
        auth.close()
