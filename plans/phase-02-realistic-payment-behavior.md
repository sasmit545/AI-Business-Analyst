# Phase 2: Realistic payment behavior

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisite: [Phase 1](synthetic-payment-dataset-plan.md) dataset gate

Implementation status (2026-11-21): dataset gate passed at 100,000 attempts per variant; analyst gate pending. See [usage and actual results](../docs/phase2-usage.md) and [validation report](../evaluation/phase2/validation_report.json). Native PostgreSQL is installed and all Phase 1/2 live tests passed. The unified database also supports the isolated Phase 3 lifecycle schema; current execution evidence is in reports/postgres_analytics_validation.json.

## Goal and boundary

Introduce heterogeneous business activity while preserving reproducibility and the three core tables. Use a new realistic_v1 profile; Phase 1 fixtures remain unchanged. Default to 100,000 attempts over October 1-28, 2026. Use 200,000 only if additional segment coverage is needed.

## Planned behavior

Store all generation assumptions in a versioned configuration. Initial defaults are synthetic and adjustable through new profile versions:

| Dimension | Initial rule |
|---|---|
| Merchant traffic | M01-M04 weight 20; M05-M10 weight 5; M11-M20 weight 1 |
| Bank shares | A/B/C/D/E weights 35/25/20/15/5 |
| UPI share by category | Retail 50%; grocery 75%; dining 80%; services 40%; CARD gets remainder |
| Amounts | Clipped lognormal draws in INR; median retail 1500, grocery 600, dining 350, services 2500; sigma 0.6; clip 10-100000 INR; round to integer paise |
| Hourly traffic | Default weight 1; 00:00-05:59 weight 0.25; dining 12:00-14:59 and 19:00-21:59 weight 3 |
| Weekend traffic | Dining and retail weight 1.3; other categories weight 1 |
| Bank/method reliability | UPI A-E: 98/97/96/95/94%; CARD A-E: 99/98/97/96/95% |
| Failure mix | UPI timeout/funds/authentication/limit weights 40/30/20/10; CARD 15/35/40/10 |

Allocate integer traffic counts with largest-remainder allocation and stable ID tie-breaking. Use seeded outcome draws for realistic profiles; record actual outcomes rather than claiming target percentages were achieved exactly. Derive named random streams for traffic, amounts and outcomes so adding a field does not change unrelated draws.

Build a paired incident fixture from the same baseline: for Bank B/UPI during October 15-21, convert 10% of eligible successful attempts into BANK_TIMEOUT failures using a stable ID-based selection. Preserve IDs, amounts and timestamps. Save baseline and incident variants separately.

## Work sequence and deliverables

1. Add the realistic profile and deterministic allocation/distribution rules.
2. Generate a no-incident baseline and its paired incident copy.
3. Independently profile category/merchant traffic, bank/method rates, amounts and hourly/weekday patterns.
4. Calculate actual expected answers with SQL for both variants and their difference.
5. Publish profile assumptions, data dictionary, hashes and validation results alongside benchmark questions.

No lifecycle tables, external data or general incident engine is required here.

## Acceptance

**Dataset gate:** Phase 1 regression results remain unchanged; joins preserve counts; distribution parameters are recorded; records obey bounds; high-volume merchant and dining peak patterns are present. Compare sampled rates to target probabilities using a documented four-standard-error diagnostic, flagging deviations rather than regenerating until a test passes. The incident changes only selected outcomes/reasons in the intended population.

**Analyst gate:** compare like-for-like hours, weekdays and segments; distinguish a normal high-volume period from a reliability incident; localize Bank B/UPI and quantify its change without calling seasonality a cause of failure. The no-incident fixture must not require the analyst to invent an outage.

## Handoff

Pass the profile configuration, paired fixtures and benchmark answers to Phase 3. Actual SQL answers remain exact for each generated release; only declared output rounding uses numerical tolerances.
