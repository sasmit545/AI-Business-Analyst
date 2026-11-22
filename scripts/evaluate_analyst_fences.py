"""Verify administrative transitions against a disposable native PostgreSQL cluster."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

import postgres_phase1 as pg
import setup_analyst_metadata as setup

sys.path.insert(0, str(pg.ROOT))
from app.analytics.attempts import analyze
from app.api.recovery import SessionLease
from app.config import Settings
from app.contracts import AnalysisRequest, Scope
from app.evidence.postgres_store import PostgresStore
from app.query.executor import Authorization, Budget, StaleSession


def control():
    return pg.query_json('SELECT scenario,generation,import_epoch,ready FROM analyst_meta.control')[0]


class SavedAnalysis:
    def __init__(self, settings):
        self.settings = settings
        self.key = secrets.token_urlsafe()
        self.scope = Scope(session_id=uuid4().hex, scenario='scenario_a')
        self.lease = SessionLease(settings, self.scope.session_id, 'scenario_a', self.key, create=True)
        self.store = PostgresStore(settings)
        self.store.owner_token = self.lease.owner
        auth = Authorization(settings)
        try:
            request = AnalysisRequest(baseline={'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},
                                      comparison={'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'})
            evidence = analyze(settings, auth, self.scope, request, Budget())
            self.evidence = self.store.put(evidence, 'analysis')
            assert self.store.get(self.evidence.id, self.scope) == self.evidence
        finally:
            auth.close()

    def verify_stale(self):
        try:
            self.store.get(self.evidence.id, self.scope)
        except StaleSession:
            pass
        else:
            raise AssertionError('Evidence remained readable after administrative change')
        finally:
            self.lease.close()
        try:
            revived = SessionLease(self.settings, self.scope.session_id, 'scenario_a', self.key, create=False)
        except StaleSession:
            return
        revived.close()
        raise AssertionError('Previously authorized session resumed after administrative change')


def run_cases(root):
    pg.create_database()
    pg.bootstrap()
    pg.select_scenario('scenario_a')
    setup.install()
    settings = Settings.from_root(root)
    report = {}
    for name, selections in (('same_schema', ['scenario_a']), ('A_B_A', ['scenario_b', 'scenario_a'])):
        saved = SavedAnalysis(settings)
        before = control()
        for selection in selections:
            pg.select_scenario(selection)
        after = control()
        saved.verify_stale()
        assert after == dict(before, generation=before['generation'] + len(selections))
        report[name] = {'before':before, 'after':after, 'stale_resume_and_evidence_rejected':True}

    # Header-only inputs exercise real COPY on all 23 disposable tables.
    def input_dir(schema):
        return root/'inputs'/schema

    for schema in pg.SCENARIOS:
        directory = input_dir(schema)
        directory.mkdir(parents=True)
        for table in pg.tables_for(schema):
            (directory/f'{table}.csv').write_text(','.join(pg.fields_for(schema)[table])+'\n', encoding='ascii')
    with patch.object(pg, 'data_path', input_dir):
        saved = SavedAnalysis(settings)
        before = control()
        pg.psql(pg.ingestion_sql())
        after = control()
        assert after == dict(before, import_epoch=before['import_epoch']+1)
        saved.verify_stale()
        report['successful_import'] = {'before':before, 'after':after, 'stale_resume_and_evidence_rejected':True}

        saved = SavedAnalysis(settings)
        pg.psql("INSERT INTO scenario_a.banks VALUES ('BANK_A','Fixture bank')")
        input_dir('lifecycle_v1').joinpath('bank_health.csv').rename(input_dir('lifecycle_v1')/'unavailable')
        before = control()
        failure = pg.psql(pg.ingestion_sql(), check=False)
        assert failure.returncode != 0 and '58P01' in failure.stderr
        after = control()
        assert after == dict(before, import_epoch=before['import_epoch']+1, ready=False)
        assert pg.psql("SELECT bank_name FROM scenario_a.banks WHERE bank_id='BANK_A'").stdout.strip() == 'Fixture bank'
        saved.verify_stale()
        report['failed_import'] = {'before':before, 'after':after, 'fixture_rollback':True, 'stale_resume_and_evidence_rejected':True}

    pg.select_scenario('scenario_a')
    saved = SavedAnalysis(settings)
    before = control()
    pg.psql('ALTER TABLE scenario_b.payments RENAME TO unavailable')
    failure = pg.psql(pg.selection_sql('scenario_b'), check=False)
    assert failure.returncode != 0 and '42P01' in failure.stderr
    after = control()
    assert after == dict(before, generation=before['generation']+1, ready=False)
    assert pg.psql("SELECT rolcanlogin FROM pg_roles WHERE rolname='ai_analyst'").stdout.strip() == 'f'
    saved.verify_stale()
    report['failed_selection'] = {'before':before, 'after':after, 'login_disabled':True, 'stale_resume_and_evidence_rejected':True}
    return report


@contextmanager
def disposable_cluster():
    """Bind the administrative helper to a fresh native cluster for this process."""
    parent = (pg.ROOT/'.local/analyst/fence-tests').resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=parent)).resolve()
    assert root.parent == parent
    local = root/'.local/postgres'
    writer = root/'.local/analyst/writer_password'
    with socket.socket() as available:
        available.bind(('127.0.0.1',0))
        port = available.getsockname()[1]
    with ExitStack() as context:
        context.enter_context(patch.object(pg, 'LOCAL', local))
        context.enter_context(patch.object(pg, 'PGDATA', local/'pgdata'))
        context.enter_context(patch.object(setup, 'WRITER_SECRET', writer))
        context.enter_context(patch.dict(os.environ, PAYMENTS_POSTGRES_PORT=str(port)))
        server = None
        try:
            pg.init_secrets()
            pg.run_native('initdb', '-D', pg.PGDATA, '-U', 'postgres', '--encoding=UTF8', '--locale=C',
                          '--auth=scram-sha-256', '--pwfile', local/'postgres_password',
                          '-c', 'shared_buffers=16MB', '-c', 'max_connections=16')
            # Run the project binary as a foreground child under this Windows
            # account so the test owns and waits for the server process itself.
            with (local/'server.log').open('w', encoding='utf-8') as log:
                server = subprocess.Popen([str(pg.BIN/'postgres.exe'), '-D', str(pg.PGDATA), '-h', '127.0.0.1',
                                           '-p', str(port)], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 30
            while pg.psql('SELECT 1', database='postgres', check=False).returncode:
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError((local/'server.log').read_text(encoding='utf-8')[-2000:])
                time.sleep(.2)
            pg.check_server_identity()
            pg.save_json(local/'native_config.json', {'port':port, 'data_directory':str(pg.PGDATA)})
            yield root
        finally:
            # Stop and remove only the cluster created in the uniquely owned directory.
            assert root.resolve().parent == parent and pg.PGDATA.resolve() == root/'.local/postgres/pgdata'
            if (pg.PGDATA/'postmaster.pid').exists():
                pg.run_native('pg_ctl','stop','-D',pg.PGDATA,'-m','fast','-w')
            if server is not None:
                server.wait(timeout=30)
            shutil.rmtree(root)


def main():
    with disposable_cluster() as root:
        report = run_cases(root)
    report.update(status='passed', mode='disposable native PostgreSQL', cleanup=not root.exists(),
                  recorded_at=datetime.now(timezone.utc).isoformat())
    path = pg.REPORTS/'analyst/administrative_fences.json'
    path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'All five administrative transitions passed. Report: {path.relative_to(pg.ROOT)}')


if __name__ == '__main__':
    main()
