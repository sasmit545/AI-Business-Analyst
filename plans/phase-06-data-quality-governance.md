# Phase 6: Data quality, reliability and governance

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisites: lifecycle/scenario fixtures; Phase 1 quality checks already exist

## Goal and boundary

Extend paired clean/dirty fixtures and test scoped data access. Dataset corruption and policy definitions are deliverables here; actual authorization enforcement requires an application/database integration and has its own gate. Do not claim a policy file alone provides security.

## Defect catalogue and expected behavior

| Defect | Injection | Required response |
|---|---|---|
| Duplicates | Replay exact attempts; separately create conflicting rows with the same ID | Detect count inflation; block metrics until an explicit resolution policy is applied |
| Missing fields | Remove status, event time, bank or merchant ID | Report affected rows and metrics; never silently exclude failures |
| Orphan references | Unknown merchant, bank, order or attempt | Report incomplete joins; block affected segmented/lifecycle analyses |
| Timestamp errors | Missing timezone, invalid offset format, impossible ordering | Reject invalid records; valid offset strings normalize to a common instant |
| Late arrivals | Ingested_at after event time and reporting cutoff | Apply event-time window plus ingestion cutoff; report incompleteness and revision |
| Contradictory outcomes | SUCCESS plus a failure reason; settlement for failed attempt | Block affected calculations |
| Settlement inconsistency | Gross settled amount exceeds successful attempt amount | Report reconciliation defect and affected amounts |
| Schema drift | Rename a required field or add an optional field | Require versioned mapping for rename; tolerate documented optional additions |

For each defect type, use a default 10 disjoint target records in a small fixture. Preserve original records and record entity IDs, before/after values, defect type and expected validation codes in an evaluator-only manifest. Produce single-defect variants before combining them.

## Access-policy fixture

- Define an all-merchants analyst and a restricted analyst with allowlist M01-M05. Identity comes from the trusted application/test harness, never natural-language user input.
- Scope orders and payments by merchant; scope settlements through authorized attempts. Permit merchant dimension rows only for authorized merchants.
- Banks, methods and reason dictionaries are shared reference data. Deny bank_health to the restricted role in v1 because it contains global operational signals.
- Enforce scope in the execution layer, not only in prompts or UI. Run tests through the same path that executes generated queries.
- Verify that joins, totals, exports, error messages, query caches and follow-up questions do not reveal other merchants' records or aggregates. Cache identity includes the authorization scope.
- A request to ignore restrictions must not expand access. Evaluator manifests and answers must remain inaccessible to both roles.

## Work sequence and acceptance

1. Extend the corruption configuration and manifests without editing clean datasets.
2. Produce a validation report mapping defects to affected metrics and analyses that remain safe.
3. Create event-time/ingestion-cutoff reference queries and schema-compatibility fixtures.
4. Publish authorized-scope expected answers and application integration tests.

**Dataset gate:** injected defects match manifests exactly; clean fixtures pass; all seeded defects are detected; valid timezone normalization is not mistaken for corruption; reference answers differ correctly by role and cutoff.

**Analyst/application gate:** block unreliable calculations with actionable reasons, qualify late-arrival results, and enforce restricted access for every tested path. If enforcement is not implemented, mark governance integration pending rather than complete.

Deliver clean/dirty pairs, defect manifests, policy specification, compatibility fixtures, validation reports and scope-specific benchmark answers. Repairs must be explicit, reproducible transformations that preserve the original input.
