# Generate and validate Phase 1

**Final CSV location: `E:\pinelabs\data\synthetic\phase1\`.** Start with the three files in `scenario_a/`. The [start-here guide](../README.md) links all nine required CSVs and explains which files to load together.

This package contains two independent clean payment-attempt scenarios and one intentionally dirty copy of Scenario A. It requires Python 3.10 or newer with its standard library, including SQLite; no packages, credentials, downloads, or network access are needed. The delivered artifacts were checked with Python 3.14.9. Run commands from `E:\pinelabs` (PowerShell examples):

```powershell
python -B scripts/generate_phase1.py
python -B scripts/validate_phase1.py --check-reproducibility
python -B -m unittest discover -s scripts -p test_phase1.py
```

The generator uses seed 42 by default and overwrites only its nine CSVs and two generation/defect manifests. It does not modify plans, reference SQL, saved expected answers, or the validation report. The validator refreshes `evaluation/phase1/validation_report.json`; exit 0 means the package passes, and exit 1 means a required check failed. The supplied dirty fixture is an expected validation failure for analysis, so detecting its exact declared defects is a passing package check.

The reproducibility option generates twice in temporary directories and compares SHA-256 hashes for every CSV and both deterministic manifests, also against the delivered files. It cleans those temporary directories afterward. Content serialization uses UTF-8, LF line endings, stable ordering, and no wall-clock build timestamps. Reproducibility is verified for the same generator version, configuration, and Python runtime; byte identity across future Python random-library changes is not promised.

To generate into a separate directory and create its expected answers:

```powershell
python -B scripts/generate_phase1.py --output-root E:\pinelabs\scratch-phase1
python -B scripts/validate_phase1.py --root E:\pinelabs\scratch-phase1 --write-expected --check-reproducibility
```

`--write-expected` computes answers from CSVs with the checked-in reference SQL, checks them against separately authored specification assertions, and writes the answer file only if all checks pass. Routine validation omits this flag and compares the new SQL results against the saved answers. Reference SQL is always loaded from this source package's `evaluation/phase1/reference.sql`, including when `--root` points elsewhere. A seed override is available for experiments, but the fixed Phase 1 acceptance profile requires seed 42.

## Files to load

Choose exactly one folder; each contains `payments.csv`, `merchants.csv`, and `banks.csv`:

| Folder | Payment rows | Purpose |
|---|---:|---|
| `data/synthetic/phase1/scenario_a/` | 20,000 | Bank B/UPI decline |
| `data/synthetic/phase1/scenario_b/` | 20,000 | Method-mix shift |
| `data/synthetic/phase1/scenario_a_dirty/` | 20,020 | Quality-failure demonstration |

Keep all `evaluation/phase1/` files outside the analyst's queryable dataset. They include reference SQL, SQL-derived expected answers, the defect manifest, the generation manifest with row counts and hashes, and the validation report. The code deliberately does not add a scenario or period column to analyst tables; folders isolate scenarios and timestamps determine periods.

## Quality-gated reference analysis

```powershell
python -B scripts/validate_phase1.py --analyze data/synthetic/phase1/scenario_a
python -B scripts/validate_phase1.py --analyze data/synthetic/phase1/scenario_a_dirty
```

The clean command prints SQL metrics and exits 0. The dirty command reports 20 additional duplicate occurrences, 10 missing timestamps, and 10 orphan merchant references, prints `analysis_status: blocked`, omits metrics, and exits 1. The validator does not discard or repair records. The three defect groups use 40 disjoint original attempt IDs; appended duplicate rows exactly match their clean originals. Dirty merchant and bank tables match clean A byte for byte.

`--analyze` checks table quality before querying; it is not the full scenario-profile check. Use the package validation command to verify exact rates, allocations, manifest hashes, expected answers, and declared dirty-copy transformations.

`reference.sql` uses SQLite queries separated by `-- query: NAME` markers. The validator loads CSV values as text into three identically named in-memory tables and executes each query independently. It never imports generator allocation constants. Python checks actual dates, schema, key relationships, amounts, outcomes, and identifiers before the SQL runs. SQL calculates period, bank/method, method, failure-reason, merchant, date, join, and decomposition results directly from loaded rows.

The dataset gate is implemented and verified. The analyst application gate remains **pending**: this package provides fixtures and reference behavior, not an analyst application. Phases 2–7, settlement, refunds, fraud, identities, access-control simulation, and performance benchmarks remain outside scope.

See [data dictionary](phase1-data-dictionary.md) and [metric definitions](phase1-metrics.md).
