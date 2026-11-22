# Phase 4: Configurable business scenarios

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisite: [Phase 3](phase-03-payment-lifecycle.md)

## Goal and interface

Replace one-off incident edits with configuration-driven scenarios over the lifecycle schema. Reuse the eight tables. Volume stays at the Phase 3 default until a scenario needs more observations.

Each scenario configuration contains scenario_id, scenario_type, enabled, start_time, end_time, scope, effect, seed and priority. Use inclusive start/exclusive end timestamps. Scope filters may specify bank, method, merchant, merchant region and amount bounds. Reject unknown fields, empty time windows and impossible rates. A target rate applies only to the selected population/window, not the entire dataset.

Configurations, selected-record manifests and expected results stay outside the analyst-visible database.

## Scenario catalogue

| Type | Mutation | Evidence to evaluate |
|---|---|---|
| Bank degradation | Lower success in a bank/method/time slice; assign timeout reasons | Rates, failure counts, timing and aligned health observations |
| Merchant integration issue | Lower success for selected merchants; authentication failures | Merchant-local versus bank-wide changes |
| Method degradation | Lower success for one method | Attempt volume and contribution |
| Mix shift | Change traffic allocation before outcomes are assigned | Method shares versus within-method rates |
| High latency | Raise selected processing duration | Duration distribution and separately measured outcome association |
| Settlement delay | Add delay to due settlements' completion | Overdue amounts, age and merchant backlog |
| Retry change | Change retry probability before attempt-chain generation | Attempts per order versus order conversion |
| Regional issue | Lower performance for merchants in a region | Merchant-region evidence; no claim about customer location |

Initial profiles run one incident at a time. Include a bank fixture for October 15, 10:00-15:00+05:30, Bank B/UPI, target success 80%, BANK_TIMEOUT failures. Use nearest feasible integer success count and record rounding.

## Generation sequence and containment

1. Generate baseline order/traffic intent, applying mix changes only when enabled.
2. Generate attempt outcomes in sequence, applying scoped performance effects before deciding retries.
3. Derive completion times, order outcomes and settlements from the resulting attempts.
4. Apply latency/settlement effects at their respective lifecycle stage, then emit health observations.
5. Compare baseline and incident variants using stable IDs; record direct changes and expected downstream changes separately.

A failed attempt can cause new retries and change settlement eligibility. Therefore, containment means no unexplained changes outside the direct scope and documented dependency closure, not that every downstream record is unchanged.

For this phase, reject overlapping writes to the same field/population. Independent incidents may coexist; Phase 5 defines intentional overlap semantics. Equal configurations must be reproducible regardless of the order listed in the configuration file.

## Acceptance

**Dataset gate:** toggling an incident off reproduces the baseline; enabled scenarios change only declared fields and derived dependencies; boundary timestamps behave as specified; empty selections report an error rather than claim success; impossible targets report failure. Validate every catalogue type with a small fixture before increasing volume.

**Analyst gate:** locate the selected incident's segment and time window, quantify its effect, show supporting queries, and separate observations from hypotheses. Health evidence may support an investigation but does not prove causation.

Deliver reusable scenario configs, paired baselines, mutation manifests, reference SQL and benchmark cases. No new UI or application orchestration is included in the dataset work.
