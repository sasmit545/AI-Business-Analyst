# Payment datasets: Phases 1-3

## Local AI analyst

A local Streamlit/FastAPI analyst supports attempt-success comparisons, order conversion, first-attempt success, retries, settlement count/amount completion and aligned bank health, with restricted PostgreSQL queries, raw-data quality gates, evidence-backed charts and visible SQL. NVIDIA Nemotron is configured through the private `.env` file. See [startup and validation instructions](docs/analyst-usage.md) and [lifecycle metric definitions](docs/analyst-lifecycle.md).

**Lifecycle breadth (U8 / G2) passed on November 22, 2026:** eight new metric benchmarks, all six original scenarios and four policy cases passed with real NVIDIA/API/PostgreSQL execution. Five real browser journeys passed, covering conversion, retries, settlement, health, clarification and dirty-data blocking. The scoped application suite passed 92 tests with two opt-in skips; live checks ran separately. All 43 protected files remain unchanged. See [lifecycle acceptance](reports/analyst/lifecycle_acceptance.json).

Start the analyst with `.\start-analyst.ps1`. Sessions save automatically in local PostgreSQL. Under **Saved sessions**, choose a conversation by its first question and select **Open session**. [Setup and recovery guide](docs/analyst-usage.md) · [Target v1 acceptance](reports/analyst/durable_acceptance.json).

**One PostgreSQL database: `payments_analytics`.** Each fixture has its own schema. Earlier fixtures have three tables; Phase 3 has eight lifecycle tables. Use one selected scenario at a time; combining variants would double-count attempts.

| Fixture | Payment rows | Final CSV directory / database schema |
|---|---:|---|
| Phase 1 clean A | 20,000 | [scenario_a](data/synthetic/phase1/scenario_a/) / `scenario_a` |
| Phase 1 clean B | 20,000 | [scenario_b](data/synthetic/phase1/scenario_b/) / `scenario_b` |
| Phase 1 dirty A | 20,020 | [scenario_a_dirty](data/synthetic/phase1/scenario_a_dirty/) / `scenario_a_dirty` |
| Phase 2 baseline | 100,000 | [baseline](data/synthetic/phase2/realistic_v1/baseline/) / `phase2_baseline` |
| Phase 2 incident | 100,000 | [incident](data/synthetic/phase2/realistic_v1/incident/) / `phase2_incident` |
| **Phase 3 lifecycle: start here** | **199,734** | [lifecycle_v1](data/synthetic/phase3/lifecycle_v1/) / `lifecycle_v1` |

These **23 CSVs are all required**: three tables in each earlier fixture and eight in Phase 3. Repeated dimension files are intentional. There are no additional final CSV copies. All original Phase 1 and 2 datasets and ground truths are unchanged.

Phase 2 uses realistic merchant, bank, method, amount and time distributions. The incident changes exactly 370 successful Bank B/UPI attempts into timeout failures during October 15-21. Full evaluation results and the reproducibility checks are in [the Phase 2 report](evaluation/phase2/validation_report.json).

## Use PostgreSQL

Native Windows PostgreSQL is the chosen deployment. From a normal PowerShell window in this repository:

```powershell
python -B scripts/postgres_analytics.py setup
python -B scripts/postgres_analytics.py test
```

Setup loads all six isolated schemas and gives the read-only AI role access to `lifecycle_v1` only. The old `postgres_phase1.py` command remains a compatibility entry point for the same unified implementation. See [installation and connections](docs/phase1-postgresql.md).

PostgreSQL is installed locally, all six schemas are loaded, and all 21 focused tests passed (including 14 database tests). Two fresh Phase 3 generation runs match the delivered files. Verification evidence is recorded in [postgres_analytics_last_run.json](reports/postgres_analytics_last_run.json) and [the database validation report](reports/postgres_analytics_validation.json).

## Evaluation and documentation

- [Phase 3 lifecycle usage and metrics](docs/phase3-usage.md), [dictionary](docs/phase3-data-dictionary.md), [profile](profiles/lifecycle_v1.json), and [expected answers](evaluation/phase3/expected_answers.json).

- [Phase 2 usage, assumptions and metrics](docs/phase2-usage.md), [field dictionary](docs/phase2-data-dictionary.md), and [versioned profile](profiles/realistic_v1.json).
- [Phase 2 expected answers](evaluation/phase2/expected_answers.json) and [benchmark questions](evaluation/phase2/benchmark_questions.json), computed from independent SQL over the CSVs.
- [Phase 1 usage](docs/phase1-usage.md), [dictionary](docs/phase1-data-dictionary.md), [metrics](docs/phase1-metrics.md), and [preserved evaluation files](evaluation/phase1/).
- [Session context](AGENTS.md) and [roadmap](plans/plan.md).

Ground truths stay in `evaluation/`, outside PostgreSQL and outside the analyst's runtime context. Dataset gates and application acceptance are reported separately.

To validate Phase 3 locally, including two temporary reproducibility runs:

```powershell
python -B scripts/validate_phase3.py --check-reproducibility
python -B -m unittest discover -s scripts -p test_phase3.py -v
python -B -m unittest discover -s scripts -p test_postgres_phase1.py -v
```

Do not regenerate Phase 1 during database setup. [Phase 2 generation instructions](docs/phase2-usage.md) are separate from ingestion.
