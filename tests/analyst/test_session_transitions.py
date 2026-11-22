from threading import Event

import pytest

from app.api.session import Sessions
from app.config import Settings
from app.evidence.store import EvidenceStore
from test_agent_flow import AuthorizationDouble


def test_clarification_can_retry_after_save_failure_and_waits_for_other_work(tmp_path,monkeypatch):
    entered = Event()
    finish = Event()

    class Runner:
        def run(self,job):
            if job.question=='second':
                entered.set()
                finish.wait(timeout=10)
            job.status='clarification_required'

    sessions=Sessions(Settings(db_password='test'),tmp_path,lambda auth,store: Runner(),
                      lambda settings: AuthorizationDouble(),lambda: EvidenceStore(tmp_path/'evidence'))
    try:
        session=sessions.create()
        first=sessions.start(session.id,'first')
        first.future.result(timeout=10)
        second=sessions.start(session.id,'second')
        assert entered.wait(timeout=10)
        with pytest.raises(ValueError,match='already running'):
            sessions.reply(session.id,first.scope.investigation_id,1,'Dates')
        finish.set()
        second.future.result(timeout=10)
        def unavailable(*jobs):
            raise OSError('Storage unavailable')
        with monkeypatch.context() as fault:
            fault.setattr(session,'save',unavailable)
            with pytest.raises(OSError):
                sessions.reply(session.id,first.scope.investigation_id,1,'Dates')
        assert first.status=='clarification_required' and first.revision==1 and not first.clarification_exchanges
        sessions.reply(session.id,first.scope.investigation_id,1,'Dates').future.result(timeout=10)
        assert first.revision==2 and first.messages==[{'role':'user','content':'Dates'}]
    finally:
        finish.set()
        sessions.shutdown()
