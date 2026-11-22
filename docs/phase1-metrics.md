# Phase 1 metric definitions and expected interpretation

One row is one completed payment-service attempt. SUCCESS means the synthetic service recorded success; it is not evidence of authorization, settlement, order conversion, or infrastructure health. Values are constructed test conditions, not empirical claims about payment methods or real banks.

**Population and dates.** Include all valid attempts in one scenario. Baseline is October 1–14, 2026 inclusive; comparison is October 15–28 inclusive. Interpret dates in their explicit +05:30 local offset. Both periods contain exactly 10,000 attempts. Use the first 10 characters of the validated local timestamp for SQL bucketing; UTC date conversion would misclassify records near midnight.

**Success rate.** `successful attempts / all valid attempts`, displayed as a percentage. Compare rates in percentage points: `100 × (comparison successes / comparison attempts − baseline successes / baseline attempts)`. Numerators and denominators are exact integers; reference SQL rounds displayed rates and contributions to six decimal places. Float sums are rounded to the same precision before comparison. Do not round counts or tolerate incorrect aggregations.

**Data quality.** Validate the complete input first. Duplicate attempt IDs, missing/invalid timestamps, invalid dimensions or foreign keys, invalid methods/currency/amounts, and contradictory status/reason combinations block reference analysis. Do not silently exclude bad records to produce a different eligible population. The dirty fixture has no certified rate.

## Scenario A

| Population | Baseline successes / attempts | Comparison successes / attempts |
|---|---:|---:|
| Overall | 9,800 / 10,000 = 98% | 9,620 / 10,000 = 96.2% |
| Bank B/UPI | 980 / 1,000 = 98% | 800 / 1,000 = 80% |
| Each other bank/method cell | 980 / 1,000 = 98% | 980 / 1,000 = 98% |

Every merchant receives 50 attempts in each bank/method/period cell, with 49 successes normally and 40 in comparison Bank B/UPI. Each normal cell contains five failures for each of the four reasons. The affected cell retains these and adds 180 BANK_TIMEOUT failures, raising its timeout count from 5 to 185.

The overall decline is 1.8 percentage points, entirely associated with the Bank B/UPI cell. For this stable-volume partition, its contribution is `100 × (800/10000 − 980/10000) = −1.8` percentage points; all other cells contribute zero. Timeout labels increased, but rows do not prove an infrastructure outage or identify a technical root cause.

## Scenario B

| Method | Baseline successes / attempts | Comparison successes / attempts | Rate in both periods |
|---|---:|---:|---:|
| CARD | 7,840 / 8,000 | 1,960 / 2,000 | 98% |
| UPI | 1,800 / 2,000 | 7,200 / 8,000 | 90% |
| Overall | 9,640 / 10,000 | 9,160 / 10,000 | 96.4% → 91.6% |

Bank shares remain equal. At each bank, CARD has 80 attempts per merchant in baseline and 20 in comparison; UPI has 20 then 80. Successes are exact at bank/method/period level, with seeded shuffled assignment across merchants. Individual merchant success rates are not constrained to equality.

Let `w` be a method's attempt share and `r` its success fraction, with 0 for baseline and 1 for comparison. The SQL decomposition is:

`overall percentage-point change = 100 × Σ[(w1 − w0) × r0] + 100 × Σ[w1 × (r1 − r0)]`.

The first term is the mix effect using baseline rates; the second is the within-method effect using comparison shares. CARD contributes −58.8 percentage points of mix effect and UPI +54.0, summing to −4.8. Both within-method effects are zero. These component magnitudes arise from redistributing shares and must be interpreted together. More attempts use the lower-success method; neither method's rate deteriorates.

**Attribution partitions.** Sum disjoint bank/method cells or disjoint methods within their respective decomposition. Never sum bank, method, merchant, category, and region contributions together: these populations overlap. `bank_method_change.overall_change_contribution_pp` is a general difference in success shares; only in Scenario A's stable-volume design does it isolate a rate decline.

Machine-readable SQL results, including exact counts, appear in `evaluation/phase1/expected_answers.json`. The analyst application should infer conclusions from CSV evidence without access to those answers or the defect manifest. Its gate remains pending until an application exists.
