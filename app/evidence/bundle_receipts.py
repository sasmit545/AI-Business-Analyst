"""Complete, scope-bound results from one read-only fixture transaction."""
import hashlib
import json

from psycopg.types.json import Jsonb

from app.query.executor import BudgetExceeded


def digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) > 1024 * 1024:
        raise BudgetExceeded('Bundle receipt exceeds result size limit')
    return hashlib.sha256(encoded).hexdigest()


class BundleReceipt:
    def __init__(self, store, scope, request, parent, budget):
        self.store, self.scope = store, scope
        self.key = (scope.session_id, scope.investigation_id, scope.version)
        self.contract = {'scope':scope.model_dump(mode='json'), 'request':request.model_dump(mode='json'),
                         'parent':{'id':parent.id, 'checksum':parent.checksum} if parent else None}
        with store.connect() as conn, store.authorized(conn, scope) as authority:
            self.authority = dict(authority)
            conn.execute(
                """INSERT INTO analyst_meta.bundles
                   (session_id,investigation_id,version,request,generation,import_epoch,initial_statements)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (session_id,investigation_id,version) DO NOTHING""",
                (*self.key, Jsonb(self.contract), authority['generation'], authority['import_epoch'], budget.statements),
            )
            row = conn.execute("""SELECT * FROM analyst_meta.bundles WHERE session_id=%s
                                  AND investigation_id=%s AND version=%s""", self.key).fetchone()
        if row['request'] != self.contract or any(row[k] != v for k,v in self.authority.items()):
            raise ValueError('Saved bundle contract differs from current authorization or request')
        self.initial_statements = row['initial_statements']
        self.replay = row['receipt']
        if self.replay is None:
            if self.initial_statements != budget.statements:
                raise BudgetExceeded('Interrupted SQL bundle has charges but no complete result receipt')
        else:
            if (digest(self.replay) != row['digest'] or self.replay['contract'] != self.contract
                    or self.replay['authority'] != self.authority
                    or self.replay['initial_statements'] != self.initial_statements
                    or not self.replay['snapshot']):
                raise ValueError('Saved SQL bundle integrity failed')
            self.check_charges(self.replay['queries'], budget)

    def check_charges(self, records, budget):
        # BEGIN, SET LOCAL and snapshot identification were charged before all query records.
        if self.initial_statements + 3 + len(records) != budget.statements or budget.statements > 12:
            raise ValueError('SQL bundle does not match durable charges')

    def seal(self, snapshot, records, budget):
        self.check_charges(records, budget)
        payload = {'contract':self.contract, 'authority':self.authority, 'snapshot':snapshot,
                   'initial_statements':self.initial_statements,
                   'queries':[record.model_dump(mode='json') for record in records]}
        signature = digest(payload)
        with self.store.connect() as conn, self.store.authorized(conn, self.scope):
            saved = conn.execute(
                """UPDATE analyst_meta.bundles SET receipt=%s,digest=%s WHERE session_id=%s
                   AND investigation_id=%s AND version=%s AND receipt IS NULL RETURNING 1""",
                (Jsonb(payload), signature, *self.key),
            ).fetchone()
            if not saved:
                raise ValueError('SQL bundle was already sealed')
