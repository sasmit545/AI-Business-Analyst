# Project context for future sessions

Last verified: 2026-11-22. Treat the status below as a dated snapshot; inspect current files and reports before resuming. New user instructions take precedence.

## Project and active scope

- **Question-specific payment recommendations (2026-11-22).** The analyst records the business objective alongside the metric and ranks verified SQL results for that objective. A contextual action follow-up uses the parent's evidence and scope. Restricted PostgreSQL and the private API covered 15 questions with a deterministic planner, including all eight lifecycle metrics. Fourteen verified results supported follow-ups with zero additional analytical SQL. Dirty data produced rule-specific guidance. Swapped failure labels and a three-bank traffic change altered the recommended investigation in disposable databases. Chromium verified chart values and reopened the same action after an API restart. The scoped suite passed 185 tests with 11 opt-in skips. Separate focused and browser checks covered the final changes. Both hosted NVIDIA attempts failed, and a connection check from this environment returned WinError 10013. The live operator selection was `lifecycle_v1` and all 43 protected hashes matched. See `reports/analyst/payment_journey_acceptance.json` and `docs/analyst-usage.md`.

- **Home header (2026-11-22).** The mint header pairs a small payment-card icon with the **Payments analyst** title. The **Start new session** button sits alongside the introduction on desktop and below it on phones. Chromium checked the icon and single-line heading at 320, 390 and 1440 pixels. See `reports/analyst/home_icon_browser.json`. Earlier header checks covered four widths and all six frontend tests passed. See `reports/analyst/home_header_browser.json` and `reports/analyst/home_header_frontend.xml`.

- **Analyst component colors (2026-11-22).** Navigation uses deep pine with mint primary actions. Baseline and comparison cards use the teal and violet of their chart series. Chromium checks at 1440 and 390 pixels covered the home and result screens, saved-session keyboard focus, and distinct chat message colors. Sampled text contrast ranged from 6.76:1 to 14.37:1. The browser used an isolated API fixture backed by saved, verified evidence. See `reports/analyst/component_palette_browser.json` and the accompanying desktop and mobile screenshots.

- **Chart scales (2026-11-22).** Daily lines fit the observed values across the displayed periods. Use **Fit y-axis to observed values** to switch scales on a chart with varying values. Bars and areas start at zero. In Chromium at 1440 and 390 pixels wide, a test series moving from 97.001% to 97.004% occupied 163 vertical pixels on the fitted scale. The chart, frontend and follow-up suites passed 47 tests with six opt-in model cases skipped. See `reports/analyst/chart_scale_tests.xml`.

- **Saved session list (2026-11-22).** Click a conversation on the home screen to reopen it. Desktop and mobile Chromium checks showed all 23 saved conversations. The mobile browser test reopened the selected conversation after an API restart, and 15 focused frontend and follow-up tests passed. See `reports/analyst/saved_session_list_tests.xml` and `reports/analyst/saved_session_list_browser.xml`.

- **Runtime bank filters (2026-11-22).** When the analyst opens a restricted database session, it reads bank IDs and names from the selected schema’s `banks` table. New queries and follow-ups bind the resolved ID before executing SQL. Missing and ambiguous bank names trigger clarification. A registered bank with an empty attempt window returns a zero denominator. PostgreSQL and API checks covered unrelated names and IDs, duplicate names, empty windows and recalculation from an older saved label. The application suite passed 145 tests with ten opt-in skips. On the final code, 24 focused checks passed, including the additional API clarification test. All 43 protected source hashes matched. See `reports/analyst/runtime_bank_directory_tests.xml` and `reports/analyst/runtime_bank_directory_final_checks.xml`.

- **Bank filters (2026-11-22).** An older Bank D/UPI investigation bound the display label `Bank D` as a PostgreSQL bank ID and returned zero attempts in both periods. New analysis calls resolve supported bank labels before checkpointing, SQL execution and evidence reuse. An affected saved result offers **Recalculate for BANK_D**. The corrected live session is titled **Bank D / UPI payment success and failure reasons**. Its October counts are 8,594/9,056 and 8,950/9,382. The live session used the explicit `BANK_D` ID. The scoped regression exercises the display name and recalculation using restricted PostgreSQL and a model double. The application suite passed 143 tests with ten opt-in skips. All 43 protected hashes matched. See `reports/analyst/bank_filter_tests.xml` and `docs/analyst-usage.md`.

- **Analyst UI styling (2026-11-22).** The Streamlit home screen now groups new and saved sessions around a locally bundled payment-card illustration. Results use labeled status pills and coordinated baseline/comparison colors. Desktop and mobile Chromium checks covered session reopening, chart totals, history, mobile tables and SQL provenance with real PostgreSQL and a deterministic model double. The scoped suite passed 141 tests with ten opt-in skips, and 11 final frontend and follow-up checks passed. Screenshots and verification details are in `reports/analyst/workspace_style.json`.

- **Analyst requirements check (2026-11-22).** Results identify the dataset and filters beside the comparison windows. Measured findings explain each observed rate's sensitivity to a single outcome, the weighting for settlement amounts, and limitations from empty denominators or blocking defects. Bank-health warnings appear alongside the result. Recommendations have their own heading. The scoped application suite passed 141 tests against the current code and skipped ten opt-in provider and browser cases. All 43 protected hashes matched the baseline. See `reports/analyst/requirements_checks.xml` and `docs/analyst-usage.md`. Earlier live benchmarks retain their original dates and coverage.

- **Local saved sessions (2026-11-22).** The home screen lists saved conversations from the local PostgreSQL database by first question and latest question date. Select **Saved sessions** from an active conversation to switch. The trusted UI can reopen existing local-operator sessions for the current dataset generation and import version. A separate workspace credential stays on the server. Existing key-based API clients keep their per-session access. The scoped suite passed 140 tests and skipped nine opt-in tests. The Chromium test created two conversations and reopened the selected one after an API restart in a fresh mobile-sized browser window. All 43 protected files matched the baseline. See `reports/analyst/local_sessions_tests.xml` and `docs/analyst-usage.md`.

- **Result screen and chat navigation (2026-11-22).** A result starts with its saved question, verified answer and comparison dates. Chart titles name the metric; chart tables show the plotted fields. Use **Ask follow-up** for a contextual question, **Filters, dates and comparisons** for structured actions, and **New question** for an independent analysis in the same session. **Chat history** reopens saved questions. See `reports/analyst/ui_readability_acceptance.json` for the scoped suite and desktop/mobile browser checks.

- **Order conversion result display (2026-11-22).** The verified result shows both paid and eligible order counts and the rate per creation window. It ranks bank and payment method pairs by the change in their own conversion rate using both denominators and reports exact ties. The SQL and parameter widgets load when the operator opens provenance. A private Chromium run using real restricted SQL and a model double checked the desktop table, mobile result and opening and closing provenance. The hosted model request failed during this display check. See `reports/analyst/conversion_answer.png`, `reports/analyst/conversion_display_tests.xml` and `docs/analyst-generative-ui.md`.

- **Saved chat history (2026-11-22).** Open **Chat history** in the sidebar of an active or resumed session. The history endpoint projects questions, clarification exchanges and published answer headlines from the authorized investigations. Reopen a result to inspect its charts and SQL. New clarification replies are saved atomically in the existing investigation JSON. Older saved questions and answers remain accessible. See `docs/analyst-usage.md` and `reports/analyst/chat_history_acceptance.json`.

- **Generative analytical UI delivery (2026-11-22).** The existing investigator selects evidence-bound views during publication. The version 1 schema is available at authenticated `GET /ui/schema`. Read `docs/analyst-generative-ui.md` and `reports/analyst/generative_ui_acceptance.json` for the component and interaction contracts, live scenarios, and verification scope. Merchant/category and latest-attempt detail use optional registered SQL inside the existing quality-gated bundle. Identical natural-language follow-up requests can reuse the verified parent snapshot. Keep published evidence and session ownership checks on every interaction.

- **Latest analyst delivery (2026-11-22): the local target-v1 plan is implemented.** Read `reports/analyst/durable_acceptance.json`, `reports/analyst/implementation_status.json` and `docs/analyst-usage.md` first. Earlier delivery boundaries and pending notes below describe prior versions. One private `analyst_meta` schema stores session ownership, generation/import versions, restricted evidence, SQL receipts, budgets and LangGraph checkpoints. A separate `analyst_writer` connects to metadata. Keep the writer password and session resume keys private.
- New sessions can resume after a restart using saved credentials and fresh authorization. A chart or typed filter runs a new comparison with inherited dates, metric and cutoff. An adaptive attempt-success test consumes the remaining parent budget. A completed SQL receipt permits replay from the original snapshot. An interrupted receipt returns a limited result with the charges retained. The API evaluator checks these interactions and conflicting metric definitions. Administrative failure/reselection checks run in a disposable native PostgreSQL cluster to preserve the operator's live selection.
- The scoped application suite passed 105 tests with three opt-in skips. Ten focused UI/interaction checks also passed, bringing the distinct passing application tests to 107. Live API and browser proof ran separately. All 43 protected hashes match the baseline. Historical demo JSON is still readable by the operator. New saved investigations use PostgreSQL. Setup for a new installation is `scripts/setup_analyst_metadata.py` using the analyst venv. Start both services with `.\start-analyst.ps1`. No further analyst plan unit remains after the target-v1 acceptance checks.

- **Earlier lifecycle milestone (2026-11-22): U8 / G2 passed.** Real NVIDIA/API/PostgreSQL checks passed all eight lifecycle/health metrics plus all six original scenarios and four policy cases. Five real browser journeys passed: conversion, retry recovery, settlement amount, health and dirty-data blocking; successful metric journeys include desktop/mobile, exact chart values, provenance and clarification clearing results. Scoped suite: 92 passed, two opt-in skips; live checks ran separately. Final verification checked 19 evidence artifacts, all 43 frozen runtime files and all 43 protected source hashes. All 23 CSVs are preserved; `lifecycle_v1` with eight visible tables is restored. Read `reports/analyst/lifecycle_acceptance.json`, `reports/analyst/implementation_status.json` and `docs/analyst-lifecycle.md` before resuming. The original U1-U7 / G1 acceptance remains in `reports/analyst/final_acceptance.json`.
- **Lifecycle implementation:** registered tools cover order conversion, first-attempt success, retry uptake and two recovery denominators, due settlement count/amount and aligned bank health. Pre-aggregate order outcomes; retain observation cutoff/maturity and metric-scoped quality. Missing/invalid/duplicate health never removes payment attempts. Runtime limits are unchanged. Hand-fixture tests use transaction-local temporary tables and rollback, never imports into business schemas. Independent evaluator: `scripts/evaluate_lifecycle.py --live-model`; original scenario regression accepts `--report` to preserve historical reports. Browser metric selectors are documented in `docs/analyst-lifecycle.md`.
- **Observed runtime limitation:** one settlement browser quality query exceeded the 10-second statement timeout and published no evidence. An isolated rerun passed with unchanged runtime code and budgets. Preserve `reports/analyst/browser_settlement_timeout.xml`; load performance is not certified. Pre-optimization SQL failures and browser-harness failures are historical, preserved and superseded by the final same-version live acceptance.
- **Latest correction:** Nemotron twice extended an explicit end date to 00:24; a prompt-only change did not fix it. `app/agent/windows.py` now recognizes two ISO inclusive-to/through-exclusive ranges with a named timezone, binds exact midnight bounds in tool schemas, and rejects mismatch before SQL with bounded repair feedback. Other wording remains model-interpreted with visible windows. Regression and final same-version live run passed. Preserve the failed-run reports; do not expose them to the model.
- **Delivery boundary at the earlier lifecycle milestone:** U9 was deferred until the durable delivery recorded above. No Git repository, commit or PR exists. Code review: skipped (ce-code-review unavailable); manual inspection and separate simplification are documented in `reports/analyst/lifecycle_review.json`. Current wheel: `reports/analyst/lifecycle_build_result.json`; frozen runtime hashes: `reports/analyst/lifecycle_runtime_snapshot.json`. Earlier pending/blocker statements below are historical and superseded by the current acceptance report.

- Project: **Enterprise AI Business Analyst**, working directory `E:\pinelabs`.
- Phase 1, 2 and 3 synthetic CSVs are implemented and validated. The data and database foundation is ready for AI analyst implementation. Phases 4-7 are future work and are not prerequisites for the first analyst application.
- Latest work: the user invoked `ce-work` on `plans/2026-11-21-2019-feat-enterprise-ai-analyst-plan.md` and subsequently asked to continue. At the lifecycle milestone, U1-U8 were implemented and verified through G2. Do not mark target v1 complete from local file evidence or in-memory investigations.
- Latest acceptance follow-up: 43 offline application checks passed; all 43 protected source hashes remain unchanged. Browser coverage now includes clarification with previous-result clearing and an occupied-port preflight. The preflight rejection is verified; the new browser journey remains unrun because ports 8000/8501 are occupied. See `reports/analyst/acceptance_followup.json`. Full six-scenario live acceptance is still pending.
- Latest live-evaluation failure (2026-11-21 22:13 IST): Scenario A reached SQL after two invalid `get_context` calls, then exhausted token reservations before publication. The adapter now requests final provider usage and settles completed calls against it; missing/invalid/interrupted receipts retain their reservation. The 32,768 ceiling is unchanged, and errors identify the specific limit. Local verification: full suite 60 passed/2 opt-in skips, then 24 focused checks passed after the final-receipt edge fix. See `reports/analyst/token_budget_diagnosis.json`; the failed live report is preserved and a fresh live run remains required.
- Subsequent live run (22:26 IST) confirmed token accounting at 11,499 tokens but attempted a second analysis after SQL, causing a policy block; the evaluator then incorrectly parsed unpublished evidence (`None`). Fixed: only inspection/publication tools are offered after analysis; the dispatcher still denies repeated bundles. The evaluator now requires scenario-appropriate published evidence and records the original error/status/budget. Full suite: 69 passed, 2 opt-in skips. Wheel rebuilt; 43 protected files unchanged. See `reports/analyst/publication_diagnosis.json`; live acceptance remains pending rerun.
- Latest live run (22:55 IST): Phase 1 A and B passed with Nemotron. Dirty stopped before SQL after three invalid `get_context` calls. The host now supplies the clean selected-schema catalog in initial context and omits that optional tool from advertised choices. Full suite: 70 passed, 2 opt-in skips. Separate real API/SQL check with an explicit model double published exactly 20 duplicate, 10 missing-timestamp and 10 orphan-merchant diagnostics, no certified metrics; restored `lifecycle_v1`, 43 protected hashes unchanged. See `reports/analyst/context_diagnosis.json` and `dirty_context_validation.json`. Remaining live cases and browser acceptance are pending; historical A/B success is not a same-version full gate pass.
- Phase 3 is complete: six-schema setup/import/SQL validation and all 21 focused tests passed. Analyst application gates remain pending; dataset and database test results do not certify application behavior.
- **Latest user decision: native PostgreSQL on Windows. No Docker or WSL.** Earlier Docker/WSL requests were superseded. `compose.yaml` was removed; current scripts use native Windows executables.
- PowerShell is the current shell. Python 3.14.9 was available. No Git repository was present; do not claim commits or PRs exist.
- `package.json`, `package-lock.json`, and `node_modules/` contain the user's Codex installation, not an analyst application. Preserve them.

## Read these first

| File | Purpose |
|---|---|
| [README.md](README.md) | Final CSV locations and entry points |
| [plans/plan.md](plans/plan.md) | Roadmap and precise Phase 1 allocations |
| [plans/synthetic-payment-dataset-plan.md](plans/synthetic-payment-dataset-plan.md) | Phase 1 specification |
| [plans/phase-02-realistic-payment-behavior.md](plans/phase-02-realistic-payment-behavior.md) | Phase 2 specification |
| [docs/phase2-usage.md](docs/phase2-usage.md) | Phase 2 assumptions, actual results, evaluation and commands |
| [profiles/realistic_v1.json](profiles/realistic_v1.json) | Versioned Phase 2 generation configuration |
| [plans/analyst-project-context.md](plans/analyst-project-context.md) | Developer/evaluator business brief; contains answers and historical Phase 1-only scope statements |
| [plans/phase-03-payment-lifecycle.md](plans/phase-03-payment-lifecycle.md) | Phase 3 lifecycle specification |
| [docs/phase3-usage.md](docs/phase3-usage.md) | Current lifecycle behavior, metrics and evaluator instructions; contains answers |
| [docs/phase3-data-dictionary.md](docs/phase3-data-dictionary.md) | Analyst-safe lifecycle field meanings |
| [docs/phase1-postgresql.md](docs/phase1-postgresql.md) | Current native Windows setup and connection instructions |
| [docs/phase1-data-dictionary.md](docs/phase1-data-dictionary.md) | Field meanings and representations |
| [docs/phase1-metrics.md](docs/phase1-metrics.md) | Metric definitions and scenario explanations |

The plans describe requirements, not current execution status. Use actual reports and runtime checks for completion claims.

## Next milestone: AI analyst implementation

- Build one complete flow before extending the datasets: accept a business question; identify the metric, dates and selected scenario; check data quality; generate and validate SQL; execute through `ai_analyst`; return a useful table/chart, an evidence-based explanation and the executed SQL.
- Reuse the existing native Windows `payments_analytics` database. Scenario selection remains administrative and outside model control. Use one selected schema per analysis; never combine fixtures into one population.
- Give the analyst only its restricted query tool, selected-schema metadata, data dictionary and answer-free metric definitions. Keep administrator credentials and host shell/filesystem tools out of its runtime.
- This `AGENTS.md`, plans, usage guides with benchmark results, generator configurations, reference SQL, expected answers and defect manifests are developer/evaluator context, not analyst prompt or retrieval material. Extract clean metric definitions instead of passing answer-bearing documents wholesale.
- Evaluate generated answers separately against the saved ground truths. The analyst must calculate findings from database rows, not read evaluator outputs or reuse reference SQL as its generated analysis.
- Start acceptance with Phase 1: localize Scenario A deterioration, distinguish Scenario B transaction-mix change from segment deterioration, and detect dirty-data defects without silently filtering or repairing them. Then evaluate Phase 2 realistic distributions and Phase 3 attempt success, order conversion, retry recovery and settlement completion.
- Answers must expose their metric denominator, filters, time window, supporting SQL/results and material caveats. Distinguish observed facts from causal hypotheses and recommendations. Clarify consequential ambiguity rather than silently choosing an unrelated period or metric.
- Enforce query safety and access boundaries in application code and database privileges, not prompts alone. Preserve timeouts and scenario isolation, and block unsupported conclusions when quality checks fail. Application-level quality gating and runtime isolation still need implementation and tests.
- The first application milestone is complete only when it executes real queries, presents evidence and passes the separate analyst benchmarks, including a safe failure case. Keep analyst gates pending until that evidence exists.
- The selected stack is FastAPI, Pydantic v2, LangGraph, SQLGlot, Psycopg 3, Streamlit and Plotly. The user selected NVIDIA Nemotron `nvidia/nemotron-3.5-super-vl-120b-a12b` with free credits. The existing npm files belong to the user's Codex installation; do not treat them as an analyst app scaffold. Consult the original business brief for requirements and current phase documentation for available tables; historical Phase 1-only limitations are not current database limitations.

## Preserve the dataset and ground truths

**Do not regenerate, edit, merge, deduplicate, or repair the existing CSVs during database or analyst implementation.** Do not modify the original evaluation files to make validation pass.

The final Phase 1 location is `data/synthetic/phase1/`. Each of these folders contains `payments.csv`, `merchants.csv`, and `banks.csv`:

| Folder/schema | Payment rows | Contract |
|---|---:|---|
| `scenario_a` | 20,000 | 98% to 96.2%; exactly 180 additional BANK_TIMEOUT failures in Bank B/UPI |
| `scenario_b` | 20,000 | 96.4% to 91.6%; CARD remains 98%, UPI remains 90%; method shares change |
| `scenario_a_dirty` | 20,020 | A plus 20 duplicate occurrences, 10 missing timestamps, and 10 orphan merchant references |

- All **nine CSVs are required**, even though filenames and dimension contents repeat. The user was confused by apparent copies; do not create another final dataset folder or delete required scenario files.
- Each clean scenario has 10,000 attempts per period, 20 merchants, and five banks. Never combine scenarios into one analytical population.
- Periods: October 1-14 and October 15-28, 2026; timestamps have explicit `+05:30`. Seed: 42. Amounts: positive integer INR paise. One payment row represents one completed attempt, not an order or settlement.
- Dirty defect groups use 40 disjoint original IDs. Preserve every intentionally corrupt record.
- Exact merchant allocations and daily quotas are in `plans/plan.md`; aggregate rates alone are insufficient validation.
- `evaluation/phase1/` contains the original reference SQL, expected answers, generation manifest, defect manifest, and CSV validation report. Preserve all five files.
- `reports/postgres_phase1_source_snapshot.json` fingerprints those five files and all nine CSVs. Verify against it; do not replace the baseline to hide changes.

## PostgreSQL implementation

- Preferred entry point: `scripts/postgres_analytics.py`; `scripts/postgres_phase1.py` retains the shared implementation for compatibility. Tests: `scripts/test_postgres_phase1.py`, now covering all three phases.
- Schema definitions, constraints and PostgreSQL reference queries: `database/phase1/`, `database/phase2/`, and `database/phase3/`.
- Exactly one target database: `payments_analytics`; schemas: `scenario_a`, `scenario_b`, `scenario_a_dirty`, `phase2_baseline`, `phase2_incident` (three tables each), and `lifecycle_v1` (eight tables). Never merge these into one analytical population.
- EDB PostgreSQL 18.7 Windows x64 binaries are installed. The user completed setup and live tests successfully; verify current reports before making fresh completion claims.
- Executables: `.local/postgres/runtime/pgsql/bin/`; persistent cluster: `.local/postgres/pgdata/`; log: `.local/postgres/server.log`.
- Bind to `127.0.0.1`, default port 5432. `PAYMENTS_POSTGRES_PORT` can select another port before first successful startup; the saved port is in `.local/postgres/native_config.json`.
- Native startup uses `initdb` and `pg_ctl`, not a Windows service. Starting an existing cluster does not import data; `setup` and `ingest` explicitly replace the fixture tables.
- Ingestion uses COPY in one transaction. Preserve rollback behavior and verify the connected server is the dedicated project cluster before making changes.
- All columns use text to preserve exact CSV representations, including empty strings and timezone offsets. Clean payments enforce keys and value checks; dirty payments intentionally omit those clean constraints. Do not silently change this representation during installation work.
- Original SQLite validation remains in `scripts/validate_phase1.py`; PostgreSQL queries are a separate port. Compare live SQL results with existing expected answers and full imported row multisets with CSVs.

## Security boundaries

- AI role: `ai_analyst`, SELECT access to exactly one selected scenario. `lifecycle_v1` is the setup default.
- Changing scenarios is administrative: disable logins, terminate existing AI sessions, revoke old privileges, grant the selected schema/tables, and reconnect clients.
- Isolation must survive qualified cross-schema queries and search_path changes. Read-only defaults alone are not sufficient; tests explicitly disable that default and exercise privileges.
- Keep ground truths outside PostgreSQL and outside the future analyst's runtime context. Do not create answer tables/views or expose evaluator scripts, plans, or answer-bearing documentation to that runtime.
- The future AI gets only its restricted database connection, not host shell/filesystem access or administrator credentials. No AI runtime sandbox has been implemented.
- Credentials already exist in `.local/postgres/ai_password` and `.local/postgres/postgres_password`. Never print them, copy them into documentation, commit them, or regenerate them while retaining the cluster.
- `.local/` is ignored. Database-level restrictions do not protect against someone controlling the Windows account or these files.
- Dirty data remains queryable when explicitly selected, but certified business metrics are blocked by the implemented raw-data quality gate. Independent SQL evaluation confirms the seeded dirty defects; live model behavior still needs acceptance evidence.

## Verified runtime status

- Native PostgreSQL is installed; the user ran setup and all 12 Phase 1/2 tests successfully. Missing-binary/download blockers are resolved.
- The user-started server is reachable from this session. A restricted-token pg_ctl status may wrongly report no server because it cannot inspect that process. start/status now verify the actual connection and dedicated data directory first; do not attempt another server or change log-file permissions to bypass restrictions.
- Six-schema Phase 3 setup/live validation and all 14 database tests passed; read reports/postgres_analytics_last_run.json and reports/postgres_analytics_validation.json for latest evidence.
- Earlier historical reports may say blocked. Do not treat them as current status or overwrite them to fabricate a successful old run.

## Resume commands

Run from `E:\pinelabs` with native Windows Python:

```powershell
# Offline verification of existing fixtures and setup code; no data regeneration.
python -B -m unittest discover -s scripts -p test_postgres_phase1.py -v

# Install, start, import existing CSVs, configure permissions, and validate.
python -B scripts/postgres_analytics.py setup

# Required live coverage: integrity, ground truths, repeat import, rollback, permissions.
python -B scripts/postgres_analytics.py test
```

For an already populated cluster, use `status`, `start`, and `validate` as appropriate instead of blindly rerunning setup. Use `select --scenario scenario_b` to change selection and `stop` for shutdown; these are subcommands of the same script.

Do not run `generate_phase1.py`, `test_phase1.py`, broad unittest discovery, or the original validator's reproducibility mode during database or analyst implementation: they generate fixtures or overwrite the original evaluation report. The focused PostgreSQL suite reads existing sources without regenerating them.

Completion of the database task requires actual successful native installation, all six imported scenarios, live SQL/permission tests passing, and unchanged source hashes. Successful live reports now use `reports/postgres_analytics_validation.json`. Keep the analyst application gate pending. Update this file's status and relevant reports after verified progress; distinguish code written, checks passed, skipped checks, and unresolved blockers.

## Phase 2 handoff

- Final CSVs: `data/synthetic/phase2/realistic_v1/{baseline,incident}/`, three files per variant, 100,000 attempts each. There are 15 required CSVs across both phases; do not delete the repeated dimension files or create another final-data folder.
- Generator: `scripts/generate_phase2.py`; independent SQL validator: `scripts/validate_phase2.py`; tests: `scripts/test_phase2.py`. Python standard library only. Seed 42, schema/generator version 1.0.0.
- Exact largest-remainder traffic counts use global merchant/bank pools and per-merchant method/date-hour allocations, stable ID/date-hour ties, and independent named random streams. Sampled outcomes need not equal configured probabilities. Earlier date-hour ties cause unequal fortnight totals; this is documented, not a validation failure.
- Baseline successes: 97,065/100,000 (97.065%); incident: 96,695/100,000 (96.695%). Incident converts 370 of 3,699 eligible successful Bank B/UPI attempts on October 15-21 to BANK_TIMEOUT. No other fields change.
- `evaluation/phase2/`: independent SQLite SQL and paired SQL, expected answers, incident/generation manifests, validation report and eight benchmark questions with machine-readable answer pointers. These files are evaluator-only, never imported into PostgreSQL or exposed to the future AI.
- The independent validator uses disposable in-memory SQLite as a calculation engine, not a second persistent application database. PostgreSQL ports compare 16 metric sections per variant plus four paired sections against its answers.
- Like-for-like metrics match local hour/ISO weekday within bank/method across fortnights, use pooled exposure weights, and report excluded strata. Paired counterfactual queries require the administrative evaluator connection; never grant both schemas to the AI.
- Dataset gate passed, zero four-SE diagnostic flags, two regeneration runs match all six CSVs and both manifests, all 14 protected Phase 1 files unchanged. Analyst gate pending.
- `python -B scripts/validate_phase2.py --check-reproducibility` checks saved answers and temporary regeneration, writing only the Phase 2 report. `python -B -m unittest discover -s scripts -p test_phase2.py -v` uses temporary Phase 2 fixtures.
- Do not run `--write-expected` to conceal a mismatch. It is only for initial/intentional release authoring after checking the specification; normal validation compares against saved ground truths.

## Phase 3 handoff

- Plan: plans/phase-03-payment-lifecycle.md. Schema/profile lifecycle_v1 version 1.0.0; seed 42. No Phase 4 incidents or AI application implemented.
- Final files: data/synthetic/phase3/lifecycle_v1/, eight CSVs. 198,000 orders, 199,734 completed payment attempts, 193,948 settlements, 89,280 health observations, 20 merchants, five banks, two methods, four failure reasons. 23 required CSVs across all phases.
- Scripts: lifecycle_schema.py (field contract), generate_phase3.py, validate_phase3.py, test_phase3.py. docs/phase3-usage.md has assumptions/metrics; phase3-data-dictionary.md has analyst-safe field meanings; profiles/lifecycle_v1.json has parameters.
- Generation preserves existing files. Reports/phase3_preexisting_source_snapshot.json fingerprints 27 original Phase 1/2 data and evaluation files. Do not replace the snapshot or regenerate prior phases.
- Orders Oct 1-28, observation cutoff Nov 1 midnight +05:30. Initial attempt +1 second; after failure, retry probability .30, next attempt +5 minutes after completion, max three. Same merchant/amount/currency/method/bank; stop on success. No truncated chains.
- One successful retry lands Oct 29. Whole stored totals are 199,734 attempts/193,948 successes; Oct 1-28 attempt metrics use 199,733 attempts/193,947 successes. Order conversion uses 193,948 paid /198,000 mature orders. Do not change denominators to erase this intentional boundary.
- Settlement per success: full gross due completion+24h; baseline settles at due time by cutoff. Main fixture has no pending obligations because all are due by Nov 1. Hand fixture uses Oct 29 noon cutoff and three orders/four attempts to test a not-yet-due obligation and immature order.
- Independent SQL/answers: evaluation/phase3/reference.sql and expected_answers.json, ten sections. hand_fixture.json and benchmark_questions.json are evaluator-only. PostgreSQL port in database/phase3/reference.sql. Never import ground truths into database or expose them to AI runtime.
- Bank-health observations independent of payments; join bank+method+containing five-minute bucket. Per-order aggregation must precede joins for conversion.
- Pure Python checks validate all chain/settlement rules. PostgreSQL enforces keys/local checks and selected cross-table relationships; remaining lifecycle invariants are independently validated, not enforced by triggers.
- Focused tests: python -B -m unittest discover -s scripts -p test_phase3.py -v. Reproducibility: python -B scripts/validate_phase3.py --check-reproducibility. Database: postgres_analytics.py setup/test. Do not run broad unittest discovery.
- Setup default AI schema is lifecycle_v1; grants eight SELECT-only tables. Other scenarios remain isolated. No additional persistent database.

## Final Phase 3 verification (2026-11-21)

- Complete: seven Phase 3 tests and 14 unified database tests passed, with no skips. Post-test live validation also passed. See reports/phase3_test_results.json and reports/postgres_analytics_validation.json.
- Two fresh seed-42 runs reproduce all eight CSVs and the generation manifest. evaluation/phase3/validation_report.json has dataset_gate passed, reproducibility identical, zero integrity errors, and analyst_gate pending.
- All 27 protected Phase 1/2 files remain unchanged. Exactly 23 final CSVs exist. The live database has six schemas; the AI role is restored to lifecycle_v1 with eight visible tables. Forty denial probes passed per selected schema; all six selections were tested.
- Bulk ingestion now allows 600 seconds after the previous 120-second wrapper timeout interrupted the larger transactional load. Analyst statement_timeout remains 15 seconds. Failed import rolls back; repeat ingestion preserves every row, including dirty records.
- No Docker, WSL, AI application, Phase 4 incidents, new persistent database, commits or PRs were created. Next dataset phase requires user authorization.

## Analyst implementation preflight (2026-11-21)

- The user invoked `ce-work` for `plans/2026-11-21-2019-feat-enterprise-ai-analyst-plan.md`. Its active delivery is the complete demo; lifecycle expansion and durable investigations remain deferred as specified in that plan.
- Native PostgreSQL connectivity was confirmed without setup, ingestion, or scenario changes. An isolated Python 3.14.9 environment exists at `.local/analyst/venv/`.
- Implementation is blocked at dependency installation: PyPI connections failed with Windows socket access error 10013 under the session sandbox. Required libraries are not installed locally and no usable cached wheels were found. No application code or dependency lock was written; no application tests or gates passed.
- Provider/model and token/spend ceilings remain unresolved. Do not substitute mock-model evidence for live acceptance.
- `reports/analyst/implementation_status.json` records the blocker, recovery installation command, and checks still pending. `reports/analyst/protected_sources_before.json` fingerprints 43 protected files, including all 23 CSVs, original evaluator files, and Codex package manifests; all were rechecked unchanged. Preserve this pre-implementation baseline on resume.
- Resume with dependency installation in an environment permitted to access PyPI, then dependency smoke, current schema audit, and implementation in plan dependency order. The plan body and original evaluation reports remain unchanged.

## NVIDIA model option (2026-11-21)

- The user authorized NVIDIA Nemotron as an LLM adapter option: OpenAI-compatible Chat Completions at `https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3.5-super-vl-120b-a12b`, credential from `NVIDIA_API_KEY`. This is an available option, not an exclusive provider requirement.
- `configs/analyst.example.yaml` records the proposed configuration. No configuration loader or runnable adapter exists yet. The isolated environment was rechecked and contains only pip; dependency installation remains blocked. Add the `openai` SDK to the dependency resolution/install command, then lock its resolved version with the application dependencies.
- The supplied example streams responses with thinking enabled. The analyst adapter must buffer and validate completed tool calls before dispatch; it must not print or publish `reasoning_content`, or treat streamed prose as verified factual output. Use serial tool dispatch under shared investigation budgets.
- The sample's `max_tokens: 16384` is a per-call output cap, not an investigation token or monetary ceiling. Those limits remain unset and live acceptance remains pending. No NVIDIA request has been made and hosted tool-call compatibility has not been validated.

## Analyst implementation progress (supersedes the preflight and option notes)

- **Latest log check:** the operator's 2026-11-21 21:48 IST investigation reached `verified` with two tools, eight bundle SQL statements and no repairs. Saved lifecycle evidence `08fc575739324a298bfb5c58802426b3` passes checksum/derivation verification and matches the independent oracle. See `reports/analyst/log_diagnosis.json`. This is one observed successful runtime comparison, not full six-scenario live acceptance. The earlier 21:45 IST run failed tool-argument validation before SQL; its exact bad fields were not logged. Safe field/code diagnostics and repair feedback are now implemented, with 14 focused tests passing; restart the API to load them. This agent session's own NVIDIA connectivity still fails with WinError 10013.

- Core dependencies plus `openai` and `setuptools` are installed in `.local/analyst/venv/`; `requirements-analyst.lock` records exact installed versions. Dependency smoke, read-only schema audit, package inclusion checks and `pip check` passed. Original npm files are unchanged.
- The user selected `nvidia/nemotron-3.5-super-vl-120b-a12b` and confirmed free NVIDIA credits. Root `.env` contains the user's private `NVIDIA_API_KEY`; never print or overwrite it. Trusted `Settings.from_root()` loads it. Runtime limits are 32,768 reserved tokens per investigation and 4,096 output tokens per call; paid use fails closed. The example YAML is reference documentation, not a second runtime configuration loader.
- Real restricted SQL matches the independent Phase 1 A/B, Phase 2 baseline/incident and lifecycle attempt/bank truths. Dirty A discovers all three seeded defect groups and publishes a diagnostic block. Thirteen denial probes pass per scenario with the read-only default disabled; A-to-B-to-A invalidates the original authorization connection. The default `lifecycle_v1` selection and eight-table visibility are restored.
- `scripts/evaluate_analyst.py` performs deterministic evaluation; `--live-model` runs real questions through the API and checks the same truths plus policy cases. Evaluator authority stays outside `app/`. Source hashes are checked against the existing pre-implementation baseline; do not replace it on resume.
- Browser screenshots and `reports/analyst/browser_validation.json` prove UI/API/DB rendering with an explicitly labeled model double, not actual language-model behavior. The real NVIDIA smoke was attempted; a separate credential-free connectivity probe confirmed `ConnectError -> PermissionError`, Windows error 10013. Do not claim complete-demo acceptance. Run the documented live checks in an environment permitted to reach NVIDIA before marking it passed.
- App tests are explicitly collected from `tests/analyst/`. Do not use broad discovery. Browser tests own their temporary servers on 8000/8501; stop ordinary application servers first. No runtime mock fallback exists.
- Scope remains the plan's first demo; lifecycle metrics, durable state and later dataset phases are deferred. No Git repository, commits or PRs were created. Formal Git-diff review is unavailable without a base; distinguish manual inspection and simplification from a completed formal review receipt.
