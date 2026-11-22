# Enterprise AI Business Analyst
## Final System Design and Implementation Specification — v4.0

**Status:** Final architectural baseline; implementation pending validation  
**Date:** 21 November 2026  
**Challenge:** 48-hour enterprise AI business analyst demonstration  
**Data baseline:** Synthetic payments dataset through Phase 3 (physical schema and ground truths must be audited)  
**Architecture:** One LLM-powered analyst + deterministic analytical harness + evidence-backed generative UI  
**Primary stack:** Python, PostgreSQL, LangGraph, FastAPI, Pydantic, SQLGlot, Streamlit, Plotly

---

## 1. Executive decision

Build **one highly capable AI Business Analyst Agent**, not a collection of specialized agents. It understands payment-business questions, selects approved metrics, conducts bounded investigations, executes safe analyses, tests hypotheses, and explains supported findings. A **deterministic harness** owns semantics, data access, calculations, security, data quality, provenance, and verification. A **schema-driven UI engine** converts verified evidence into charts, tables, KPI cards, and interactive dashboards; it never executes model-generated frontend code.

**System principle:** *The agent decides what to investigate; trusted tools establish numerical facts; the verifier checks the claims; the UI makes the evidence understandable and interactive.*

This document deliberately separates (a) the **minimum working 48-hour demo**, (b) the **target v1 architecture**, and (c) **deferred enterprise features**. The 48-hour commitment is a functioning vertical slice, not the entire architecture.

### 1.1 Definition of success

A business user asks, for example: **“Why did UPI attempt success rate decline last week? Which banks contributed most? Show me the evidence.”** The system must:

1. Resolve the metric, denominator, time periods, dataset scope, and necessary joins.
2. Generate or compile SQL, validate it, and **execute** it against the supplied data.
3. Calculate a valid overall comparison and segmented bank/payment-method analysis.
4. Explain the largest observed drivers, distinguishing rate changes from transaction-mix changes.
5. Produce at least one chart or table based on the executed results.
6. Show SQL/analysis steps, dataset, filters, time windows, caveats, and recommended next actions.
7. Demonstrate **at least one safe data-quality or access-control failure**.

The minimum is met only when these behaviors are **observed in a working demo** and tested against independent reference answers—not merely specified on paper.

## 2. Scope and prioritization

| Layer | 48-hour demo — mandatory | Target v1 — incremental | Deferred |
|---|---|---|---|
| Data | ≥2 related real supplied tables; Phase 3 audit; approved metric | All relevant Phase 3 lifecycle tables | New enterprise data sources |
| Question answering | Natural language, metric selection, one diagnostic path | Adaptive strategy router, more complex multi-turn | General-purpose autonomous analyst across domains |
| Queries | Executed, validated read-only metric SQL | Guarded exploratory SQL with cost estimation | Unrestricted SQL or code execution |
| Analytics | Period comparison, segmentation, mix-vs-rate explanation | Orders, retries, settlements, bank-health analysis | Automatic causal identification |
| Evidence | SQL, inputs, period, denominators, caveats | Durable evidence store and claim-level verification | External audit integrations |
| Visuals | At least one real chart/table; aim for 2–3 | Schema-driven dashboards and drill-down | Arbitrary app generation and React migration |
| Safety | Read-only execution; one intentional safe failure | Metric-specific quality gates, authorization, budgets | Full production multi-tenant hardening |
| Evaluation | Golden questions and a complete demo test | Adversarial/semantic/visual regression suites | Production-scale continuous evaluation |

The target design must **not** hold the demo hostage. Deliver the end-to-end minimal path first, then deepen individual modules.

### 2.1 Explicit non-goals

No multi-agent swarm; no LLM-written arbitrary Python, HTML, JavaScript, or executable UI code; no independent agent with direct database credentials; no claim of causal proof from a correlation; no expectation that Phase 1 benchmark numbers apply to Phase 3; no blanket promise of production-grade RBAC, high availability, or all enterprise connectors within 48 hours.

## 3. System architecture and trust boundaries

```text
Business user / Streamlit chat + analytics workspace
                        |
                        v
             FastAPI request boundary
       (identity, scope, validation, rate limits)
                        |
                        v
         Context and semantic retrieval manager
                        |
                        v
          SINGLE AI BUSINESS ANALYST AGENT
        (intent -> plan -> act -> observe -> replan)
                        |
                 Typed tool calls
                        v
              ANALYTICAL HARNESS
      +----------------+---------------------+
      | semantic layer | query compiler      |
      | schema catalog | safe SQL executor   |
      | quality gates  | analytical functions|
      | evidence store | claim verifier      |
      +----------------+---------------------+
                        |
               Read-only PostgreSQL
                        |
             Verified result artifacts
                        |
        Narrative + typed dashboard specification
                        |
           Schema/lineage/permission validator
                        |
          Trusted Streamlit/Plotly renderer
                        |
          Answer, charts, table, SQL, caveats

Separate: independent benchmark/evaluation process
```

**Agent authority:** Interpret intent; select analytical strategies and approved metric IDs; form, prioritize, test, weaken, and retire hypotheses; choose tools; decide whether additional evidence is useful; draft narrative and visualization structure.

**Harness authority:** Enforce approved definitions, scope, query policy, deterministic calculations, time/cost budgets, evidence storage, quality gating, claim validation, and UI-spec validation. The agent cannot overrule a rejected query or a BLOCK result.

**Frontend authority:** Render registered components only. Convert selection or filter events to typed interaction intents routed through FastAPI. The frontend does not trust generated SQL or UI executable code.

**Evaluator authority:** Maintain expected answers and failure fixtures independently from the agent runtime; benchmark truth must not appear in runtime semantic context or accessible tables.

## 4. Phase 3 data integration and semantic foundation

The roadmap describes conceptual domains: **orders, payment attempts, retries, merchant and bank dimensions, payment-method/failure-reason references, settlements, and bank-health observations**. These are *expected domains*, not verified physical table or column names.

### 4.1 Mandatory M0 schema audit

Before writing the production query templates, inspect the actual generated Phase 3 PostgreSQL schema and artifacts. Output:

- A versioned manifest: tables/views, keys, row counts, nullable fields, indexes, timestamps, time zones, allowed statuses, data version, and fixture seed if present.
- An explicit grain for each relation: order, attempt, retry event, settlement obligation/entry, and bank-health observation.
- Authorized join graph with keys, cardinality, many-to-many warnings, safe aggregation patterns, and filter propagation rules.
- Lifecycle rules: attempts per order; sequence ordering; what qualifies as a retry; terminal/eligible outcomes; settlement completion and lateness; cohort maturity.
- A quality catalog mapping known dirty cases to affected metrics and expected PASS/WARN/BLOCK decisions.
- Independent reference SQL and expected answers for benchmark scenarios. Store separately from the runtime agent.

**Non-negotiable invariant:** Aggregation is performed at the metric’s defined grain. One order with multiple attempts, or one payment with several settlement records, must not become multiple independent orders/payments through a naïve join.

### 4.2 Version-controlled semantic catalog

Every approved metric contract includes:

`metric_id`, display name, business definition, base grain, numerator, denominator, eligible population, terminal/status rules, event-time or processing-time basis, timezone, observation cutoff, cohort maturity, required data, safe join paths, supported filters/dimensions, unit, aggregation method, quality dependencies, and semantic version.

| Metric | Contractual meaning | Key caution |
|---|---|---|
| Attempt success rate | Successful eligible completed attempts ÷ eligible completed attempts | Attempt grain; exclude or explicitly handle in-flight attempts |
| Order conversion | Eligible orders with ≥1 qualifying successful attempt ÷ eligible orders | Order grain; multiple attempts do not duplicate orders |
| First-attempt success rate | Eligible first attempts that succeeded ÷ eligible first attempts | Deterministic first-attempt sequencing |
| Retry uptake | Eligible first-failure orders with subsequent retry ÷ eligible first-failure orders | Define observation horizon |
| Retry recovery | Failed-first-attempt orders eventually successful ÷ defined first-failure population | Separately label recovery *among retried* orders |
| Settlement completion | Fully settled eligible obligations ÷ settlement-eligible obligations at cutoff | Count and amount reconciliation are distinct |
| Bank performance/health | Payment rate and aligned operational observations | Missing telemetry and timing lag limit inference |

The demo may initially expose only attempt success rate and its segmentation. The remaining definitions are targets once confirmed against the actual dataset.

### 4.3 Time, defaults, and ambiguity

- Use **explicit comparison windows** and state whether endpoints are inclusive/exclusive; normalize timezone before comparison.
- Specify metric denominator and cohort maturity. Exclude incomplete cohorts when approved by the metric contract, or label results provisional.
- If the user omits a time period or denominator and the result would materially change depending on the choice, **ask one clarification** before calculating.
- Otherwise use an approved, documented semantic default (e.g., last complete 7-day window vs preceding comparable 7-day window) and **disclose the assumption**. Never invent a universal default if the dataset or business contract does not support one.
- Never silently substitute order conversion for attempt success rate merely because the phrase “success rate” appears.

### 4.4 Disagreement between sources

When two sources disagree on the same metric, first compare *grain, numerator/denominator eligibility, event vs processing timestamp, timezone, freshness/cutoff, deduplication, status mapping, and filter coverage*. Prefer an explicitly approved system-of-record definition where one exists. If reconciliation fails, display both measured values with their definitions and quality status, explain the disagreement, and **do not assert one definitive answer**. Record this as a reproducible conflict test.

## 5. Single-agent investigation engine

### 5.1 Strategy router

Classify requests into supported strategies:

- **Direct:** retrieve a verified measure, trend, simple comparison, or presentation change.
- **Diagnostic:** investigate a decline/anomaly, compare cohorts, decompose contributions, or examine lifecycle events.
- **Clarification/limited answer:** a required metric or scope is ambiguous, unavailable, or blocked.

### 5.2 Adaptive diagnostic loop

```text
Authorize scope -> Resolve question -> Load metric context
 -> Establish baseline -> Form hypotheses -> Select next test
 -> Execute typed tool -> Observe result and quality
 -> Update hypothesis states -> (replan or stop)
 -> Verify claims -> Build response/UI spec -> Persist trace
```

Hypotheses have `id`, statement, affected segment/period, supporting evidence IDs, contradicting IDs, status (`untested`, `supported`, `weakened`, `inconclusive`), and proposed next test. The agent prioritizes tests likely to separate competing explanations, rather than blindly running all available tools.

**Stop when:** the supported question is answered; next tests provide little expected value; required data is unavailable; a relevant quality gate blocks a claim; a limit is reached; or user clarification is required. A stop must still return a useful partial result with explicit limitations where possible.

### 5.3 Structured state and context

Versioned Pydantic contracts: `QuestionContext`, `InvestigationState`, `AnalysisStep`, `Hypothesis`, `ToolRequest`, `ToolResult`, `EvidenceRef`, `Claim`, `DashboardSpec`, `ExecutionBudget`.

`InvestigationState` stores at least investigation/thread IDs; authorized subject and dataset scope; data/schema/semantic versions; normalized intent; metric IDs; grain; filters and time windows; working plan; hypothesis statuses; completed steps; compact observations; evidence references; quality flags; current execution budget; and last UI-spec version.

Four context layers:

1. **Trusted semantic context:** retrieved approved business definitions and join rules.
2. **Working investigation context:** plan, hypotheses, observations, pending work, and remaining budget.
3. **Durable evidence:** complete SQL, bound parameters, result artifacts, calculations, checksums, timestamps, version and quality metadata.
4. **Conversation context:** previous question, inherited filters/windows, and user presentation preferences.

Compact narrative history, **never** metric definitions, authorization scope, original evidence, or numerical source-of-truth. Follow-ups inherit relevant filters unless changed, but must be reauthorized. Store checkpoints using LangGraph; replay non-idempotent writes with idempotency keys.

## 6. Tool and execution contracts

Expose a small, typed model-facing registry; implement analytical operations as independently testable Python services.

| Tool | Required behavior |
|---|---|
| `get_semantic_context` | Return authorized metric definitions, grains, relationships, quality constraints |
| `inspect_schema` | Return only approved metadata and relation structure |
| `run_metric_analysis` | Compile/execute an approved metric query for trend, period comparison, or segments |
| `run_exploratory_query` | Optional guarded SQL fallback when approved metric templates cannot answer |
| `check_data_quality` | Return rule-level PASS/WARN/BLOCK for affected scope |
| `analyze_contributions` | Compute and reconcile mix and within-segment effects |
| `analyze_lifecycle` | Order conversion, attempts, retries, settlement calculations |
| `align_bank_health` | Align operational evidence and payment observations in time |
| `get_evidence` | Retrieve persisted result metadata and verified artifacts by reference |
| `build_dashboard_spec` | Propose registered UI components referring to verified evidence |

Every tool request includes user/scope and investigation IDs, metric/time/filter context, resource budget, and typed arguments. Each tool result includes `status`, typed data or artifact reference, `evidence_id` when data is produced, `quality_status`, `elapsed_ms`, and a safe structured error where relevant. Do not let the LLM invoke arbitrary functions or override protected parameters.

### 6.1 Safe query pipeline

**Preferred path:** approved metric selection → deterministic SQL compilation → AST/contract validation → resource checks → authorized read-only execution → versioned results.

**Fallback path:** model-proposed SQL → SQLGlot PostgreSQL parse/AST policy → one-statement SELECT-only restrictions → allowlisted relations/functions and columns → authorized join/grain review → parameter binding → bounded query/estimated cost → read-only execution.

Enforce protections independently of the agent:

- Dedicated least-privilege PostgreSQL role, read-only transaction, explicit schema/table permissions; optionally row-level security for tenant scope.
- No access to ground-truth/evaluation schemas; reject modifications, DDL, administrative queries, unauthorized functions, dangerous constructs, and multiple statements.
- Parameterize filter values; prevent text fields returned from the DB from acting as instructions.
- Configurable statement timeout, query planning/cost safeguards, limits on returned rows/bytes, maximum query count, safe error messages, cancellation, and auditing.
- Retain executed SQL and parameters but mask secrets or sensitive data in the user-facing trace.
- Fix query errors only when classified as repairable; never relax authorization, grain, or definitions to force a result.

**Version consistency:** Prefer a stable dataset snapshot across the investigation. Where this is impractical, pin the known data and semantic version/cutoff, detect change between queries, and warn when comparison consistency cannot be guaranteed.

### 6.2 Caching (optional stretch)

Introduce caching only after correctness is demonstrated. Cache keyed by tenant/authorized scope, normalized metric/query and bound parameters, time window, semantic and dataset versions, and quality/cutoff status. Never share cache entries across unauthorized scopes; invalidate on version changes. Caching must not hide stale data or alter evidence lineage.

## 7. Analytical reasoning and mathematical correctness

For diagnostic payment-rate declines, start with an aggregate baseline and denominator, then inspect supported segment rates/volumes, contribution ranking, changes in transaction composition, failure categories, and—only if relevant—retries, order conversion, settlement outcomes, and bank telemetry.

**Always distinguish:** worst current segment vs largest deterioration; largest raw failure volume vs largest contribution to change; attempt success vs order conversion; retry uptake vs recovery; payment completion vs settlement; correlation vs causation.

### 7.1 Exact mix-versus-rate decomposition

For **mutually exclusive, exhaustive segments** whose definitions remain consistent across periods, let `w(i,t)` be segment `i`'s share of eligible attempts and `r(i,t)` its success rate in period `t`. Overall rate `R(t) = Σ_i w(i,t) × r(i,t)`.

- **Mix contribution, segment i:** `(w(i,1) - w(i,0)) × (r(i,0) + r(i,1)) / 2`.
- **Within-segment rate contribution:** `(r(i,1) - r(i,0)) × (w(i,0) + w(i,1)) / 2`.
- **Reconciliation:** `Σ_i [mix contribution + rate contribution] = R(1) - R(0)` within a documented numerical tolerance.

Use deterministic functions for this calculation. Handle newly appearing/disappearing segments using an explicitly defined convention before applying the formula; otherwise mark decomposition unavailable. Compare rates in fraction units internally and display percentage-point differences correctly. Never add independently generated overlapping bank/merchant/method contributions as though they were disjoint causes.

A detected bank-health anomaly may **support a hypothesis**; it does not independently prove that bank health caused the payment decline.

## 8. Data quality, uncertainty, and failure handling

Quality checks are **metric-scoped**, executed as lightweight preflight checks and targeted checks after relevant queries.

| Class | Examples | Expected behavior |
|---|---|---|
| Identity/referential | Missing/duplicate IDs, broken keys | Flag, quantify, and block affected measures if material |
| Lifecycle | Invalid transitions, unordered attempts/retries | Warn/block attempt- or retry-dependent claims |
| Temporal | Incomplete cohorts, timezone errors, delayed events | Apply contract cutoff or disclose provisional numbers |
| Aggregation | Join multiplication, duplicated settlement entries | Block/recompute at correct grain |
| Reconciliation | Amount/count mismatch, inconsistent statuses | Warn/block settlement-specific conclusions |
| Telemetry | Missing/late bank health | Limit bank-health inference, not unrelated payment metrics |
| Authorization | Request for forbidden table, bank, or tenant | Deny query and give safe explanation |
| Query safety | Expensive/unsafe SQL | Reject or constrain; suggest a narrower scoped query |
| Source conflict | Two inconsistent metrics | Reconcile definitions or surface both with caveats |

`PASS` = qualified metric can be reported. `WARN` = answer is permitted with quantified limitation. `BLOCK` = affected claim cannot be asserted reliably. Each quality record includes rule ID, affected metric/filter/period, measured impact where possible, evidence ID, and remediation. A failed *bank-health* check must not automatically block clean attempt-level payment rates.

**Uncertainty policy:** Report evidence coverage, sample size/denominator, sensitivity to assumptions, known missing data, conflicting sources, and untested alternatives. Do not fabricate model confidence percentages. When evidence is insufficient, state what is established, what remains hypothetical, and which next test could resolve the uncertainty.

## 9. Evidence, claim verification, and response integrity

Every significant numerical statement must resolve to durable executed evidence, not model memory or an unverified chart spec.

**Evidence record:** investigation ID, authorization scope, dataset/schema/semantic version, metric and grain, query text/hash and parameters, filters and comparison windows, observation cutoff, execution time, result artifact/checksum, numerator/denominator, quality checks, and validation result.

**Claim record:** statement type (`fact`, `comparison`, `derived_attribution`, `hypothesis`, `recommendation`), metric/units, numeric values if any, period and filters, one or more evidence IDs, arithmetic validation result, and limitations.

The deterministic verifier must:

1. Confirm evidence belongs to the authorized investigation/snapshot and approved metric.
2. Recompute percentages, changes, rates, rankings, and decomposition totals from result artifacts.
3. Check matching units, denominators, windows, population filters, and quality status.
4. Reject invented figures, unsupported causal assertions, incompatible sources, and charts referencing nonexistent result columns.
5. Return actionable failure reasons so the agent can correct or remove a claim; never silently publish an invalid statement.

A final response is structured as **direct answer → observed facts → ranked supported drivers → unresolved hypotheses → recommended next actions → visuals → expandable technical evidence and caveats**. Make the difference between measured observations and operational recommendations explicit.

## 10. Generative UI and interactive visualization

The UI extension is part of the **same single-agent system**, not a separate visualization agent.

```text
Verified evidence -> Visualization planner -> DashboardSpec
  -> schema/lineage/authorization validator -> trusted renderer
  -> selected chart/filter event -> typed DrilldownIntent
  -> FastAPI authorization -> existing or new investigation
```

**Allowed component registry:** `kpi`, `line_chart`, `bar_chart`, `stacked_bar`, `heatmap`, `funnel`, `data_table`, `narrative`, `quality_warning`, and `evidence_panel`. The 48-hour demo needs only KPI, bar/line, and table/evidence view.

Each `DashboardSpec` declares version, investigation ID, title, data version, component IDs, type, layout, verified `evidence_id`, approved metric/units, mapping of existing result fields, time/filter scope, and allowed interactions. The schema validator rejects unknown component types, unauthorized fields, inconsistent units, missing evidence, unsupported aggregation, and excessive dashboard complexity. **No arbitrary HTML, JS, Python, or SQL in the UI spec.**

**Two interaction paths:**

- *Presentation-only change*: “Turn this into a bar chart.” Re-render the same compatible verified result without querying again.
- *Data-changing drill-down*: “Show only Bank B” or click Bank B. Send a typed filter intent to FastAPI, reauthorize it, run necessary analysis, verify new evidence, and update linked charts/narrative.

**Initial renderer:** Streamlit + Plotly with visible SQL/metric inspection, quality notes, and selection-based drill-down where feasible. React + component registry is a future migration only if Streamlit limits become material.

### 10.1 Example UI contract (illustrative structure; no invented business data)

```json
{
  "version": "1.0",
  "investigation_id": "inv_example",
  "title": "UPI attempt success analysis",
  "dataset_version": "<from-run-metadata>",
  "components": [
    {"id":"rate","type":"kpi","metric_id":"attempt_success_rate","evidence_id":"ev_overall"},
    {"id":"trend","type":"line_chart","evidence_id":"ev_trend","x":"date","y":"attempt_success_rate","unit":"percent"},
    {"id":"banks","type":"bar_chart","evidence_id":"ev_bank","x":"bank","y":"attempt_success_rate","unit":"percent","interactions":["drilldown"]},
    {"id":"sql","type":"evidence_panel","evidence_id":"ev_bank"}
  ]
}
```

Field names in this contract are illustrative result aliases, **not assumptions about PostgreSQL table columns**.

## 11. End-to-end demonstration walkthrough

**Example request:** “Why did UPI payment attempt success drop last week? Break it down by bank and show me a chart.”

1. **Authorize** the user's accessible dataset and permitted bank/merchant scope.
2. **Ground** the request in the approved `attempt_success_rate` definition and comparison window. Clarify genuinely ambiguous periods/denominators or disclose an approved default.
3. **Plan** baseline comparison, bank segmentation, and mix/rate decomposition (if complete compatible segments are available).
4. **Compile and execute** parameterized read-only PostgreSQL queries through `run_metric_analysis`; store SQL, parameters, versions, and evidence IDs.
5. **Validate** denominator consistency, join grain, missing records, status eligibility, and data-quality gates.
6. **Investigate** highest-contributing bank segments and relevant failure reasons, without interpreting correlation as proof of cause.
7. **Compute** exact decomposition and reconcile contributions to the measured overall change.
8. **Verify** proposed claims, numbers, rankings, and limitations against source artifacts.
9. **Render** a direct business answer, an overall KPI, a trend/chart, bank comparison, SQL/evidence view, and caveats.
10. **Demonstrate a failure**: run a fixture with an affecting duplicate or missing-data issue (or an unauthorized-scope request); the system must warn/block the affected conclusion or reject the request with no data disclosure.

No benchmark numerical result is hard-coded into the narration. Actual values come from executed Phase 3 queries.

## 12. Implementation stack and module boundaries

| Concern | Technology / boundary |
|---|---|
| API | FastAPI with typed request/response contracts |
| Agent loop and checkpointing | LangGraph; PostgreSQL-backed checkpoint persistence |
| Schema/contracts | Pydantic and versioned YAML metric definitions |
| Database | PostgreSQL, dedicated read-only role, actual Phase 3 dataset |
| SQL compiler | Reviewed templates/AST composition for registered metrics |
| SQL validation | SQLGlot plus PostgreSQL permissions and executor policy |
| Analytics | PostgreSQL + independently tested Python arithmetic |
| Evidence | Versioned PostgreSQL metadata and bounded result artifacts |
| UI | Streamlit + Plotly, registered renderer components |
| Tests | Pytest, independent SQL reference queries, scenario fixtures |
| Observability | Structured traces, audit logs, counters and cost/latency metrics |

Suggested repo layout:

```text
app/
  api/              # Request/auth/scope contracts
  agent/            # LangGraph state, routing, planning, policies
  context/          # Semantic retrieval and conversation carryover
  semantic/         # Versioned metric and relationship contracts
  query/            # Compiler, SQL policy, executor
  analytics/        # Period, segment, mix/rate, lifecycle computations
  quality/          # Data-quality rules and severity mapping
  evidence/         # Artifact storage and claim verification
  ui_specs/         # Dashboard types, validation, interaction intents
  frontend/         # Streamlit/Plotly renderer
  observability/    # Traces and audit events
configs/            # Versioned non-secret configuration
tests/              # Unit and integration tests
eval/               # Independent benchmark runner and private truths
```

Avoid introducing a vector database until semantic-context search scale creates a measurable need. Keep library/framework choices replaceable behind typed boundaries.

## 13. Resource budgets, resilience, and observability

Initial configurable guardrails (to tune after measurement): 8–12 agent analytical calls per diagnostic investigation, at most two **repair** attempts per invalid query, 10-second initial PostgreSQL statement timeout, bounded preview rows/bytes, overall time/token/cost ceilings, and dashboard component caps. These are *configuration starting points*, not fixed success criteria. If the budget ends, return supported partial conclusions and note what remains unresolved.

Log investigation ID, scope fingerprint, selected metric and semantic version, strategy/hypothesis transitions, tool name, SQL hash, query runtime, rows returned, budget consumption, quality results, evidence IDs, claim-verification decisions, and dashboard validation. Do not log secrets, credentials, or unnecessary sensitive row payloads.

Treat model tool requests as repeatable but not inherently idempotent. Persist checkpoints, retry only classified errors, prevent duplicate evidence writes, and ensure a failed visualization step cannot alter raw analytical evidence.

## 14. Implementation milestones and exit criteria

| Milestone | Build | Exit gate |
|---|---|---|
| **M0 — Dataset audit** | Actual Phase 3 schema, grain/joins, lifecycle, quality fixtures, benchmark answers | Catalog matches physical data; independent known-answer queries run |
| **M1 — Trusted analytics** | Approved metric SQL, read-only executor, period/segment analysis, quality checks | Reference SQL matches; prohibited requests rejected |
| **M2 — Agent harness** | Single agent, strategy router, structured state, plan/observe/replan, evidence refs | Real multi-step investigation completes with bounded trace |
| **M3 — Analytical depth** | Mix/rate decomposition, lifecycle tools, follow-up context | Attribution reconciles; representative scenarios correct |
| **M4 — Claim verification** | Claim schema, arithmetic/lineage verifier, ambiguity/conflict handling, tests | Unsupported figures or conflicting claims cannot be published |
| **M5 — Dynamic UI** | Schema-driven dashboards, KPI/charts/table, evidence panel, drill-down | Verified visuals render; invalid UI specs rejected; drill-down preserves scope |

### 14.1 Recommended 48-hour build order

1. **First:** M0 and the smallest correct M1 path using attempt success rate on two related tables. Produce one known-answer SQL test.
2. **Second:** A minimal M2 question-to-query-to-answer loop. Record query and evidence in the UI.
3. **Third:** Bank segmentation, period comparison, and mix decomposition with a reconciled result.
4. **Fourth:** One or two actual Plotly charts, a compact table, and visible SQL/filters/caveats.
5. **Fifth:** A data-quality or access-control negative demonstration and a repeatable end-to-end test.
6. **Only after passing the demo gate:** expand hypotheses/memory, full claim-by-claim verification, lifecycle coverage, dynamic dashboard layouts, and richer interactions.

This ordering is a **delivery sequence**, not a requirement to finish all of M0–M5 in 48 hours.

## 15. Verification and acceptance tests

### 15.1 Mandatory demo gate — all required

- [ ] At least **two related actual datasets/tables** are used in an executed analysis.
- [ ] A **natural-language** payment metric/trend question is answered from supplied data.
- [ ] A validated SQL query (or equivalent structured analysis) is **executed**, not simulated.
- [ ] The user can inspect executed SQL/steps, metric, denominator, dataset, filters, and windows.
- [ ] The answer includes an **overall period comparison and segmented bank/payment-method analysis**.
- [ ] At least one chart/table displays **real results** from those queries.
- [ ] Facts, hypotheses, recommendations, and caveats are distinguishable.
- [ ] A missing/duplicated-data case **or** unauthorized request fails safely and visibly.
- [ ] At least one independent expected-answer test matches measured values, with correct grain.
- [ ] The full journey runs from the UI without hard-coded chart data or fabricated conclusions.

### 15.2 Stretch and robustness tests

- [ ] Ambiguous time period/denominator triggers clarification or disclosed contract default.
- [ ] Two sources with mismatched metric definitions are reconciled or explicitly reported as conflicting.
- [ ] A pure transaction-mix shift is correctly distinguished from within-bank deterioration.
- [ ] Attempt and order denominators are not confused; one-to-many joins do not inflate results.
- [ ] Expensive or unsafe SQL is rejected within executor policy.
- [ ] Missing bank telemetry limits telemetry claims without invalidating unrelated attempt rates.
- [ ] Claim verifier rejects unsupported percentage-point changes and fabricated rankings.
- [ ] Chart validator rejects a missing or unauthorized evidence field.
- [ ] A chart-driven drill-down uses a reauthorized typed filter and correct inherited windows.
- [ ] Checkpoint replay and query retries do not duplicate durable evidence.

Independent reference queries, seeded synthetic failures, and evaluator-only fixtures are not exposed to the runtime agent. Existing Phase 1 known-answer fixtures may remain regression tests; **their numerical answers must not be assumed for Phase 3**.

## 16. Risks, trade-offs, and explicit decisions

| Risk / tension | Decision |
|---|---|
| Complex reasoning takes longer than 48 hours | Ship the complete minimal vertical slice before advanced strategies |
| LLM writes numerically plausible but wrong answers | Ground all material figures in evidence; recompute and reject unsupported claims |
| Correct SQL but wrong business denominator | Semantic catalog and grain-aware compiler are mandatory |
| SQL AST appears safe but violates permissions | Independent PostgreSQL least privilege and scope policy remain authoritative |
| Cross-source metrics disagree | Reconcile contracts or state unresolved conflict; never silently cherry-pick |
| Many-to-one/many-to-many join explosion | Pre-aggregate to required grain and use join-cardinality tests |
| Agent plans too many tools | Direct/diagnostic routing, budgets and early-stop logic |
| “Generative UI” allows unsafe executable output | Registered components and validated declarative specs only |
| Fast UI implementation conflicts with long-term flexibility | Use Streamlit/Plotly first; keep UI schema portable |
| Inconsistent data across multi-step queries | Snapshot/version/cutoff pinning; warn where unavailable |

## 17. Final definition of done

**For the 48-hour challenge:** All Section 15.1 checks pass in one coherent live demonstration. The user gets an executed, correctly segmented analysis with verified visual data, visible query evidence, meaningful caveats, suggested next steps, and one demonstrated safe failure. Any mock, missing feature, or operational limitation is explicitly identified.

**For target v1:** The agent can select and test investigative hypotheses, handle more Phase 3 lifecycle questions, preserve context across follow-ups, use claim-level evidence verification, and generate safe interactive dashboards whose filters and underlying data stay consistent.

**Final architectural statement:** **One intelligent analyst controls the investigation; a deterministic, context-aware harness governs data access and numerical truth; a validated UI engine turns evidence into interactive business understanding.**

---

## Appendix A — Original challenge traceability

| Original specification | Design location | Demo obligation |
|---|---|---|
| Two related datasets | §4, §15.1 | Mandatory |
| Natural-language metrics and trends | §5, §11 | Mandatory |
| SQL generation and execution | §6, §11 | Mandatory |
| Query/analysis steps shown | §9, §11 | Mandatory |
| Charts or tables | §10, §11 | Mandatory |
| Dataset/filter/time-window citations | §9, §15.1 | Mandatory |
| Facts vs hypotheses vs recommendations | §8–9, §15.1 | Mandatory |
| RBAC/access restrictions | §3, §6, §8 | Stretch; read-only/scope demo required where chosen |
| Quality/missing warnings | §8 | One safe failure mandatory |
| Cohorts/drill-down | §7, §10 | Stretch |
| Timeout/cost controls/cache | §6, §13 | Basic safety mandatory; caching optional |
| Known-answer evaluation | §4, §15 | At least one mandatory |
| Confidence/uncertainty | §8–9 | Caveats mandatory; advanced uncertainty stretch |
| Missing/duplicated records | §8, §15 | One negative case may use this |
| Out-of-scope data | §6, §8, §15 | One negative case may use this |
| Conflicting sources | §4.4, §15.2 | Stretch test |
| Pure mix shift | §7, §15.2 | Strong stretch/diagnostic case |
| Ambiguous time/denominator | §4.3, §15.2 | Clarify or disclose default |
| Unsafe/expensive query | §6, §13, §15.2 | Executor must enforce baseline restrictions |

## Appendix B — Source lineage and open integration dependencies

This specification consolidates the original enterprise AI analyst challenge, the Phase 3-aware v2 agent design, and the v3 single-agent + generative UI design. It intentionally adds **explicit ambiguity handling, source-conflict resolution, optional caching policy, and a strict minimum-demo gate**.

**Open integration dependencies (not design ambiguity):** actual Phase 3 physical table/column names; status eligibility rules; timestamp basis; available bank telemetry; seed/version/benchmark values; real database access scope; whether any backend auth needs to be mocked for the demo. Resolve these at **M0** and document any assumptions before presenting benchmark results.

**Reference implementations to consult during engineering:** LangGraph (workflows/checkpoints), SQLGlot (SQL AST validation), PostgreSQL (privileges, query execution, optional row-level security), Streamlit and Plotly (charts/interactions), Microsoft Data Formulator and Wren AI (semantic UX patterns), and InsightBench (analytical evaluation patterns). Architectural choices here do not depend on adopting their complete application stacks.
