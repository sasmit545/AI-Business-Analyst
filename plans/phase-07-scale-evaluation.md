# Phase 7: Scale, evaluation and demonstration readiness

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisites: selected earlier dataset gates; a working analyst for application measurements

## Goal and benchmark tiers

Verify correctness and responsiveness as workload grows. Earlier phases already provide evaluation answers; this phase consolidates them and adds scale/concurrency measurements.

Use 40K, 100K, 500K and 1M attempt tiers. These are separate scale profiles, not replacements for the exact Phase 1 fixtures. Keep a small diagnostic fixture for every scenario. Increase size only to test segment coverage, query plans, memory or concurrent requests. Do not promise million-row support before measurement.

## Benchmark contract

Every case records question ID, dataset/profile version, seed, question, authorized scope, metric definition, time window/cutoff, reference SQL, expected result, rounding rules and required evidence. Keep answer files unavailable to the analyst.

Include at least these question families:

- Overall and segmented success rates, period change and top contributors.
- Mix versus performance effects, interactions and Simpson's paradox.
- Attempt rate versus order conversion, retry recovery and settlement backlog.
- Data-quality rejection, late-arrival qualification and unauthorized requests.
- Ambiguous time period or denominator: ask for clarification rather than silently choosing a materially different metric.

Use exact integer counts and money totals. Compare rates to the exact rational answer within 1e-9 before presentation rounding; compare displayed values at their stated precision. Narrative wording need not match exactly, but numerical statements, evidence references and causal caveats must.

## Measurements and execution

1. Record generator/schema/config versions, hashes, database/runtime versions, machine CPU/RAM, model/provider settings and measurement timestamp.
2. Run reference SQL and quality checks on every tier before testing AI answers.
3. Measure database execution separately from end-to-end model response. Disable application result caching for cold runs and report warm-cache results separately.
4. Run each deterministic query five times cold and five times warm. For end-to-end tests, run the selected demo question set three times and report every failure; do not retain only the best run.
5. Test concurrency 1 and 5 with at least 20 completed requests per level; report median/p95 latency, errors, timeouts, peak memory and model cost where available.
6. Re-run authorization isolation under concurrent requests and shared caches.

Provisional local-demo budgets are p95 database query <=2 seconds and p95 end-to-end response <=30 seconds at the selected demo tier. Treat these as product targets, not performance claims. Report the hardware/provider context; revise a budget explicitly if necessary rather than hiding a failed result.

## Completion and delivery

**Dataset gate:** deterministic regeneration and hashes pass; all exact fixture assertions and integrity checks pass; scale profiles have verified reference answers and complete manifests.

**Analyst gate:** all selected must-pass demo cases produce correct metrics and traceable evidence across the repeated runs; no unauthorized disclosure or fabricated execution; expected invalid-data cases fail safely. Report broader-suite pass rates separately so averaging cannot conceal a critical failure.

**Performance gate:** the selected demo size meets the declared budgets. Larger tiers may remain recorded limits; do not grow the demo solely to advertise row count.

Publish a benchmark report, reproducibility instructions and a short demo runbook covering one segment decline, one mix-shift explanation, one lifecycle distinction if enabled, and one safe failure. List which phase capabilities are implemented, which application gates remain pending and the largest measured tier.

Freeze the chosen dataset and application configuration for the demonstration. Synthetic benchmark success is not evidence of correctness on arbitrary real-world payment data.
