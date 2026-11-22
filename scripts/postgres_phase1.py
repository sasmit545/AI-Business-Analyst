"""Manage one native PostgreSQL database with isolated Phase 1-3 fixtures."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

import validate_phase1 as source
import validate_phase2 as phase2
import validate_phase3 as phase3

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/synthetic/phase1'
EVALUATION = ROOT / 'evaluation/phase1'
SQL = ROOT / 'database/phase1'
LOCAL = ROOT / '.local/postgres'
REPORTS = ROOT / 'reports'
PHASE1_SCENARIOS = ('scenario_a', 'scenario_b', 'scenario_a_dirty')
PHASE2_SCENARIOS = {'phase2_baseline': 'baseline', 'phase2_incident': 'incident'}
SCENARIOS = (*PHASE1_SCENARIOS, *PHASE2_SCENARIOS, 'lifecycle_v1')
TABLES = ('merchants', 'banks', 'payments')
DATABASE = 'payments_analytics'
PG_VERSION = '18.7-1'
ARCHIVE_URL = f'https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-windows-x64-binaries.zip'
BIN = LOCAL / 'runtime/pgsql/bin'
PGDATA = LOCAL / 'pgdata'


class DependencyUnavailable(RuntimeError):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def require_scenario(value):
    if value not in SCENARIOS:
        raise ValueError(f'Unknown scenario: {value!r}')
    return value


def source_hashes():
    paths = sorted(list(DATA.rglob('*.csv')) + list(EVALUATION.iterdir()))
    return {p.relative_to(ROOT).as_posix(): source.sha256(p) for p in paths if p.is_file()}


def fixture_hashes():
    paths = sorted(list(phase2.data_dir(ROOT).rglob('*.csv')) + list(phase2.EVALUATION.iterdir()))
    paths += sorted(list(phase3.data_dir(ROOT).glob('*.csv')) + list(phase3.EVALUATION.iterdir()))
    return source_hashes() | {p.relative_to(ROOT).as_posix(): source.sha256(p) for p in paths if p.is_file()}


def data_path(schema):
    require_scenario(schema)
    if schema == 'lifecycle_v1':
        return phase3.data_dir(ROOT)
    if schema in PHASE2_SCENARIOS:
        return phase2.data_dir(ROOT) / PHASE2_SCENARIOS[schema]
    return DATA / schema


def expected_rows(schema):
    require_scenario(schema)
    if schema == 'lifecycle_v1':
        return read_json(phase3.EVALUATION / 'generation_manifest.json')['actual_attempts']
    if schema in PHASE2_SCENARIOS:
        return read_json(phase2.CONFIG)['attempts']
    return 20020 if schema.endswith('_dirty') else 20000


def scenario_literals():
    return '(' + ', '.join(sql_literal(schema) for schema in SCENARIOS) + ')'


def fields_for(schema):
    require_scenario(schema)
    return phase3.FIELDS if schema == 'lifecycle_v1' else source.SCHEMAS


def tables_for(schema):
    require_scenario(schema)
    return tuple(phase3.FIELDS) if schema == 'lifecycle_v1' else TABLES


def verify_sources():
    """Read existing fixtures/oracles only. Never call the generator or write evaluation files."""
    if source_hashes() != read_json(REPORTS / 'postgres_phase1_source_snapshot.json'):
        raise ValueError('A protected CSV or evaluation file changed from the original snapshot')
    errors = source.check_manifest(ROOT, read_json(EVALUATION / 'generation_manifest.json'))
    expected = read_json(EVALUATION / 'expected_answers.json')
    if expected['reference_sql_sha256'] != source.sha256(EVALUATION / 'reference.sql'):
        errors.append('Original reference SQL hash differs from saved ground truth')
    tables = {schema: source.load_tables(DATA / schema) for schema in PHASE1_SCENARIOS}
    for schema in PHASE1_SCENARIOS[:2]:
        metrics = source.reference_metrics(tables[schema])
        errors.extend(source.check_specification(schema, tables[schema], metrics))
        if metrics != expected['scenarios'][schema]:
            errors.append(f'{schema}: existing CSV SQL results differ from saved answers')
    _, dirty_errors = source.check_dirty(tables['scenario_a'], tables['scenario_a_dirty'],
                                         read_json(EVALUATION / 'defect_manifest.json'))
    errors.extend(dirty_errors)
    if errors:
        raise ValueError('\n'.join(errors))
    phase2_report, _ = phase2.validate(write_report=False)
    if phase2_report['dataset_gate'] != 'passed':
        raise ValueError('Phase 2 source verification failed: ' + '; '.join(phase2_report['errors']))
    tables.update({schema: source.load_tables(data_path(schema)) for schema in PHASE2_SCENARIOS})
    phase3_report, _ = phase3.validate(write_report=False)
    if phase3_report['dataset_gate'] != 'passed':
        raise ValueError('Phase 3 source verification failed: ' + '; '.join(phase3_report['errors']))
    tables['lifecycle_v1'] = phase3.load_tables(data_path('lifecycle_v1'))
    return tables


def init_secrets():
    LOCAL.mkdir(parents=True, exist_ok=True)
    for name in ('postgres_password', 'ai_password'):
        path = LOCAL / name
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                stream.write(secrets.token_urlsafe(36))
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', path.read_text(encoding='ascii').strip()):
            raise ValueError(f'{path.name} must be a 32-128 character URL-safe secret')


def sql_literal(value):
    value = value.as_posix() if isinstance(value, Path) else str(value)
    return "'" + value.replace("'", "''") + "'"


def run_native(program, *args, input_text=None, env=None, check=True, timeout=120):
    executable = BIN / f'{program}.exe'
    if not executable.is_file():
        raise DependencyUnavailable('Native PostgreSQL is not installed. Run: python -B scripts/postgres_analytics.py install')
    command = [str(executable), *map(str, args)]
    result = subprocess.run(command, cwd=ROOT, input=input_text, encoding='utf-8',
                            capture_output=True, env=env, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        for name in ('postgres_password', 'ai_password'):
            path = LOCAL / name
            if path.is_file():
                message = message.replace(path.read_text(encoding='ascii').strip(), '[REDACTED]')
        raise RuntimeError(f'PostgreSQL command failed: {message}')
    return result


def require_native():
    if os.name != 'nt':
        raise DependencyUnavailable('This setup uses native Windows PostgreSQL binaries. Run it in Windows PowerShell.')
    for program in ('postgres', 'psql', 'pg_ctl', 'initdb'):
        if not (BIN / f'{program}.exe').is_file():
            raise DependencyUnavailable('Native PostgreSQL binaries are missing; run postgres_analytics.py install')
    return run_native('postgres', '--version').stdout.strip()


def extract_binaries(archive_path, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f'Unsafe archive path: {entry.filename}')
        archive.extractall(destination)


def install_native():
    if os.name != 'nt':
        raise DependencyUnavailable('Run this installer in Windows PowerShell, not WSL.')
    if (BIN / 'postgres.exe').is_file():
        return require_native()
    downloads = LOCAL / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / f'postgresql-{PG_VERSION}-windows-x64-binaries.zip'
    if not archive.is_file():
        partial = archive.with_suffix('.zip.part')
        print('Downloading official PostgreSQL Windows binaries...', flush=True)
        try:
            with urllib.request.urlopen(ARCHIVE_URL, timeout=45) as response, partial.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
        except (urllib.error.URLError, OSError) as error:
            raise DependencyUnavailable(
                f'Cannot download PostgreSQL: {error}. Run the same install command in your normal '
                'PowerShell window, outside this restricted session.') from error
        if not zipfile.is_zipfile(partial):
            raise ValueError('Download is not a PostgreSQL ZIP archive')
        partial.replace(archive)
    extract_binaries(archive, LOCAL / 'runtime')
    version = require_native()
    save_json(REPORTS / 'postgres_native_install.json',
              {'version': version, 'source_url': ARCHIVE_URL, 'archive_sha256': source.sha256(archive),
               'binary_directory': str(BIN), 'installation': 'project-local native Windows binaries'})
    return version


def server_port():
    config = LOCAL / 'native_config.json'
    saved = read_json(config)['port'] if config.is_file() else None
    port = int(os.environ.get('PAYMENTS_POSTGRES_PORT', saved or 5432))
    if not 1024 <= port <= 65535:
        raise ValueError('PAYMENTS_POSTGRES_PORT must be between 1024 and 65535')
    if saved is not None and port != saved:
        raise ValueError(f'Existing project cluster uses port {saved}; remove the conflicting environment override')
    return port


def start_server():
    require_native()
    init_secrets()
    port = server_port()
    if (PGDATA / 'PG_VERSION').is_file():
        # A restricted process token may not inspect the user's server process.
        # A successful connection plus the data-directory check is authoritative.
        probe = psql('SELECT 1;', database='postgres', check=False)
        if probe.returncode == 0:
            check_server_identity()
            save_json(LOCAL / 'native_config.json', {'port': port, 'data_directory': str(PGDATA)})
            return
    if not (PGDATA / 'PG_VERSION').is_file():
        run_native('initdb', '-D', PGDATA, '-U', 'postgres', '--encoding=UTF8', '--locale=C',
                   '--auth=scram-sha-256', '--pwfile', LOCAL / 'postgres_password')
    status = run_native('pg_ctl', 'status', '-D', PGDATA, check=False)
    if status.returncode:
        run_native('pg_ctl', 'start', '-D', PGDATA, '-l', LOCAL / 'server.log', '-w', '-t', '60',
                   '-o', f"-h 127.0.0.1 -p {port}", timeout=75)
    check_server_identity()
    save_json(LOCAL / 'native_config.json', {'port': port, 'data_directory': str(PGDATA)})


def check_server_identity():
    actual = psql('SHOW data_directory;', database='postgres').stdout.strip()
    if Path(actual).resolve() != PGDATA.resolve():
        raise RuntimeError('Connected server is not the dedicated project cluster; refusing to change it')


def create_database():
    exists = psql("SELECT 1 FROM pg_database WHERE datname = 'payments_analytics';", database='postgres')
    if exists.stdout.strip() != '1':
        psql('CREATE DATABASE payments_analytics OWNER postgres;', database='postgres')


def psql(statement, *, analyst=False, database=DATABASE, check=True, timeout=120):
    password_path = LOCAL / ('ai_password' if analyst else 'postgres_password')
    if not password_path.is_file():
        raise RuntimeError('Credentials are absent; run: python -B scripts/postgres_analytics.py init')
    env = os.environ.copy()
    env['PGPASSWORD'] = password_path.read_text(encoding='ascii').strip()
    env['PGCLIENTENCODING'] = 'UTF8'
    env['PGCONNECT_TIMEOUT'] = '10'
    return run_native('psql', '-X', '-q', '-A', '-t', '-w', '-h', '127.0.0.1', '-p', str(server_port()),
                   '-U', 'ai_analyst' if analyst else 'postgres', '-d', database,
                   '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose',
                   input_text=statement, env=env, check=check, timeout=timeout)


def query_json(query, *, schema=None, analyst=False):
    prefix = '' if schema is None else f'SET search_path = pg_catalog, {require_scenario(schema)};\n'
    result = psql(prefix + "SELECT coalesce(json_agg(row_to_json(result)), '[]'::json) FROM (\n"
                  + query.strip().rstrip(';') + '\n) result;', analyst=analyst)
    return json.loads(result.stdout)


def bootstrap():
    password = (LOCAL / 'ai_password').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password):
        raise ValueError('Invalid local secret format')
    preamble = """
SELECT pg_advisory_lock(604201);
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_analyst') THEN
    CREATE ROLE ai_analyst NOLOGIN;
  END IF;
END $$;
ALTER ROLE ai_analyst NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
"""
    preamble += metadata_update('generation = generation + 1, ready = false')
    preamble += '\nCOMMIT;\n' + TERMINATE_ANALYST
    statements = ['BEGIN;', "SET password_encryption = 'scram-sha-256';",
                  f"ALTER ROLE ai_analyst PASSWORD '{password}';",
                  'REVOKE ALL ON DATABASE payments_analytics FROM PUBLIC, ai_analyst;',
                  'REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC, ai_analyst;',
                  'GRANT CONNECT ON DATABASE payments_analytics TO ai_analyst;',
                  'REVOKE ALL ON SCHEMA public FROM PUBLIC, ai_analyst;',
                  'REVOKE EXECUTE ON FUNCTION pg_catalog.lo_create(oid), pg_catalog.lo_creat(integer), '
                  'pg_catalog.lo_from_bytea(oid, bytea) FROM PUBLIC, ai_analyst;',
                  "ALTER ROLE ai_analyst SET default_transaction_read_only = on;",
                  "ALTER ROLE ai_analyst SET statement_timeout = '15s';",
                  "ALTER ROLE ai_analyst SET idle_in_transaction_session_timeout = '30s';",
                  "ALTER ROLE ai_analyst SET timezone = 'Asia/Kolkata';",
                  "ALTER ROLE ai_analyst SET search_path = pg_catalog;"]
    memberships = query_json("SELECT parent.rolname FROM pg_auth_members m "
                            "JOIN pg_roles parent ON parent.oid = m.roleid "
                            "JOIN pg_roles child ON child.oid = m.member WHERE child.rolname = 'ai_analyst'")
    if memberships:
        psql(preamble)
        raise RuntimeError('ai_analyst has unexpected role memberships; login disabled. Remove memberships before setup.')
    for schema in SCENARIOS:
        if schema == 'lifecycle_v1':
            statements.append((ROOT / 'database/phase3/tables.sql').read_text(encoding='utf-8'))
            continue
        sql_dir = ROOT / 'database/phase2' if schema in PHASE2_SCENARIOS else SQL
        constraints = '' if schema.endswith('_dirty') else (sql_dir / 'clean_constraints.sql').read_text(encoding='utf-8')
        ddl = (SQL / 'tables.sql').read_text(encoding='utf-8')
        statements.append(ddl.replace('{{clean_constraints}}', constraints).replace('{{schema}}', schema))
    statements.append('COMMIT;')
    psql(preamble + '\n' + '\n'.join(statements))


TERMINATE_ANALYST = "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity WHERE usename = 'ai_analyst';"


def metadata_update(assignments, predicate='true'):
    """Run a coordinated fence only when durable metadata has been installed."""
    return f"""
DO $$ BEGIN
  IF to_regclass('analyst_meta.control') IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(604202);
    UPDATE analyst_meta.control SET {assignments} WHERE singleton AND ({predicate});
  END IF;
END $$;"""


def ingestion_sql():
    names = [f'{schema}.{table}' for schema in SCENARIOS for table in tables_for(schema)]
    # Hold one session lock across both commits. The new epoch becomes visible
    # before any table is replaced. A failed COPY rolls back all fixture rows
    # and leaves recovery fenced until a successful administrative selection.
    statements = ['BEGIN;', 'SELECT pg_advisory_lock(604201);',
                  metadata_update('import_epoch = import_epoch + 1, ready = false'),
                  'COMMIT;', TERMINATE_ANALYST, 'BEGIN;', 'SET LOCAL lock_timeout = \'15s\';',
                  'TRUNCATE TABLE ' + ', '.join(names) + ';']
    for schema in SCENARIOS:
        for table in tables_for(schema):
            fields = ', '.join(fields_for(schema)[table])
            path = sql_literal(data_path(schema) / f'{table}.csv')
            statements.append(f"COPY {schema}.{table} ({fields}) FROM {path} "
                              f"WITH (FORMAT csv, HEADER MATCH, ENCODING 'UTF8', FORCE_NOT_NULL ({fields}));")
    statements.extend([metadata_update('ready = true', "(SELECT rolcanlogin FROM pg_roles WHERE rolname = 'ai_analyst')"),
                       'COMMIT;'])
    return '\n'.join(statements)


def ingest():
    before = fixture_hashes()
    verify_sources()
    print('Source verification passed; copying 23 managed tables...', flush=True)
    # COPY checks several relational constraints per lifecycle row. Allow the
    # atomic bulk load to finish on a local Windows disk; analyst timeout stays 15s.
    psql(ingestion_sql(), timeout=600)
    if fixture_hashes() != before:
        raise RuntimeError('Protected sources changed during ingestion')


def selection_sql(scenario):
    scenario = require_scenario(scenario)
    statements = ['SELECT pg_advisory_lock(604201);', 'BEGIN;', 'ALTER ROLE ai_analyst NOLOGIN;',
                  metadata_update('generation = generation + 1, ready = false'),
                  'COMMIT;', TERMINATE_ANALYST, 'BEGIN;']
    for schema in SCENARIOS:
        statements.extend([f'REVOKE ALL ON SCHEMA {schema} FROM ai_analyst;',
                           f'REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM ai_analyst;'])
    statements.extend([f'GRANT USAGE ON SCHEMA {scenario} TO ai_analyst;',
                       'GRANT SELECT ON ' + ', '.join(f'{scenario}.{table}' for table in tables_for(scenario)) + ' TO ai_analyst;',
                       f'ALTER ROLE ai_analyst SET search_path = pg_catalog, {scenario};',
                       metadata_update(f"scenario = '{scenario}', ready = true"),
                       'ALTER ROLE ai_analyst LOGIN;', 'COMMIT;'])
    return '\n'.join(statements)


def select_scenario(scenario):
    psql(selection_sql(scenario))


def selected_scenario():
    rows = query_json("SELECT nspname FROM pg_namespace WHERE nspname IN " + scenario_literals() + " "
                      "AND has_schema_privilege('ai_analyst', oid, 'USAGE') ORDER BY nspname")
    if len(rows) != 1:
        raise RuntimeError('ai_analyst must have USAGE on exactly one scenario; run select')
    return rows[0]['nspname']


def reference_queries(schema='scenario_a', parameters=None):
    require_scenario(schema)
    if schema == 'lifecycle_v1':
        params = parameters or phase3.parameters(read_json(phase3.CONFIG))
        queries = phase2.queries(ROOT / 'database/phase3/reference.sql')
        for name, query in queries.items():
            for parameter, value in params.items():
                query = query.replace(':' + parameter, sql_literal(value))
            queries[name] = query
        return queries
    sql_dir = ROOT / 'database/phase2' if schema in PHASE2_SCENARIOS else SQL
    parts = re.split(r'^-- query: (\w+)\s*$', (sql_dir / 'reference.sql').read_text(encoding='utf-8'), flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip().rstrip(';') for i in range(1, len(parts), 2)}


def row_hash(rows, fields):
    values = sorted(tuple(row[field] for field in fields) for row in rows)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def database_row_hashes():
    return {f'{schema}.{table}': row_hash(query_json(f'SELECT * FROM {schema}.{table}'), fields_for(schema)[table])
            for schema in SCENARIOS for table in tables_for(schema)}


def check_permissions(selected):
    require_scenario(selected)
    visible = query_json("SELECT table_schema, table_name FROM information_schema.tables "
                         "WHERE table_schema IN " + scenario_literals() + " "
                         "AND table_type = 'BASE TABLE' ORDER BY table_name", analyst=True)
    wanted = [{'table_schema': selected, 'table_name': t} for t in sorted(tables_for(selected))]
    if visible != wanted:
        raise ValueError(f'Analyst visibility differs from selected scenario tables: {visible}')
    count = query_json('SELECT count(*) AS rows FROM payments', analyst=True)[0]['rows']
    if count != expected_rows(selected):
        raise ValueError('Unqualified analyst query resolved to wrong scenario')
    roles = query_json("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit "
                       "FROM pg_roles WHERE rolname = current_user", analyst=True)
    if len(roles) != 1 or any(roles[0].values()):
        raise ValueError('Analyst has elevated role attributes')
    members = query_json("SELECT m.roleid FROM pg_auth_members m "
                         "JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = 'ai_analyst'")
    if members:
        raise ValueError('Analyst has unexpected role memberships')
    attacks = []
    for other in SCENARIOS:
        if other != selected:
            attacks.extend([f'SELECT * FROM {other}.payments LIMIT 1',
                            f'SET search_path = {other}; SELECT * FROM {other}.payments LIMIT 1',
                            f'SELECT a.attempt_id FROM {selected}.payments a JOIN {other}.payments b USING(attempt_id) LIMIT 1',
                            f"SELECT pg_read_file({sql_literal(data_path(other) / 'payments.csv')})"])
    attacks.extend([
        f'INSERT INTO {selected}.payments SELECT * FROM {selected}.payments LIMIT 1',
        f"UPDATE {selected}.payments SET currency = 'USD' WHERE false",
        f'DELETE FROM {selected}.payments WHERE false',
        f'TRUNCATE {selected}.payments',
        f'ALTER TABLE {selected}.payments ADD COLUMN forbidden text',
        f'DROP TABLE {selected}.payments',
        f'CREATE TABLE {selected}.forbidden (id integer)',
        'CREATE TABLE public.forbidden (id integer)',
        'CREATE TEMP TABLE forbidden (id integer)',
        'CREATE SCHEMA forbidden',
        'SET ROLE postgres',
        'SET ROLE pg_read_all_data',
        'SELECT lo_create(0)',
        'SELECT lo_creat(-1)',
        "SELECT lo_from_bytea(0, decode('00', 'hex'))",
        f"SELECT pg_read_file({sql_literal(LOCAL / 'postgres_password')})",
        f"SELECT pg_read_file({sql_literal(EVALUATION / 'expected_answers.json')})",
        f"SELECT pg_read_file({sql_literal(phase2.EVALUATION / 'expected_answers.json')})",
        f"SELECT pg_read_file({sql_literal(phase3.EVALUATION / 'expected_answers.json')})",
        f"COPY {selected}.payments TO PROGRAM 'cmd /c exit 0'",
    ])
    for attack in attacks:
        result = psql('BEGIN; SET TRANSACTION READ WRITE;\n' + attack + ';\nROLLBACK;',
                      analyst=True, check=False)
        if result.returncode == 0 or '42501' not in result.stderr:
            raise ValueError(f'Expected permission denial (42501) for: {attack}\n{result.stderr}')
    for database in ('postgres', 'template1'):
        denied = psql('SELECT 1;', analyst=True, database=database, check=False)
        if denied.returncode == 0 or 'permission denied' not in denied.stderr.lower():
            raise ValueError(f'Analyst can connect to auxiliary database {database}, or check failed unexpectedly')
    return {'selected_schema': selected, 'visible_tables': len(tables_for(selected)),
            'denied_statements': len(attacks), 'auxiliary_databases_denied': 2}


def validate_database():
    before = fixture_hashes()
    original = verify_sources()
    expected = read_json(EVALUATION / 'expected_answers.json')['scenarios']
    phase2_expected = read_json(phase2.EVALUATION / 'expected_answers.json')
    expected.update({schema: phase2_expected['variants'][variant] for schema, variant in PHASE2_SCENARIOS.items()})
    expected['lifecycle_v1'] = read_json(phase3.EVALUATION / 'expected_answers.json')['metrics']
    report = {'status': 'failed', 'database': DATABASE, 'scenarios': {}, 'source_files_unchanged': False}
    version = query_json('SELECT version() AS version')[0]['version']
    report['postgres_version'] = version
    for schema in SCENARIOS:
        print(f'Checking database records and SQL answers: {schema}', flush=True)
        loaded = {table: query_json(f'SELECT * FROM {schema}.{table}') for table in tables_for(schema)}
        hashes = {}
        for table in tables_for(schema):
            fields = fields_for(schema)[table]
            if Counter(tuple(r[f] for f in fields) for r in loaded[table]) != Counter(
                    tuple(r[f] for f in fields) for r in original[schema][table]):
                raise ValueError(f'{schema}.{table}: database records differ from CSV, including duplicate multiplicity')
            hashes[table] = row_hash(loaded[table], fields)
        if schema == 'lifecycle_v1':
            quality = phase3.check_quality(loaded, read_json(phase3.CONFIG))
            if quality:
                raise ValueError(f'PostgreSQL lifecycle integrity failed: {quality}')
        observed_quality = query_json((SQL / 'quality.sql').read_text(encoding='utf-8'), schema=schema)[0]
        target = {'rows': expected_rows(schema), 'duplicate_occurrences': 0, 'missing_timestamps': 0,
                  'orphan_merchants': 0, 'orphan_banks': 0}
        if schema.endswith('_dirty'):
            target.update(rows=20020, duplicate_occurrences=20, missing_timestamps=10, orphan_merchants=10)
            _, errors = source.check_dirty(original['scenario_a'], loaded,
                                            read_json(EVALUATION / 'defect_manifest.json'))
            if errors:
                raise ValueError('\n'.join(errors))
            metrics = None
        else:
            metrics = {name: query_json(query, schema=schema) for name, query in reference_queries(schema).items()}
            if metrics != expected[schema]:
                differing = [name for name in expected[schema] if metrics.get(name) != expected[schema][name]]
                raise ValueError(f'{schema}: PostgreSQL differs from saved ground truth in {differing}')
        if observed_quality != target:
            raise ValueError(f'{schema}: wrong database quality results: {observed_quality}')
        report['scenarios'][schema] = {'quality': observed_quality, 'record_hashes': hashes,
                                       'analysis_status': 'blocked' if metrics is None else 'allowed',
                                       'ground_truth_sections_matched': 0 if metrics is None else len(metrics),
                                       'periods': None if metrics is None else metrics['periods']}
    paired = {name: query_json(query) for name, query in phase2.queries(ROOT / 'database/phase2/paired_reference.sql').items()}
    if paired != phase2_expected['paired']:
        raise ValueError('PostgreSQL paired Phase 2 results differ from independent ground truth')
    report['phase2_paired_summary'] = paired['summary']
    report['permissions'] = check_permissions(selected_scenario())
    report['source_files_unchanged'] = fixture_hashes() == before
    if not report['source_files_unchanged']:
        raise RuntimeError('Protected files changed during validation')
    report['status'] = 'passed'
    save_json(REPORTS / 'postgres_analytics_validation.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'install', 'setup', 'start', 'stop', 'status',
                                           'ingest', 'select', 'validate', 'test'))
    parser.add_argument('--scenario', choices=SCENARIOS, default='lifecycle_v1')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            init_secrets()
            print('Local credentials initialized in .local/postgres/; existing secrets preserved.')
            return 0
        if args.command == 'install':
            print(install_native())
            save_json(REPORTS / 'postgres_analytics_last_run.json',
                      {'status': 'passed', 'command': 'install', 'live_database_verified': False})
            return 0
        if args.command == 'setup':
            print('Verifying existing CSVs and independent ground truths...', flush=True)
            verify_sources()
            install_native()
            init_secrets()
            start_server()
            create_database()
            print('Preparing isolated schemas and permissions...', flush=True)
            bootstrap()
            print('Importing existing CSVs in one transaction...', flush=True)
            ingest()
            select_scenario(args.scenario)
            print('Validating imported rows, SQL answers and analyst permissions...', flush=True)
            validate_database()
        elif args.command in ('start', 'stop', 'status'):
            require_native()
            if args.command == 'start':
                start_server()
            elif args.command == 'status':
                check_server_identity()
                print(f'Project PostgreSQL is reachable at 127.0.0.1:{server_port()} ({PGDATA}).')
            else:
                extra = ('-m', 'fast', '-w') if args.command == 'stop' else ()
                result = run_native('pg_ctl', args.command, '-D', PGDATA, *extra)
                print(result.stdout.strip())
            return 0
        else:
            require_native()
            check_server_identity()
        if args.command == 'ingest':
            ingest()
            validate_database()
        elif args.command == 'select':
            select_scenario(args.scenario)
            check_permissions(args.scenario)
        elif args.command == 'validate':
            validate_database()
        elif args.command == 'test':
            before = fixture_hashes()
            env = os.environ.copy()
            env['PAYMENTS_POSTGRES_INTEGRATION'] = '1'
            result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'scripts',
                                     '-p', 'test_postgres_phase1.py', '-v'], cwd=ROOT, env=env)
            if result.returncode:
                raise RuntimeError('PostgreSQL test suite failed; see test output')
            if fixture_hashes() != before:
                raise RuntimeError('Tests changed protected sources')
            validate_database()
        save_json(REPORTS / 'postgres_analytics_last_run.json',
                  {'status': 'passed', 'command': args.command, 'live_database_verified': True})
        print(f'{args.command}: passed')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        status = {'status': 'blocked' if isinstance(error, DependencyUnavailable) else 'failed',
                  'command': args.command, 'error': str(error), 'live_database_verified': False}
        save_json(REPORTS / 'postgres_analytics_last_run.json', status)
        print(json.dumps(status, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(main())
