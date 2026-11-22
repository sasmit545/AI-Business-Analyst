"""Install durable analyst storage on the existing dedicated PostgreSQL server."""
import os
from pathlib import Path
import re
import secrets

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver

import postgres_phase1 as pg


SCHEMA_DDL = pg.ROOT / 'database/analyst'
WRITER_SECRET = pg.ROOT / '.local/analyst/writer_password'


def writer_password(role_exists):
    if not WRITER_SECRET.exists():
        if role_exists:
            raise RuntimeError('Restore .local/analyst/writer_password for the existing writer role.')
        WRITER_SECRET.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(WRITER_SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            output.write(secrets.token_urlsafe(36))
    password = WRITER_SECRET.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password):
        raise ValueError('Unexpected writer credential format')
    return password


def install():
    pg.require_native()
    pg.check_server_identity()
    with psycopg.connect(host='127.0.0.1', port=pg.server_port(), dbname=pg.DATABASE, user='postgres',
                         password=(pg.LOCAL/'postgres_password').read_text().strip(), connect_timeout=5,
                         autocommit=True, row_factory=dict_row, prepare_threshold=0,
                         options='-c search_path=analyst_meta,pg_catalog') as conn:
        if pg.PGDATA.resolve() != Path(conn.execute('SHOW data_directory').fetchone()['data_directory']).resolve():
            raise RuntimeError('Unexpected PostgreSQL cluster')
        conn.execute('SELECT pg_advisory_lock(604201)')
        with conn.transaction():
            role = conn.execute("SELECT oid FROM pg_roles WHERE rolname='analyst_writer'").fetchone()
            password = writer_password(role is not None)
            if role is None:
                conn.execute('CREATE ROLE analyst_writer NOLOGIN')
            elif conn.execute('SELECT 1 FROM pg_auth_members WHERE member=%s OR roleid=%s',
                              (role['oid'], role['oid'])).fetchone():
                raise RuntimeError('Unexpected analyst_writer role membership')
            conn.execute('ALTER ROLE analyst_writer NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS')
            if role is None:
                verifier = conn.pgconn.encrypt_password(password.encode(), b'analyst_writer', b'scram-sha-256')
                conn.execute(sql.SQL('ALTER ROLE analyst_writer PASSWORD {}').format(sql.Literal(verifier.decode('ascii'))))
            conn.execute('REVOKE ALL ON DATABASE payments_analytics FROM analyst_writer')
            conn.execute('GRANT CONNECT ON DATABASE payments_analytics TO analyst_writer')
            conn.execute('REVOKE ALL ON SCHEMA public FROM analyst_writer')
            conn.execute('ALTER ROLE analyst_writer SET search_path = analyst_meta,pg_catalog')
            for fixture in pg.SCENARIOS:
                conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM analyst_writer').format(sql.Identifier(fixture)))
                conn.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM analyst_writer').format(sql.Identifier(fixture)))
            conn.execute((SCHEMA_DDL/'metadata.sql').read_text(encoding='utf-8'), prepare=False)
            for ddl in sorted(SCHEMA_DDL.glob('*.sql')):
                if ddl.name != 'metadata.sql':
                    conn.execute(ddl.read_text(encoding='utf-8'), prepare=False)
        # The pinned saver runs CREATE INDEX CONCURRENTLY. Setup must run as
        # the DDL owner in autocommit mode, with its unqualified names scoped.
        if conn.execute('SELECT current_schema() AS name').fetchone()['name'] != 'analyst_meta':
            raise RuntimeError('Metadata migration search path is invalid')
        PostgresSaver(conn).setup()
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(604202)')
            selected = pg.selected_scenario()
            conn.execute("""INSERT INTO analyst_meta.control (scenario,generation,import_epoch,ready)
                            SELECT %s,1,1,rolcanlogin FROM pg_roles WHERE rolname='ai_analyst'
                            ON CONFLICT (singleton) DO NOTHING""", (selected,))
            stored = conn.execute('SELECT scenario, ready FROM analyst_meta.control WHERE singleton').fetchone()
            if stored is None or stored['scenario'] != selected:
                raise RuntimeError('Selection mismatch. Run the administrative select command before restarting setup.')
            conn.execute('REVOKE ALL ON ALL TABLES IN SCHEMA analyst_meta FROM PUBLIC, ai_analyst, analyst_writer')
            conn.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA analyst_meta TO analyst_writer')
            conn.execute('REVOKE INSERT,UPDATE,DELETE ON analyst_meta.control,analyst_meta.checkpoint_migrations FROM analyst_writer')
            conn.execute('ALTER ROLE analyst_writer LOGIN')
    # Verify the stored credential without writing it into output or the command line.
    with psycopg.connect(host='127.0.0.1', port=pg.server_port(), dbname=pg.DATABASE, user='analyst_writer',
                         password=password, connect_timeout=5) as writer:
        writer.execute('SELECT generation FROM analyst_meta.control WHERE singleton').fetchone()
    return selected


if __name__ == '__main__':
    selected = install()
    print(f'Private analyst metadata installed. Selected fixture: {selected}.')
