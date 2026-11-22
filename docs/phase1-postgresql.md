# Unified PostgreSQL on Windows

This setup uses native Windows PostgreSQL. Docker and WSL are not required.
It imports all 23 existing CSVs unchanged into one database, `payments_analytics`,
with six isolated schemas: `scenario_a`, `scenario_b`, `scenario_a_dirty`,
`phase2_baseline`, `phase2_incident`, and `lifecycle_v1`. Each schema holds one analytical population.

## Install and run

From a normal Windows PowerShell window:

```powershell
cd E:\pinelabs
python -B scripts/postgres_analytics.py setup
python -B scripts/postgres_analytics.py test
```

`setup` downloads the official EDB PostgreSQL 18.7 Windows binary ZIP when needed,
extracts it into `.local/postgres/runtime/`, initializes a dedicated cluster,
starts it, imports the existing CSVs, selects Phase 3 lifecycle, and validates the data
and permissions. The installer does not use winget, Docker, WSL, or a Windows
service. It writes only inside this project and does not need administrator
installation privileges. It does need outbound HTTPS to `get.enterprisedb.com`
and permission to execute the downloaded native programs.

If an agent session blocks network access with `WinError 10013`, run these commands
in your normal PowerShell window. That error means the download did not complete;
it is not proof of a PostgreSQL installation or a running database.

To install the binaries without starting or importing anything:

```powershell
python -B scripts/postgres_analytics.py install
```

The installer uses the [official Windows binary distribution](https://www.enterprisedb.com/download-postgresql-binaries).
It records the downloaded archive's SHA-256 and server version in
`reports/postgres_native_install.json`. This hash records the downloaded artifact;
it is not a separately published vendor-checksum verification.

## Files and connection

| Item | Location or value |
|---|---|
| Server/client executables | `.local/postgres/runtime/pgsql/bin/` |
| Persistent database files | `.local/postgres/pgdata/` |
| Server log | `.local/postgres/server.log` |
| Host | `127.0.0.1` |
| Default port | `5432` |
| Database | `payments_analytics` |
| AI user | `ai_analyst` |
| AI password | `.local/postgres/ai_password` |
| Administrator user | `postgres` |
| Administrator password | `.local/postgres/postgres_password` |

Passwords are random, stored locally, and excluded from Git. Existing passwords
are reused. Do not delete them while retaining the initialized cluster. The server
accepts loopback connections only and uses SCRAM password authentication.

If port 5432 is occupied, set a different port **before first setup**:

```powershell
$env:PAYMENTS_POSTGRES_PORT = '5433'
python -B scripts/postgres_analytics.py setup
```

The selected port is saved in `.local/postgres/native_config.json`. Later commands
reuse it; conflicting environment overrides are rejected. The script verifies the
connected server's data directory before changing an initialized database.

Connect as the AI user using a database client and the connection settings above.
For the included psql client (replace 5432 if configured differently):

```powershell
$env:PGPASSWORD = (Get-Content -Raw .local/postgres/ai_password).Trim()
try {
    & .local/postgres/runtime/pgsql/bin/psql.exe -h 127.0.0.1 -p 5432 -U ai_analyst -d payments_analytics
} finally {
    Remove-Item Env:PGPASSWORD
}
```

Example queries:

```sql
SELECT current_user;
SELECT count(*) FROM payments;
SELECT payment_method, count(*) FROM payments GROUP BY payment_method;
```

## Lifecycle and ingestion

```powershell
python -B scripts/postgres_analytics.py status
python -B scripts/postgres_analytics.py stop
python -B scripts/postgres_analytics.py start
python -B scripts/postgres_analytics.py ingest
python -B scripts/postgres_analytics.py validate
```

This is a background PostgreSQL process, not an automatically starting Windows
service. After a restart, use `start`. Stopping the server keeps the data. Starting
it does not reimport records. `setup` and `ingest` explicitly refresh this fixture.

Ingestion takes an advisory lock, truncates the 23 managed tables together, and
uses PostgreSQL COPY in one transaction. A failed import rolls back all tables.
It never regenerates CSVs, edits evaluation files, drops schemas, or uses CASCADE.
Existing readers may briefly block while the fixture is replaced.

Each earlier schema has `payments`, `merchants`, and `banks`. Phase 3 adds orders, payment_methods, failure_reasons, settlements and bank_health. Clean A and clean B each have
20,000 payments, 20 merchants, and five banks. Dirty A has 20,020 payments.
Phase 2 baseline and incident each have 100,000 payments, 20 merchants, and five banks.
No table or view combines the scenarios.

All fields are stored as text to retain the exact CSV values, including `+05:30`
and empty strings. COPY's FORCE_NOT_NULL preserves blanks as empty strings.
Clean payments enforce primary/foreign keys and checks for dates, amounts,
currency, methods, and outcomes. Dirty payments intentionally omit those clean
constraints; corrupt records are preserved. Dimensions retain their primary keys.

For arithmetic, use `amount_paise::numeric`. For timestamp operations, use
`NULLIF(attempted_at, '')::timestamptz` after quality checks. Local date grouping
uses `substr(attempted_at, 1, 10)` to match the existing benchmark.

## Scenario isolation and read-only access

Only the administrator changes the selected scenario (setup defaults to lifecycle_v1):

```powershell
python -B scripts/postgres_analytics.py select --scenario lifecycle_v1
python -B scripts/postgres_analytics.py select --scenario phase2_incident
python -B scripts/postgres_analytics.py select --scenario phase2_baseline
python -B scripts/postgres_analytics.py select --scenario scenario_a
python -B scripts/postgres_analytics.py select --scenario scenario_b
python -B scripts/postgres_analytics.py select --scenario scenario_a_dirty
```

Selection disables new AI logins, terminates existing AI sessions, revokes the
previous grants, grants USAGE/SELECT on exactly the selected scenario tables, updates
search_path, and re-enables login. Reconnect clients after switching. The selection
is global for this one AI role.

The AI has no elevated role attributes or memberships. Cross-schema reads, writes,
DDL, temporary tables, role escalation, server-file reads, program execution, and
large-object creation are denied. Default read-only transactions and query timeouts
are additional defaults; live tests turn read-only mode off to verify that table
privileges still deny writes. PostgreSQL catalogs may reveal schema/table names;
record isolation does not imply complete metadata invisibility.

Dirty A is only for quality-failure testing. Validation detects its defects and
omits certified business metrics. The database still allows SELECT on dirty A when
selected; the future analyst application must gate business conclusions on quality
checks. No AI application is implemented here.

## Ground truths and validation

Ground truths remain outside PostgreSQL in `evaluation/phase1/`, `evaluation/phase2/` and `evaluation/phase3/`.
All original Phase 1 artifacts are unchanged. No
answer tables, stored functions, views, or comments are created to expose them.
The native server runs under the Windows account starting it, so operating-system
access to this workspace is administrative access. The future AI runtime must have
only its restricted database connection, with no host filesystem/shell access or
administrator credentials. Application sandboxing is not implemented here.

`database/phase1/reference.sql` runs PostgreSQL queries over each clean schema and
compares all ten result sections against the existing expected answers. The
original SQLite reference SQL is preserved. Imported records are compared as
complete-row multisets against the CSVs, including duplicate multiplicity. Dirty
record IDs are checked against the existing defect manifest.

`database/phase2/reference.sql` compares 16 result sections per variant, including
local hour/weekday standardized rates, with the independent saved SQLite answers.
Its paired reference SQL compares both variants only through the administrator
connection; no cross-scenario view is created or granted to the analyst. The
[Phase 2 guide](phase2-usage.md) describes ground-truth generation and scoring.

```powershell
# Existing-source checks only; live tests are explicitly skipped.
python -B -m unittest discover -s scripts -p test_postgres_phase1.py -v

# Requires native PostgreSQL and initialized data; fails if unavailable.
python -B scripts/postgres_analytics.py test
```

Live tests check exact rates and allocations, row preservation, dirty defects,
repeat imports, rollback after a failed COPY, clean constraints, and permission
denials for all six selections. Permission probes roll back their transactions.
The suite restores the previous selection and validates again after passing.

Reports are separate from the original evaluation files:

- `postgres_phase1_source_snapshot.json`: hashes of the original nine CSVs and five evaluation files.
- `postgres_native_install.json`: successful installation/version evidence.
- `postgres_analytics_validation.json`: written after successful live database validation.
- `postgres_analytics_last_run.json`: latest setup/import/selection/validation/test result or dependency failure.

The original `evaluation/phase1/validation_report.json` describes CSV validation,
not PostgreSQL. An offline test pass is not live database verification.

Future phases should add their own schema/import definitions under `database/`
without replacing this fixture. Do not point another PostgreSQL major version at
the existing data directory without a planned upgrade.

The file keeps its original name for existing links. `postgres_phase1.py` remains
a compatibility entry point for the same unified database controller; it does not
create a separate database. Native binaries are installed, all six schemas are loaded, and all 14 unified database tests passed. The final post-test validation also passed. See the latest reports for execution evidence.

Phase 3 adds 198,000 orders, 199,734 attempts, 193,948 settlements and 89,280 health
observations in lifecycle_v1. Its ten PostgreSQL query sections are compared with
independent SQLite answers; hand-fixture queries run in temporary tables during
tests. See [Phase 3 lifecycle usage](phase3-usage.md) for metrics and all eight tables.
