# Synthetic payment dataset roadmap

Created: 2026-11-21

## Purpose and current scope

Build a reproducible payment-analysis demonstration, then progressively introduce realistic behavior, relational depth, interacting incidents, and unreliable data. Increase volume only when it tests something a smaller fixture cannot.

This roadmap records the agreed overall direction. It authorizes no implementation by itself. The Phase 1 plan was the initial one-hour dataset deliverable; later phases are independently gated extensions. As of 2026-11-21, the user has authorized Phases 1-3. Their datasets and evaluation artifacts are implemented; analyst gates remain pending. Native PostgreSQL is installed and Phase 1/2 live tests passed. Read the current session context and database reports for Phase 3 verification status. See [Phase 2 validation](../evaluation/phase2/validation_report.json) and [session context](../AGENTS.md).

Sources: [dataset trade-offs](../notes/payment_datasets_tradeoffs.md), the existing Phase 1 specification, and the user's seven-phase proposal. Candidate datasets inform the design; records will be generated originally, not copied or merged from those datasets.

## Phase index

| Phase | Canonical plan | Main capability | Suggested scale, not a gate |
|---|---|---|---|
| 1 | [Foundational dataset](synthetic-payment-dataset-plan.md) | Exact outcomes, merchant/bank joins, two isolated scenarios, dirty copy | 3 tables; 40K clean attempts across two scenarios |
| 2 | [Realistic payment behavior](phase-02-realistic-payment-behavior.md) | Unequal traffic, amounts, seasonality, baseline reliability | Same 3 tables; 100K default, up to 200K |
| 3 | [Payment lifecycle and relationships](phase-03-payment-lifecycle.md) | Orders, retries, settlement, bank-health observations | 8 tables; 200K default, up to 500K |
| 4 | [Configurable business scenarios](phase-04-business-scenarios.md) | Reusable incident injection, timing, scope, latency and delays | Reuse 8 tables; no table-count target |
| 5 | [Complex analytical scenarios](phase-05-complex-analysis.md) | Overlapping effects, confounders, Simpson's paradox | Small diagnostic fixtures before large variants |
| 6 | [Data quality and governance](phase-06-data-quality-governance.md) | Corruption, late arrivals, schema compatibility, access-policy tests | Clean/corrupted pairs at existing sizes |
| 7 | [Scale and evaluation](phase-07-scale-evaluation.md) | Repeatable correctness, performance and concurrency benchmark | 40K, 100K, 500K, 1M; stop when useful |

## Shared rules

- Preserve Phase 1 as a regression fixture. New phases use versioned profiles; never replace its original files or change its expected answers.
- A payment row always represents an attempt. Orders, retries and settlements add relationships, not a silent reinterpretation of the row.
- Distinguish payment-service success, authorization, order conversion and settlement. Do not describe one as proof of another.
- Keep bank role, merchant region, eligible populations, time zone and observation cutoff explicit.
- Use fictional entities, INR integer paise and explicit +05:30 event timestamps. Synthetic distributions are design assumptions, not measured behavior of real networks.
- Keep source data, dirty variants and analyst-visible tables separate from generator configuration, defect manifests and evaluation answers.
- Maintain two kinds of truth: generator-known interventions, and conclusions actually supported by analyst-visible evidence. A known injected cause does not authorize unsupported causal claims by the analyst.
- Start independent SQL and reproducibility checks in Phase 1 and extend them in every phase. Phase 7 adds systematic scale testing; it does not introduce correctness testing for the first time.
- Once records are generated, their counts and rates have definite answers. Tolerances apply to generation targets and declared numerical rounding, not incorrect aggregations.
- Attribute changes using disjoint segments within one partition. Do not add bank, merchant and method contributions together because those populations overlap.

## Phase 1 implementation clarifications

These fill allocation details left open in the existing plan without changing its totals or schema.

- Number merchants M01-M20 and banks BANK_A-BANK_E. Merchant categories cycle over retail, grocery, dining and services; regions cycle independently in groups of five over North, South, East and West.
- Scenario A allocates 50 attempts to each merchant in every bank/method/period cell. Assign 49 successes per merchant normally and 40 for Bank B/UPI in the comparison period.
- Each normal bank/method/period cell has 20 failures: five of each documented reason. The affected cell retains those and adds 180 BANK_TIMEOUT failures.
- Scenario B allocates each bank's CARD attempts at 80 per merchant in baseline and 20 in comparison; UPI uses the opposite allocations. Assign exact successes at bank/method/period level and distribute them by seeded shuffle, without promising identical merchant-level rates.
- Allocate dates with equal integer daily quotas plus remainder records on ascending dates; seed time-of-day and amount variation. Use October 1-14 and October 15-28 inclusive as defined in Phase 1.
- The dirty copy has 20,020 rows, 20 extra duplicate occurrences, 10 missing timestamps and 10 orphan merchant references on disjoint original IDs. Clean data is untouched.
- Include seed, profile ID, schema version, generator version, row counts and content hashes in a manifest. Exclude wall-clock build timestamps from deterministic payloads.

## Delivery gates and sequencing

Each phase has two independent gates:

1. **Dataset gate:** files and relationships satisfy the specification; independent queries reproduce expected results; corruption/interventions match their manifests.
2. **Analyst gate:** the application answers the benchmark using visible evidence, respects its scope and handles failure correctly. Mark this gate pending until an application exists.

Normal progression is 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7. Quality checks exist from Phase 1, and performance may be measured earlier. Phase 6's policy fixtures can be designed without a working application, but permission enforcement cannot be certified without one.

The first demo may stop at Phase 1 plus one complete question-to-answer application flow. Later phases have no one-hour commitment. Before extending, preserve the previous fixture and verify the new capability on a small dataset.

## Eventual generator organization

Separate baseline construction, business-distribution configuration, incident injection, lifecycle generation, corruption, validation and evaluation as those capabilities become necessary. Phase 1 needs only a small script and configuration; do not build the full framework up front.

Every release contains datasets, a data dictionary and metric definitions, generator/configuration identifiers, reference SQL, expected answers and a validation report. Keep unresolved application gates visible rather than claiming a dataset alone proves AI quality or security.
