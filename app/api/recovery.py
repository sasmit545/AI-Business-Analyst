"""Exclusive ownership of a saved session, including during checkpoint replay."""
from contextlib import contextmanager
from hashlib import sha256
import hmac
from threading import RLock
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.query.executor import StaleSession
from app.evidence.postgres_store import open_writer


def saved_sessions(settings, scenario):
    with open_writer(settings) as conn, conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock_shared(604202)')
        return conn.execute("""SELECT s.session_id, first_question.title, first_question.last_question_at
            FROM analyst_meta.sessions s JOIN analyst_meta.control c USING (scenario,generation,import_epoch)
            LEFT JOIN LATERAL (
                SELECT left(i.state->>'question', 100) AS title,
                       max((i.state->>'created_at')::double precision) OVER () AS last_question_at
                FROM analyst_meta.investigations i WHERE i.session_id=s.session_id
                ORDER BY (i.state->>'created_at')::double precision, i.investigation_id LIMIT 1
            ) first_question ON true
            WHERE c.ready AND NOT s.revoked AND s.subject='local-operator' AND s.scenario=%s
            ORDER BY last_question_at DESC NULLS LAST, s.session_id""", (scenario,)).fetchall()


class SessionLease:
    def __init__(self, settings, session_id, scenario, key, *, create, local_operator=False):
        self.id = session_id
        self.owner = uuid4().hex
        self.connection = open_writer(settings)
        self.lock = RLock()
        try:
            with self.connection.transaction():
                conn = self.connection
                conn.execute('SELECT pg_advisory_xact_lock_shared(604202)')
                control = conn.execute('SELECT * FROM analyst_meta.control WHERE ready').fetchone()
                if not control or control['scenario'] != scenario:
                    raise StaleSession('Database selection changed')
                if not create:
                    row = conn.execute('SELECT * FROM analyst_meta.sessions WHERE session_id=%s AND NOT revoked',
                                       (session_id,)).fetchone()
                    if not row or (not local_operator and
                                   not hmac.compare_digest(row['key_digest'], sha256(key.encode()).hexdigest())):
                        raise KeyError('Unknown saved session')
                    if (row['subject'] != 'local-operator' or any(row[k] != control[k]
                            for k in ('generation', 'import_epoch', 'scenario'))):
                        raise StaleSession('Saved session no longer authorized')
                acquired = conn.execute('SELECT pg_try_advisory_lock(604203, hashtext(%s)) AS held',
                                        (session_id,)).fetchone()['held']
                if not acquired:
                    raise ValueError('Session is already active')
                self.epoch = control['import_epoch']
                if create:
                    conn.execute("""INSERT INTO analyst_meta.sessions
                        (session_id,subject,scenario,generation,import_epoch,key_digest,owner_token)
                        VALUES (%s,'local-operator',%s,%s,%s,%s,%s)""",
                        (session_id, scenario, control['generation'], self.epoch, sha256(key.encode()).hexdigest(), self.owner))
                else:
                    conn.execute('UPDATE analyst_meta.sessions SET owner_token=%s WHERE session_id=%s',
                                 (self.owner, self.id))
        except BaseException:
            self.connection.close()
            raise

    @contextmanager
    def authorized(self):
        with self.lock:
            try:
                with self.connection.transaction():
                    conn = self.connection
                    conn.execute('SELECT pg_advisory_xact_lock_shared(604202)')
                    row = conn.execute("""SELECT 1 FROM analyst_meta.sessions s JOIN analyst_meta.control c
                        USING (scenario,generation,import_epoch)
                        WHERE c.ready AND NOT s.revoked AND s.subject='local-operator'
                          AND s.session_id=%s AND s.owner_token=%s""",
                        (self.id, self.owner)).fetchone()
                    if not row:
                        raise StaleSession('Saved scope is stale')
                    yield conn
            except psycopg.OperationalError:
                raise StaleSession('Session lease was interrupted') from None

    def save(self, *jobs):
        with self.authorized() as conn:
            for job in jobs:
                conn.execute("""INSERT INTO analyst_meta.investigations(session_id,investigation_id,state)
                              VALUES (%s,%s,%s) ON CONFLICT(session_id,investigation_id)
                              DO UPDATE SET state=EXCLUDED.state""",
                             (self.id, job.scope.investigation_id, Jsonb(job.saved_state())))

    def load(self):
        with self.authorized() as conn:
            return [row['state'] for row in conn.execute("""SELECT state FROM analyst_meta.investigations
                    WHERE session_id=%s ORDER BY state->>'created_at',investigation_id""", (self.id,))]

    def revoke(self):
        with self.authorized() as conn:
            conn.execute('UPDATE analyst_meta.sessions SET revoked=true WHERE session_id=%s', (self.id,))

    def close(self):
        self.connection.close()
