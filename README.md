# Enterprise AI Business Analyst

A local payments analyst that answers business questions using verified SQL results from synthetic payment data. Ask about payment success, order conversion, retries, settlements or bank health, then inspect the supporting charts, counts, filters and executed SQL. Conversations and evidence are saved in PostgreSQL and can be reopened after a restart.

The application uses FastAPI, Pydantic v2, LangGraph, SQLGlot, Psycopg 3, Streamlit and Plotly. The configured model is NVIDIA Nemotron (`nvidia/nemotron-3.5-super-vl-120b-a12b`). It runs on Windows with native PostgreSQL; Docker and WSL are not used.

## What the analyst does

- Compares completed-attempt success across periods, banks and payment methods, including daily trends, failure reasons and the contribution of traffic mix versus segment performance.
- Measures order conversion, first-attempt success, retry uptake, recovery among initially failed mature orders or the subset that retried, due settlement completion by count or amount, and aligned bank health in `lifecycle_v1`.
- Ranks findings for the business question. Failure volume, deterioration per attempt and contribution to overall change use different rankings. Recommendations cite the saved evidence and distinguish recorded outcomes from causal hypotheses.
- Supports contextual follow-ups, chart selections and structured changes to filters and dates. An action-only follow-up can reuse the parent's verified snapshot without additional analytical SQL; changed filters can require a new measurement.
- Saves sessions, clarification exchanges, answer history, evidence and execution budgets in local PostgreSQL. Select a conversation under **Saved sessions** to reopen it, then use **Chat history** to revisit earlier results.
- Checks raw data before certifying metrics. Blocking defects produce diagnostics instead of business conclusions. Bank filters resolve against the selected schema's bank directory; missing or ambiguous names require clarification.

Results show the selected dataset, denominator, comparison windows, filters and material caveats. **Show chart data as tables** exposes plotted values; **SQL, quality and provenance** exposes queries and bound parameters. Daily trend lines fit the observed values by default, while bar and area charts start at zero.

## Start the application

Use PowerShell from the repository root. For an existing installation, check the dedicated database and start it only if stopped:

```powershell
python -B scripts/postgres_analytics.py status
# Only when the database is stopped:
python -B scripts/postgres_analytics.py start

.\start-analyst.ps1
```

Open **http://127.0.0.1:8501** and select **Start new session**. The private API listens on `127.0.0.1:8000`. Both ports must be available before launching. Press Q or Ctrl+C in the launcher's terminal to stop the API and UI; PostgreSQL can remain running.

For a new comparison, include the metric, both periods and timezone. Explicit inclusive/exclusive date ranges bind exact midnight boundaries:

> Compare attempt success from 2026-10-01 inclusive to 2026-10-15 exclusive against 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. Which bank and payment method contributed most to the change?

Then use **Ask follow-up**:

> What steps should I take to address this?

Use **Filters, dates and comparisons** for structured changes, or **New question** for an independent analysis in the same session. See the [usage and recovery guide](docs/analyst-usage.md) for the full workflow.

### First-time setup

Requirements: Windows x64, PowerShell, Python 3.14 or later, and a valid NVIDIA API key with free credits. Installation needs network access for Python packages and the PostgreSQL binaries; model requests need access to NVIDIA's endpoint.

Create the analyst environment and install the locked dependencies:

```powershell
python -m venv .local/analyst/venv
.\.local\analyst\venv\Scripts\python.exe -m pip install -r requirements-analyst.lock
```

For a new database installation, run:

```powershell
python -B scripts/postgres_analytics.py setup
.\.local\analyst\venv\Scripts\python.exe scripts/setup_analyst_metadata.py
```

The database setup installs EDB PostgreSQL 18.7 locally, imports the existing CSVs into six isolated schemas, and selects `lifecycle_v1`. Metadata setup creates the private `analyst_meta` tables and a separate writer role in the same database. **`setup` and `ingest` replace the imported fixture tables.** Use `status` and `start` for normal operation on an existing installation. The old `postgres_phase1.py` command remains a compatibility entry point. See [native PostgreSQL installation and connections](docs/phase1-postgresql.md).

Add your key to the root `.env` file, preserving any existing settings:

```dotenv
NVIDIA_API_KEY=your_nvidia_api_key
```

The host loads `.env`; environment variables take precedence. Keep `.env` and `.local/` private; both are ignored by Git. Paid model usage remains disabled until a pricing and spending policy is implemented. After setup, run `.\start-analyst.ps1`.

## Data and access boundaries

One native PostgreSQL database, `payments_analytics`, holds the business fixtures and private analyst metadata. The `ai_analyst` role can read exactly one selected business schema. Only the operator can change that selection. Combining scenarios would double-count attempts.

| Fixture | Payment attempts | Final CSV directory | Database schema |
|---|---:|---|---|
| Phase 1 clean A | 20,000 | [scenario_a](data/synthetic/phase1/scenario_a/) | `scenario_a` |
| Phase 1 clean B | 20,000 | [scenario_b](data/synthetic/phase1/scenario_b/) | `scenario_b` |
| Phase 1 dirty A | 20,020 | [scenario_a_dirty](data/synthetic/phase1/scenario_a_dirty/) | `scenario_a_dirty` |
| Phase 2 baseline | 100,000 | [baseline](data/synthetic/phase2/realistic_v1/baseline/) | `phase2_baseline` |
| Phase 2 incident | 100,000 | [incident](data/synthetic/phase2/realistic_v1/incident/) | `phase2_incident` |
| Phase 3 lifecycle (default) | 199,734 | [lifecycle_v1](data/synthetic/phase3/lifecycle_v1/) | `lifecycle_v1` |

All **23 CSVs are required**: three tables in each earlier fixture and eight in Phase 3. Repeated dimension files are intentional. Phase 3 includes orders, payments, settlements, bank health and four dimension tables. Phase 2 uses realistic traffic distributions; its incident changes exactly 370 successful Bank B/UPI attempts into timeout failures during October 15-21. [Phase 2 evaluation](evaluation/phase2/validation_report.json)

The application enforces SQL validation, restricted database privileges, quality gates and investigation limits. The model has no host-shell, filesystem, administrator or arbitrary-SQL tool. Ground truths in `evaluation/`, reference SQL, plans and reports remain outside its runtime context. Existing CSVs and evaluation files must not be regenerated, repaired or edited during application work.

This is a single-operator local application. Browsers share the local workspace; session recovery checks ownership and dataset/import versions. It is not a production multi-user authentication system or an operating-system sandbox. Scenario reselection and imports invalidate earlier analysis authorization.

## Verification status

Recorded evidence as of **November 22, 2026**:

| Scope | Recorded result | Evidence |
|---|---|---|
| Question-specific recommendations and follow-ups | Scoped suite: 185 passed, 11 opt-in skips. Private API with real PostgreSQL and a deterministic planner: 15 questions, 14 verified results, one dirty-data block. All 14 contextual action follow-ups used zero additional analytical SQL. Chromium checked chart values and recovery after an API restart. | [Payment journey acceptance](reports/analyst/payment_journey_acceptance.json) |
| Durable local target v1 | Passed saved-investigation recovery, completed-SQL replay, reauthorized interactions and administrative invalidation checks. | [Target v1 acceptance](reports/analyst/durable_acceptance.json) |
| Earlier lifecycle acceptance | Real NVIDIA/API/PostgreSQL checks passed eight lifecycle/health metrics, six original scenarios and four policy cases. Five browser journeys passed. The scoped suite recorded 92 passes and two opt-in skips. | [Lifecycle acceptance](reports/analyst/lifecycle_acceptance.json) |
| Dataset and database foundation | All six schemas validated; 21 focused Phase 3/database tests passed, including 14 database tests. Reproducibility runs matched the delivered Phase 3 files. | [Phase 3 tests](reports/phase3_test_results.json), [database validation](reports/postgres_analytics_validation.json) |

The newest recommendation flow **remains unverified with the hosted model**: both NVIDIA attempts failed, and a connectivity check returned Windows socket error 10013. Its deterministic-planner and browser results do not establish hosted-model success. Earlier successful live runs retain their original scope. The recommendation acceptance report also records all 43 protected source hashes unchanged, including the 23 CSVs.

Later home/status display changes passed nine focused frontend/history tests; their updated browser journeys were not rerun because ports 8000/8501 were occupied. Performance under load remains unverified: one earlier settlement quality query hit the 10-second timeout and safely published no evidence; an isolated rerun passed.

For scoped application checks:

```powershell
New-Item -ItemType Directory -Force .local/analyst/test-temp | Out-Null
$analystTestTemp = Join-Path (Resolve-Path .local/analyst/test-temp) ([guid]::NewGuid().ToString('N'))
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst -q -p no:cacheprovider --basetemp $analystTestTemp
```

For existing-source database checks without regeneration:

```powershell
python -B -m unittest discover -s scripts -p test_postgres_phase1.py -v
```

Live database validation uses `python -B scripts/postgres_analytics.py validate`. The administrative `test` subcommand also exercises imports, rollback and scenario permissions; stop active analyst work before running it. Provider and browser tests are opt-in and have separate setup requirements in the [analyst verification guide](docs/analyst-usage.md#verification). Avoid broad test discovery and fixture-generation commands during application work.

## Repository guide

| Path | Purpose |
|---|---|
| `app/` | API, investigation graph, restricted SQL tools, semantic definitions and Streamlit UI |
| `tests/analyst/` | Scoped application, integration and opt-in provider/browser tests |
| `scripts/` | Native database management, metadata setup and independent evaluation |
| `data/synthetic/` | Delivered Phase 1-3 CSV fixtures |
| `database/` | Schema definitions and evaluator-only PostgreSQL reference queries |
| `evaluation/` | Preserved ground truths, manifests and dataset validation |
| `reports/analyst/` | Application acceptance, diagnostics and browser evidence |
| `docs/`, `plans/`, `profiles/` | Usage guides, specifications and generation configuration |

The local `package.json`, `package-lock.json` and `node_modules/` belong to the user's Codex installation and are excluded from Git. Application dependencies are declared in `pyproject.toml` and pinned in `requirements-analyst.lock`.

- [Analyst usage, setup and recovery](docs/analyst-usage.md), [lifecycle metrics](docs/analyst-lifecycle.md), and [analytical UI contracts](docs/analyst-generative-ui.md).
- [Phase 3 usage and metrics](docs/phase3-usage.md), [data dictionary](docs/phase3-data-dictionary.md), [profile](profiles/lifecycle_v1.json), and [expected answers](evaluation/phase3/expected_answers.json).
- [Phase 2 usage and assumptions](docs/phase2-usage.md), [dictionary](docs/phase2-data-dictionary.md), [profile](profiles/realistic_v1.json), [expected answers](evaluation/phase2/expected_answers.json), and [benchmark questions](evaluation/phase2/benchmark_questions.json).
- [Phase 1 usage](docs/phase1-usage.md), [dictionary](docs/phase1-data-dictionary.md), [metrics](docs/phase1-metrics.md), and [preserved evaluation files](evaluation/phase1/).
- [Session context](AGENTS.md) and [dataset roadmap](plans/plan.md). Phases 4-7 remain future dataset work; the local target-v1 analyst is implemented.
