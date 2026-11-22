# Phase 5: Complex analytical scenarios

Created: 2026-11-21

[Roadmap](plan.md) | Prerequisite: [Phase 4](phase-04-business-scenarios.md)

## Goal

Test explanations that require more than finding the worst-performing group. Begin with small deterministic fixtures; add realistic-profile counterparts only after exact answers pass. Preserve isolated scenarios for debugging.

## Required fixtures

1. Simultaneous Bank B/UPI degradation and a separate merchant CARD authentication issue, with disjoint populations and individually measurable contributions.
2. An interaction: degradation only for Bank B/UPI above 500000 paise, concealing the effect in broader averages.
3. A Simpson's-paradox fixture: baseline has 20% CARD at 98% success and 80% UPI at 90%; comparison has 80% CARD at 96% and 20% UPI at 88%. Overall success improves from 91.6% to 94.4%, while both methods decline by two percentage points. Use 10,000 attempts per period.
4. A delayed-recovery fixture where retries occur after the incident window; compare initiation-time attempt metrics with order-cohort conversion.
5. A noncausal-correlation fixture where latency and failures share a configured common driver; no direct latency-to-outcome dependency. The analyst must not infer causality from association.
6. An overlapping fixture in which two configured degradations affect the same attempt population.

## Overlap and attribution contract

- For overlapping performance incidents, represent effects as success-probability multipliers in [0,1]. Combined probability equals baseline probability times each multiplier. Reuse each attempt's deterministic uniform draw across baseline, single-incident and combined variants.
- Select the visible failure reason from the highest-priority applicable incident that individually flips that attempt; if only the combined effect flips it, use the highest-priority applicable incident. Record all contributors in evaluator-only metadata. Reject priority ties on overlapping effects.
- Use a shared baseline and four variants for a two-incident overlap: none, A, B, A+B. Initially keep traffic and retries fixed/disabled for this attribution fixture so the population is identical.
- Compute evaluator intervention contributions with two-factor Shapley allocation, averaging each incident's marginal effect over both orders. Contributions must sum to the combined change. This is controlled-generator truth, not a causal claim the analyst can derive from observational tables.
- For analyst-visible descriptive attribution, use disjoint bank/method cells and the exact symmetric decomposition: mix = sum((w1-w0)*(r1+r0)/2); performance = sum((r1-r0)*(w1+w0)/2). Require positive support in both periods for these fixtures. Report results in percentage points.
- Do not add contributions from overlapping merchant and bank partitions. Display alternative breakdowns as alternative views of the same change.

## Work and verification

Build exact fixtures first, calculate SQL results independently, and store baseline/single/combined evaluator variants separately from application data. Verify that the common-driver fixture has no implemented latency-to-failure dependency. Preserve the configuration and generator version for each fixture.

**Dataset gate:** contributions reconcile to total change; paradox directions and percentages hold exactly; interaction filters select the intended population; delayed retries obey cutoff rules; scenario order does not change outputs.

**Analyst gate:** explain overall change, affected segments, quantified descriptive contributions, evidence, uncertainty and next investigations. Do not require it to recover hidden interventions that visible data cannot identify. Unsupported confident causal claims fail even when they accidentally match the generator's hidden answer.

## Deliverables

Scenario suite, controlled counterfactual variants, exact reference queries, expected numerical answers, and an explanation rubric distinguishing required observations from permissible hypotheses. No increase in table count or volume is required to finish this phase.
