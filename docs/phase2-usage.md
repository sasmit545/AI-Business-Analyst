# Phase 2: realistic payment behavior

The delivered profile is `realistic_v1`, seed 42, with **100,000 attempts in each variant** over October 1-28, 2026. The baseline has no injected incident. Its paired incident copy changes only selected outcomes and failure reasons. Phase 1 remains byte-for-byte unchanged. The AI analyst and Phases 3-7 are not implemented.

## Files and one database

| Variant | Authoritative CSV directory | PostgreSQL schema |
|---|---|---|
| Baseline | `data/synthetic/phase2/realistic_v1/baseline/` | `phase2_baseline` |
| Incident | `data/synthetic/phase2/realistic_v1/incident/` | `phase2_incident` |

Each directory contains `payments.csv`, `merchants.csv`, and `banks.csv`. All five Phase 1/2 fixtures belong to **one database, `payments_analytics`**, in isolated schemas. There is no combined payment table. Baseline and incident repeat the same attempt IDs because they are alternative outcomes of the same population; combining them would double-count attempts. No additional CSV copies are needed.

Follow [the native PostgreSQL guide](phase1-postgresql.md). The unified entry point is:

```powershell
python -B scripts/postgres_analytics.py setup
python -B scripts/postgres_analytics.py test
```

Phase 3 setup now defaults to `lifecycle_v1`. To analyze Phase 2, an administrator selects `phase2_incident` or `phase2_baseline` with `select --scenario`; the AI role loses access to the previous schema. Setup imports existing CSVs without generating data. Native PostgreSQL is installed and Phase 1/2 live tests passed. Current all-phase execution evidence is in reports/postgres_analytics_validation.json.

## Validate or reproduce locally

Python uses only its standard library. Run from `E:\pinelabs`:

```powershell
# Check saved answers against independent SQL; also regenerate into temporary directories.
python -B scripts/validate_phase2.py --check-reproducibility
python -B -m unittest discover -s scripts -p test_phase2.py -v

# Verify unified importer and source fixtures without PostgreSQL.
python -B -m unittest discover -s scripts -p test_postgres_phase1.py -v
```

Validation writes only the Phase 2 validation report. Reproducibility checks compare the delivered six CSVs and two manifests with two isolated runs. Tests generate disposable Phase 2 fixtures in temporary directories. Neither operation regenerates Phase 1.

To deliberately reproduce this Phase 2 release:

```powershell
python -B scripts/generate_phase2.py
python -B scripts/validate_phase2.py --check-reproducibility
```

Generation overwrites only the six Phase 2 CSVs and their two manifests. For initial release authoring, `validate_phase2.py --write-expected` saves independently calculated SQL answers after all checks pass. **Do not use that flag to hide a mismatch with an established release.** Version assumptions and ground truths together when intentionally changing a profile. No additional coverage was needed, so this release uses 100,000 rather than 200,000 attempts.

## Generation assumptions

[The versioned configuration](../profiles/realistic_v1.json) records every distribution parameter, seed, allocation hierarchy, stream name, rounding rule and incident definition. All are synthetic assumptions, not estimates of real payment behavior.

Integer counts use largest remainder with exact rational weights and ascending identifier tie-breaking. First allocate global merchant totals and the global bank pool. Allocate method counts and joint local date/hour cells separately within each merchant. Independently shuffle the bank and method pools, then assign within those date/hour cells. Bank shares are exact globally; bank shares within every merchant/hour cell are sampled assignments. Seconds within each hour are random. Ties at the date/hour level favor earlier ISO date/hour keys, so the two fortnights need not have equal counts. Low-volume merchants also have visible integer quantization.

Merchant weights are 20 for M01-M04, 5 for M05-M10 and 1 for M11-M20. Bank weights are 35/25/20/15/5 for A-E. Category UPI shares are retail 50%, grocery 75%, dining 80%, services 40%. Night hours 00-05 have weight 0.25; dining hours 12-14 and 19-21 have weight 3. Dining/retail weekend days have weight 1.3. Other hours/days have weight 1.

Amounts are lognormal draws with sigma 0.6 and INR medians retail 1500, grocery 600, dining 350, services 2500. Clip to INR 10-100,000, then round to integer paise with Python's nearest-integer rounding. Drawn sample medians need not equal the parameters.

Baseline success probabilities for UPI A-E are 98/97/96/95/94%; CARD probabilities are 99/98/97/96/95%. Failure-reason weights for timeout/funds/authentication/limit are UPI 40/30/20/10 and CARD 15/35/40/10. Outcomes are sampled, so saved SQL answers use actual rates, never target probabilities.

Random streams derive from SHA-256 of `phase2:streams:v1:<seed>:<stream_name>`. Banks, methods, time, category amounts, status and reasons have separate streams. Changing an amount parameter preserves traffic/outcomes. Reproducibility is scoped to the recorded generator/configuration and compatible Python random implementation; this release was checked with Python 3.14.9. No wall-clock values enter deterministic artifacts.

## Incident and actual results

Eligible records are successful baseline Bank B/UPI attempts on October 15-21 inclusive, using the local timestamp date. Rank IDs by SHA-256 of `phase2:incident:v1:42:<attempt_id>`, with ID tie-breaks. Convert 10% of eligible successes, rounding the count to nearest integer with half ties upward. Preserve every other value and all dimensions.

| Measure | Baseline | Incident |
|---|---:|---:|
| Attempts | 100,000 | 100,000 |
| Successes | 97,065 | 96,695 |
| Whole-period success rate | 97.065% | 96.695% |
| Oct 1-14 success rate (51,184 attempts) | 97.151454% | 97.151454% |
| Oct 15-28 success rate (48,816 attempts) | 96.974353% | 96.216404% |

Exactly **370 of 3,699 eligible successes** change to `FAILED/BANK_TIMEOUT`. In the affected Bank B/UPI window there are 3,812 total attempts; successes change from 3,699 to 3,329, a **9.706191 percentage-point decrease**. Across the entire paired population the decrease is 0.37 percentage points. Non-outcome changes: zero. The 10% rule applies to eligible successes, not all attempts or a fixed ten-percentage-point decline.

## Evaluation and gates

`evaluation/phase2/` is evaluator-only:

| Artifact | Purpose |
|---|---|
| `reference.sql` | Independent SQLite queries for each variant |
| `paired_reference.sql` | Counterfactual comparison of paired IDs |
| `expected_answers.json` | Actual SQL results, including matched-stratum comparisons and query/config hashes |
| `benchmark_questions.json` | Eight questions, answer pointers, access scopes and scoring rules |
| `generation_manifest.json` | Configuration, file row counts and SHA-256 hashes |
| `incident_manifest.json` | Eligible count, changed IDs and intervention |
| `validation_report.json` | Integrity, allocation, incident, sampling diagnostics and reproducibility checks |

The SQL evaluator loads CSVs into **temporary in-memory SQLite**, not a second persistent application database. PostgreSQL ports in `database/phase2/` must match these saved results on the live server. The importer compares entire row multisets as well as metrics. Ground truths are never imported into PostgreSQL.

Success rate is `100 * successes / attempts`; percentage-point change is comparison minus baseline. An attempt is the denominator, not merchant count or amount. Periods are October 1-14 and October 15-28. Incident analysis separately uses October 15-21 and the post-window October 22-28. Dates and hours are local `+05:30`, not UTC. Each ISO weekday occurs four times in the full month slice; normalize weekday counts by calendar-day exposure when discussing seasonality.

For a like-for-like fortnight comparison, `standardized_periods` matches local hour and ISO weekday **within each bank/method**. Retain strata present in both periods; weight each by pooled attempts `(n_baseline + n_comparison)`. Weighted success rates are the weighted means of within-stratum rates. Report excluded attempts rather than inventing zero rates for missing strata. This comparison includes the post-incident week; use window-specific queries to localize the intervention.

Baseline diagnostics compare each bank/method success proportion and method-specific failure-reason proportion with its configured probability using `SE = sqrt(p*(1-p)/n)`. Flag absolute deviation above four SEs; do not resample to force a pass. This release has zero flags. These are descriptive, unadjusted diagnostics, not evidence of causal effects. The incident variant intentionally deviates and is checked against its exact paired intervention instead.

The **dataset gate passes**. The **analyst gate remains pending** because no AI analyst has been implemented. Benchmark scoring must distinguish normal volume patterns from reliability deterioration and must not require an invented outage in baseline. Exact counterfactual counts are available only to an administrator/evaluator comparing both variants; an analyst restricted to one schema must not claim hidden intervention knowledge.

Keep evaluation files, profiles, answer-bearing docs and plans out of the future analyst's filesystem/context. Give it only the selected read-only database connection and an answer-free schema dictionary. Database permissions cannot protect these files from the Windows account that owns the project.
