# Enterprise AI Business Analyst: Project and Phase 1 Context

Created: 2026-11-21

## Purpose of this document

This is a self-contained context brief for development of the payment business analyst alongside the Phase 1 dataset work. It combines the business challenge, the agreed dataset contract, the analytical scenarios and the longer-term roadmap. It describes the problem and expected behavior, not an application implementation plan or a technology recommendation.

Source documents:

- [Original business challenge](../notes/enterprise_ai_business_analyst.md)
- [Overall dataset roadmap and Phase 1 clarifications](plan.md)
- [Phase 1 dataset specification](synthetic-payment-dataset-plan.md)

This document is a consolidated snapshot of those sources. The original challenge defines the business requirements; the Phase 1 plan plus the roadmap's allocation clarifications define the dataset. Later source changes need reconciliation here. Dataset descriptions and expected results below are specifications, not a claim that generation or validation has already completed.

**Audience boundary:** this document is for developers and evaluators. It contains scenario answers and corruption details. Those sections are not runtime context for the analyst being evaluated; the analyst must calculate its findings from the supplied tables.

## Business problem

A payments business has transaction, merchant, bank, payment-method and settlement information spread across datasets. Business leaders want to understand changes in payment performance, identify contributing segments and decide what to investigate or do next.

Typical questions are:

- Why did payment success rates change?
- Which banks, merchants or payment methods contributed most to the decline?
- Is a decline broad or concentrated in a particular segment?
- Did the transaction mix change, or did comparable segments actually perform worse?
- What evidence supports the explanation, and what remains uncertain?

Today, answering these questions can involve hours of finding data, defining metrics, preparing queries and comparing results. The intended product is an AI business analyst that performs this analysis using supplied data and returns explanations traceable to executed calculations.

The challenge's original delivery horizon is 48 hours for a coherent working vertical slice. The separately agreed one-hour target applies only to preparing the Phase 1 dataset package, not the entire application or the seven-phase roadmap.

## Intended user experience and required capabilities

The business user asks a natural-language question. The system identifies relevant tables, metrics, dimensions and periods; creates and validates SQL or equivalent structured analysis; executes it; compares and segments the results; and presents a chart or table with an explanation.

The core requirements are:

- Use at least two related datasets. Phase 1 provides three.
- Support natural-language questions about business metrics and trends.
- Generate and actually execute SQL or equivalent structured analysis.
- Expose the query or analytical steps supporting the answer.
- Present useful visual evidence through charts or tables.
- Identify supporting datasets, filters and time windows for conclusions.
- Distinguish observed facts, hypotheses requiring further validation, and recommendations based on the findings.

The minimum demonstration includes executed analysis, a segmented result, visual evidence, an explanation connected to the original question, explicit caveats and at least one demonstrated data-quality or access-control failure. Phase 1 supplies the data-quality failure route; it does not supply access-control enforcement.

The challenge assesses analytical reasoning, data modelling, safe and reliable query generation, interpretation, traceability and communication. Query execution alone is not sufficient evidence of correct business analysis.

## Current scope versus future capability

Phase 1 concerns completed payment attempts, merchants and payer banks. It deliberately excludes orders, retries, pending attempts, settlements, refunds, customer identities, fraud modelling and access-policy simulation.

The business context mentions settlement data, but there is no settlement table in Phase 1. Likewise, there is no latency, bank-health telemetry or incident log. Questions requiring these fields cannot be answered from the current dataset.

The original challenge lists role-based access, additional data-quality checks, cohorts/drill-down, query cost/timeouts, caching, known-answer evaluation and uncertainty explanations as stretch capabilities. The agreed Phase 1 package does include known answers and specific quality defects, without making every enterprise feature mandatory.

The original failure considerations also include conflicting sources, unauthorized requests, ambiguous periods/denominators and unsafe or expensive queries. The clean Phase 1 fixtures do not simulate all of these. Absence of such fixtures is not proof that the application handles those failures.

## Why the data is synthetic

The public-data research revealed trade-offs between payment outcomes, related tables, failure details, availability and licensing. The agreed choice is original, reproducible synthetic data with controlled analytical outcomes, rather than copying or combining public records.

The design draws on the types of capabilities discussed in the research: bank and merchant segmentation, explicit outcomes, failure reasons, transaction identifiers, useful joins and deliberate quality defects. These are fictional test conditions, not measured characteristics of real banks or payment networks.

Fixed scenario counts provide independently checkable answers. A fixed seed of 42 controls shuffling and auxiliary variation. Success on these fixtures demonstrates behavior on controlled data; it does not establish reliability on arbitrary production payment data.

## Phase 1 data contract

There are two separate clean scenarios, each with 20,000 attempts and the same three-table structure: 40,000 clean attempts across the two scenarios. Each has 20 merchants and five banks. A dirty copy of Scenario A is a third, separate variant. Only one scenario/variant is active for an analysis; their rows are not combined into a single population.

### payments

| Field | Meaning |
|---|---|
| attempt_id | Unique payment-attempt identifier within a clean scenario |
| attempted_at | Attempt timestamp with explicit +05:30 offset |
| merchant_id | Reference to merchants.merchant_id |
| payer_bank_id | Reference to banks.bank_id |
| payment_method | UPI or CARD |
| amount_paise | Positive integer amount in paise |
| currency | INR |
| status | SUCCESS or FAILED |
| failure_reason | Internal synthetic reason for a failed attempt; absent for a success |

Each row is one completed payment attempt, not a purchase order, a lifecycle event or a settlement. No retries or pending attempts are represented.

### merchants

| Field | Meaning |
|---|---|
| merchant_id | Unique merchant key, M01-M20 |
| merchant_name | Fictional display name |
| category | retail, grocery, dining or services |
| region | North, South, East or West; the merchant's region |

Categories cycle in the listed order across merchant IDs. Regions are assigned in groups of five: M01-M05 North, M06-M10 South, M11-M15 East, M16-M20 West. Merchant region is not customer geography.

### banks

| Field | Meaning |
|---|---|
| bank_id | Unique bank key, BANK_A-BANK_E |
| bank_name | Fictional display name |

The payment's bank means payer/remitter bank for UPI and issuing bank for CARD. It is not an acquiring bank or payment gateway.

Both joins are many payment attempts to one dimension row. Valid joins preserve the payment-row count. IDs are scoped to a scenario; no cross-scenario relationship is implied.

These are logical field definitions. SQL engine, physical database types, frontend, model provider and agent framework have not been selected by these source plans.

## Metric and time semantics

- Payment success rate = successful attempts / all valid completed attempts in the selected population.
- Failures remain in the denominator. SUCCESS means the synthetic payment service recorded success; it does not prove settlement or define a separate authorization-stage metric.
- All Phase 1 attempts are completed and have a final SUCCESS or FAILED status in clean data.
- Quality defects do not authorize silently removing problematic records and presenting the resulting rate as complete.
- Coverage is October 1-28, 2026 in +05:30. Baseline is October 1-14 inclusive; comparison is October 15-28 inclusive.
- Equivalent half-open windows are [October 1 00:00, October 15 00:00) and [October 15 00:00, October 29 00:00), both at +05:30.
- Each period contains 10,000 attempts per clean scenario. Dates use equal integer daily quotas with remaining records assigned to ascending dates; time-of-day and amounts vary reproducibly.
- A percentage-point change is comparison rate minus baseline rate. A relative percentage change is that difference divided by the baseline rate. They are different quantities.
- Amount is not the success-rate denominator. Amount-based metrics, if reported, need their own explicit definition.
- Recorded failure reasons are BANK_TIMEOUT, INSUFFICIENT_FUNDS, AUTHENTICATION_FAILED and LIMIT_EXCEEDED. They are synthetic internal labels, not verified network response codes.

The documented comparison is sufficient for the benchmark questions. A user request with a different or ambiguous period/denominator cannot silently inherit an unrelated interpretation.

## Scenario A: deterioration within a segment

This fixture tests whether the analyst can localize a true within-segment performance change and quantify its contribution.

Each bank/method pair has 1,000 attempts per period. The five banks and two methods create ten disjoint cells. Each merchant receives 50 attempts in every cell and period. Normally, 49 of those 50 succeed. In Bank B/UPI during comparison, 40 of 50 succeed per merchant.

| Population | Baseline attempts | Baseline successes | Comparison attempts | Comparison successes |
|---|---:|---:|---:|---:|
| BANK_B + UPI | 1,000 | 980 | 1,000 | 800 |
| Other nine cells combined | 9,000 | 8,820 | 9,000 | 8,820 |
| Overall | 10,000 | 9,800 | 10,000 | 9,620 |

Overall success changes from 98% to 96.2%: a decline of 1.8 percentage points. Bank B/UPI changes from 98% to 80% while retaining a 10% share of attempts. Its 18-percentage-point decline therefore accounts for the entire 1.8-point overall decline. There are 180 additional failures, and transaction mix is unchanged.

Each normal cell has 20 failures: five of each reason. The affected comparison cell preserves those failures and adds 180 BANK_TIMEOUT failures. Overall timeout-labelled failures consequently rise from 50 to 230.

The evidence supports concentration in Bank B/UPI and an increase in timeout labels. It does not establish an infrastructure outage, a particular service defect or the efficacy of a routing change. Those are hypotheses or possible investigations, not observed facts.

Merchant volumes are stable, and all merchants share the affected cell's degradation. The fixture does not establish that one merchant caused the problem.

## Scenario B: transaction-mix shift

This fixture tests whether the analyst can distinguish changed composition from worsening within-segment performance.

| Method | Baseline attempts | Baseline successes | Comparison attempts | Comparison successes | Rate in both periods |
|---|---:|---:|---:|---:|---:|
| CARD | 8,000 | 7,840 | 2,000 | 1,960 | 98% |
| UPI | 2,000 | 1,800 | 8,000 | 7,200 | 90% |
| Overall | 10,000 | 9,640 | 10,000 | 9,160 | 96.4% then 91.6% |

Overall success falls by 4.8 percentage points, although neither method's rate changes. CARD share falls from 80% to 20%; UPI share rises from 20% to 80%. The aggregate rate is the volume-weighted mean of the method rates.

Each bank receives equal traffic: baseline has 1,600 CARD and 400 UPI attempts per bank; comparison reverses those counts. Each merchant receives 80 CARD and 20 UPI attempts per bank in baseline, with the reverse in comparison. Exact success counts are assigned at bank/method/period level and distributed by seeded shuffle. Identical merchant-level rates are not guaranteed.

The data supports a composition explanation. It does not support saying UPI reliability deteriorated, a bank became unavailable or users switched methods for a particular reason. Why the mix changed is not encoded as observable evidence.

This is a pure mix-shift example. The stronger Simpson's-paradox fixture, where every comparable segment deteriorates while the aggregate improves, belongs to Phase 5.

## Analytical interpretation shared by both scenarios

The worst success rate, the largest rate decline and the largest contribution to the overall change are not interchangeable. Volume shares matter. Bank, merchant, category and method breakdowns may describe overlapping records; their contributions cannot simply be added together as independent causes.

Observed facts are computed from records: rates, counts, timing, shares and failure labels. Hypotheses explain mechanisms that the available data cannot establish. Recommendations describe follow-up investigations or actions, not completed interventions or guaranteed outcomes.

Every reported finding needs a traceable dataset/variant, period, filter, grouping, numerator, denominator and executed query or equivalent computation. Expected answers are evaluator material, not a substitute for executing that analysis.

## Dirty Scenario A and failure behavior

The original clean Scenario A stays unchanged. Its dirty copy contains:

- 20 appended exact duplicate rows, resulting in 20,020 physical rows.
- 10 original records with missing timestamps.
- 10 other original records with merchant IDs absent from the merchant table.
- Disjoint original-ID groups for duplicates, missing timestamps and unknown merchants.

The expected validation result identifies all three defect categories and blocks affected analysis rather than silently dropping or repairing records. Duplicate counts can inflate metrics, missing timestamps undermine period assignment, and orphan merchants make joins incomplete. Their combined metric impact is determined by the actual selected rows, not by a predetermined corrupted success rate.

The evaluator-only defect manifest records the injected records. The application cannot rely on reading that manifest to claim it detected a defect. Any repair is a separate explicit transformation with its assumptions retained.

## Dataset deliverables and independent acceptance

The Phase 1 package is specified to include CSV datasets, a standard-library Python generator, independent reference SQL, machine-readable expected answers, a validation report, a generation manifest and a data dictionary.

The manifest records seed, profile ID, schema version, generator version, row counts and content hashes. Deterministic payloads exclude changing build timestamps. Running identical generation configuration twice produces identical dataset hashes.

The dataset gate checks exact counts/rates, all foreign keys, unique clean attempt IDs, outcome/reason consistency, positive integer amounts, valid timestamps, row-preserving joins and all expected dirty-copy failures. Independent SQL calculates results from generated rows rather than merely repeating constants in the generator.

The analyst gate is separate: actual executed analysis, correct interpretation, visible evidence, clear caveats and safe failure behavior. A passing generator report is not proof that the analyst meets the business challenge. File locations and commands for generated artifacts must come from the actual dataset handoff; this context does not claim those artifacts already exist.

## Longer-term roadmap context

Later phases add capabilities without changing a payment row from an attempt into something else. They are future direction, not requirements for the Phase 1 analyst demonstration.

| Phase | Added context | New analytical difficulty |
|---|---|---|
| 1: Foundation | Three tables; exact counts; two isolated scenarios; dirty copy | Segment deterioration versus transaction mix |
| 2: Realistic behavior | Unequal merchant/bank shares, amount distributions, seasonality and normal reliability differences | Distinguishing normal variation from an incident |
| 3: Lifecycle | Orders, retries, method/reason reference tables, settlements and bank health | Attempt rate versus order conversion; one-to-many joins; settlement completion |
| 4: Business scenarios | Configurable bank, merchant, method, regional, latency, retry and settlement incidents | Scoped time windows and downstream effects |
| 5: Complex analysis | Simultaneous and overlapping incidents, interactions, Simpson's paradox, delayed effects and confounders | Quantifying multiple contributors without unsupported causal claims |
| 6: Quality/governance | More corruption, ingestion delays, schema drift and authorized scopes | Identifying unreliable results and enforcing access outside the model |
| 7: Scale/evaluation | Versioned benchmarks, repeated runs, performance and concurrency measurements | Preserving correctness and isolation at measured workloads |

Evaluation and basic quality checks begin in Phase 1, not Phase 7. Larger row counts are optional tools for testing, not success criteria by themselves. Future phase details remain in the [roadmap and linked plans](plan.md).

## Important limitations and documentation expectations

The supplied plans do not choose an LLM/provider, agent architecture, database engine, deployment environment or UI framework. They do not establish live integrations, production access controls or performance measurements.

Phase 1 uses balanced, deliberately simple populations and exact outcomes. It lacks real-world operational provenance, incomplete lifecycle states and measured traffic patterns. Small merchant-level variations in Scenario B are not additional engineered incidents. Unsupported fields or causal evidence cannot be manufactured in the explanation.

The business challenge expects implementation assumptions, mocked dependencies, intentional exclusions, limitations and possible future improvements to be documented. The current deliverable is a coherent evidence-backed demonstration, with future phases preserving rather than silently replacing the initial benchmark.
