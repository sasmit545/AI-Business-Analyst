"""Private checkpoint/evidence writer for the currently authorized fixture."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.contracts import Evidence
from app.evidence.store import checksum
from app.query.executor import StaleSession


def open_writer(settings, root=None):
    directory = Path(root) / '.local/analyst' if root is not None else settings.evidence_dir.parent
    return psycopg.connect(
        host='127.0.0.1', port=settings.db_port, dbname='payments_analytics',
        user='analyst_writer', password=(directory / 'writer_password').read_text().strip(),
        connect_timeout=5, autocommit=True, prepare_threshold=0, row_factory=dict_row,
        options='-c search_path=analyst_meta,pg_catalog -c statement_timeout=10000',
    )


class PostgresStore:
    def __init__(self, settings, root=None):
        self.settings, self.root = settings, root
        self.owner_token = None

    def connect(self):
        return open_writer(self.settings, self.root)

    @contextmanager
    def authorized(self, conn, scope):
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock_shared(604202)')
            control = conn.execute(
                """SELECT c.generation, c.import_epoch
                   FROM analyst_meta.sessions s JOIN analyst_meta.control c
                     ON (s.generation,s.import_epoch,s.scenario)=(c.generation,c.import_epoch,c.scenario)
                   WHERE s.session_id=%s AND s.subject=%s AND s.scenario=%s
                     AND s.owner_token IS NOT DISTINCT FROM %s AND NOT s.revoked AND c.ready
                   FOR SHARE OF s""",
                (scope.session_id, scope.subject, scope.scenario, self.owner_token),
            ).fetchone()
            if control is None:
                raise StaleSession('Saved investigation authorization expired')
            yield control

    @staticmethod
    def _read(row, scope):
        evidence = Evidence.model_validate(row['payload'])
        if evidence.scope != scope or evidence.checksum != checksum(evidence):
            raise ValueError('Saved evidence scope or checksum is invalid')
        return evidence

    def find_step(self, scope, step):
        with self.connect() as conn, self.authorized(conn, scope):
            row = conn.execute(
                """SELECT payload FROM analyst_meta.evidence
                   WHERE session_id=%s AND investigation_id=%s AND version=%s AND step=%s""",
                (scope.session_id, scope.investigation_id, scope.version, step),
            ).fetchone()
        return self._read(row, scope) if row else None

    def has_bundle(self, scope):
        with self.connect() as conn, self.authorized(conn, scope):
            return conn.execute("""SELECT 1 FROM analyst_meta.bundles WHERE session_id=%s
                                   AND investigation_id=%s AND version=%s""",
                                (scope.session_id, scope.investigation_id, scope.version)).fetchone() is not None

    @contextmanager
    def bundle(self, scope, request, parent, budget):
        from app.evidence.bundle_receipts import BundleReceipt
        budget.journal = BundleReceipt(self, scope, request, parent, budget)
        try:
            yield
        finally:
            budget.journal = None

    def get(self, evidence_id, scope):
        with self.connect() as conn, self.authorized(conn, scope):
            row = conn.execute(
                """SELECT payload FROM analyst_meta.evidence
                   WHERE id=%s AND session_id=%s AND investigation_id=%s AND version=%s""",
                (evidence_id, scope.session_id, scope.investigation_id, scope.version),
            ).fetchone()
        if row is None:
            raise KeyError('Unknown evidence')
        return self._read(row, scope)

    def put(self, evidence, step):
        scope = evidence.scope
        saved = evidence.model_copy(update={'checksum': checksum(evidence)})
        if len(saved.model_dump_json().encode()) > 1024 * 1024:
            raise ValueError('Evidence artifact exceeds byte limit')
        with self.connect() as conn, self.authorized(conn, scope):
            key = (scope.session_id, scope.investigation_id, scope.version, step)
            conn.execute(
                """INSERT INTO analyst_meta.evidence (session_id,investigation_id,version,step,id,payload)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (session_id,investigation_id,version,step) DO NOTHING""",
                (*key, saved.id, Jsonb(saved.model_dump(mode='json'))),
            )
            row = conn.execute(
                """SELECT payload FROM analyst_meta.evidence
                   WHERE session_id=%s AND investigation_id=%s AND version=%s AND step=%s""", key,
            ).fetchone()
            existing = self._read(row, scope)
            if existing.checksum != saved.checksum:
                raise ValueError('Step already has different evidence')
            return existing

    @contextmanager
    def meter(self, scope, budget):
        key = (scope.session_id, scope.investigation_id)
        with self.connect() as conn:
            deadline = datetime.fromtimestamp(time.time() + 120 - (time.monotonic() - budget.started), timezone.utc)
            with self.authorized(conn, scope):
                conn.execute(
                    """INSERT INTO analyst_meta.budgets VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (session_id,investigation_id) DO NOTHING""",
                    (*key, deadline, budget.statements, budget.tools, budget.repairs, budget.tokens_reserved),
                )
                row = conn.execute(
                    'SELECT * FROM analyst_meta.budgets WHERE session_id=%s AND investigation_id=%s', key,
                ).fetchone()
            budget.started = time.monotonic() - 120 + (row['deadline'].timestamp() - time.time())
            budget.statements, budget.tools, budget.repairs, budget.tokens_reserved = (
                row[k] for k in ('statements','tools','repairs','tokens')
            )

            def persist():
                with self.authorized(conn, scope):
                    conn.execute(
                        """UPDATE analyst_meta.budgets SET statements=%s,tools=%s,repairs=%s,tokens=%s
                           WHERE session_id=%s AND investigation_id=%s""",
                        (budget.statements, budget.tools, budget.repairs, budget.tokens_reserved, *key),
                    )
            budget.persist = persist
            try:
                yield
            finally:
                budget.persist = None
