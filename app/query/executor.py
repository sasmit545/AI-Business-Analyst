"""Restricted connections and single-snapshot execution; no administrative imports."""
import hashlib
import json
import threading
import time
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings
from app.context.catalog import catalog
from app.context.dimensions import resolve_member
from app.contracts import QueryRecord
from app.query.policy import validate_sql


class StaleSession(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass
class Budget:
    started: float = field(default_factory=time.monotonic)
    statements: int = 0
    tools: int = 0
    repairs: int = 0
    tokens_reserved: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    persist: Callable[[], None] | None = field(default=None, repr=False)
    journal: object | None = field(default=None, repr=False)

    def record(self):
        if self.persist is not None:
            self.persist()

    def reserve_tokens(self, amount):
        self.tokens_reserved += amount
        self.record()

    def settle_tokens(self, reservation, actual):
        self.tokens_reserved += actual - reservation
        self.record()

    def check(self):
        if self.cancel.is_set():
            raise Cancelled('Investigation cancelled')
        if time.monotonic() - self.started >= 120:
            raise BudgetExceeded('Investigation time limit reached')

    def sql(self):
        self.check()
        self.statements += 1
        self.record()
        if self.statements > 12:
            raise BudgetExceeded('SQL statement limit reached')

    def tool(self):
        self.check()
        self.tools += 1
        self.record()
        if self.tools > 10:
            raise BudgetExceeded('Tool limit reached')


def connect(settings: Settings):
    return psycopg.connect(host='127.0.0.1', port=settings.db_port,
                          dbname='payments_analytics', user='ai_analyst',
                          password=settings.db_password.get_secret_value(),
                          connect_timeout=5, autocommit=True, row_factory=dict_row,
                          options='-c statement_timeout=10000')


def selected_schema(connection) -> str:
    identity = connection.execute('SELECT current_user AS role, current_database() AS db').fetchone()
    if identity != {'role': 'ai_analyst', 'db': 'payments_analytics'}:
        raise StaleSession('Unexpected database identity')
    rows = connection.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','pg_catalog') AND table_type='BASE TABLE'").fetchall()
    schemas = {r['table_schema'] for r in rows}
    if len(schemas) != 1:
        raise StaleSession('Exactly one selected schema is required')
    scenario = schemas.pop()
    if {r['table_name'] for r in rows} != set(catalog(scenario)['tables']):
        raise StaleSession('Selected table inventory changed')
    return scenario


def read_directory(connection, scenario, table, code, label):
    query = sql.SQL('SELECT {}, {} FROM {} LIMIT 2001').format(
        sql.Identifier(code), sql.Identifier(label), sql.Identifier(scenario, table))
    rows = connection.execute(query).fetchall()
    if len(rows) > 2000 or len(json.dumps(rows).encode()) > 1024 * 1024:
        raise BudgetExceeded(f'{table} directory exceeds the result size limit')
    return {row[code]: row[label] for row in rows}


def read_bank_directory(connection, scenario):
    return read_directory(connection, scenario, 'banks', 'bank_id', 'bank_name')


class Authorization:
    """The original connection is the non-reconnectable session generation."""
    def __init__(self, settings):
        self.connection = connect(settings)
        self.stale = False
        self.lock = threading.RLock()
        try:
            self.scenario = selected_schema(self.connection)
            self.banks = read_bank_directory(self.connection, self.scenario)
            selected = catalog(self.scenario)
            if 'payment_methods' in selected['tables']:
                self.methods = read_directory(self.connection, self.scenario, 'payment_methods', 'payment_method', 'label')
            else:
                self.methods = {code: code for code in selected['filter_values']['payment_method']}
        except Exception:
            self.connection.close()
            raise

    def resolve_merchant(self, value):
        # Search only matching members. A large merchant dimension need not fit in a result or model context.
        query = sql.SQL(
            'SELECT merchant_id, merchant_name FROM {} WHERE '
            'lower(merchant_id) = lower(%s) OR lower(merchant_name) = lower(%s) '
            'ORDER BY (merchant_id = %s) DESC, merchant_id LIMIT 7'
        ).format(sql.Identifier(self.scenario, 'merchants'))
        with self.lock:
            rows = self.connection.execute(query, (value.strip(), value.strip(), value)).fetchall()
        return resolve_member(value, {r['merchant_id']:r['merchant_name'] for r in rows}, 'merchant')

    def check(self):
        with self.lock:
            if self.stale:
                raise StaleSession('Session expired; start a new session')
            try:
                if selected_schema(self.connection) != self.scenario:
                    raise StaleSession('Selected scope changed')
            except Exception:
                self.close()
                raise StaleSession('Session expired; start a new session') from None

    def close(self):
        self.stale = True
        self.connection.close()


class Bundle:
    def __init__(self, settings, authorization, budget):
        self.settings, self.authorization, self.budget = settings, authorization, budget
        self.records = []
        self.connection = None

    def __enter__(self):
        self.authorization.check()
        self.journal = self.budget.journal
        self.replay = self.journal.replay if self.journal else None
        if self.replay is not None:
            self.snapshot = self.replay['snapshot']
            return self
        self.connection = connect(self.settings)
        try:
            if selected_schema(self.connection) != self.authorization.scenario:
                raise StaleSession('Scope changed')
            self.budget.sql()
            self.connection.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.budget.sql()
            self.connection.execute("SET LOCAL statement_timeout = '10s'")
            self.budget.sql()
            self.snapshot = self.connection.execute('SELECT pg_current_snapshot()::text AS snapshot').fetchone()['snapshot']
            return self
        except BaseException:
            self.connection.close()
            raise

    def query(self, name, sql, parameters=None):
        if self.replay is not None:
            self.budget.check()
            expected = self.replay['queries']
            if len(self.records) >= len(expected):
                raise ValueError('Saved SQL bundle is incomplete')
            record = QueryRecord.model_validate(expected[len(self.records)])
            if (record.name != name or record.sql != sql or record.parameters != (parameters or {})
                    or record.sql_sha256 != hashlib.sha256(sql.encode()).hexdigest()):
                raise ValueError('Registered SQL differs from the saved bundle')
            self.records.append(record)
            return deepcopy(record.rows)
        self.budget.sql()
        validate_sql(sql, self.authorization.scenario)
        started = time.monotonic()
        with self.connection.cursor() as cursor:
            cursor.execute(sql, parameters or {})
            rows = cursor.fetchmany(2001)
        if len(rows) > 2000 or len(json.dumps(rows, default=str).encode()) > 1024 * 1024:
            raise BudgetExceeded('Result size limit reached')
        self.budget.check()
        self.records.append(QueryRecord(name=name, sql=sql, parameters=parameters or {},
                                        rows=rows, elapsed_ms=(time.monotonic()-started)*1000,
                                        sql_sha256=hashlib.sha256(sql.encode()).hexdigest()))
        return rows

    def seal(self):
        if self.replay is not None:
            if len(self.records) != len(self.replay['queries']):
                raise ValueError('Registered analysis did not consume its complete saved SQL bundle')
        elif self.journal is not None:
            self.journal.seal(self.snapshot, self.records, self.budget)

    def __exit__(self, kind, value, traceback):
        try:
            if self.connection:
                self.connection.execute('ROLLBACK')
        finally:
            if self.connection:
                self.connection.close()
