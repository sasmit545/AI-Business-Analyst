# Enterprise AI Business Analyst

## 1. Customer Context

A payments business has transaction, merchant, bank, payment-method, and
settlement data spread across multiple datasets.

Business leaders regularly ask questions such as:

-   Why did payment success rates change?
-   Which segments contributed most to a decline?
-   What actions should the business take?

Today, analysts can spend hours locating the right data, preparing
queries, comparing segments, and explaining the results.

The goal is to build an AI-powered business analyst that can answer
these questions using supplied data and provide clear, evidence-backed
explanations.

## 2. Illustrative End-to-End User Journey

1.  **Ask a business question:** A business user submits a
    natural-language question about payment performance.
2.  **Identify relevant data:** The system identifies the datasets,
    metrics, and dimensions needed to answer the question.
3.  **Plan and validate the analysis:** It generates a SQL query or
    structured analysis plan and validates it before execution.
4.  **Execute the analysis:** It runs the query against a supplied
    database or dataset.
5.  **Analyze the results:** It segments and compares results, generates
    visualizations, and identifies plausible drivers.
6.  **Present the answer:** It returns a clear explanation with query
    evidence, caveats, and recommended next steps.

## 3. Core Requirements

-   Provide at least two related datasets, such as transactions and
    merchant or bank dimensions.
-   Support natural-language questions about business metrics and
    trends.
-   Generate and execute SQL or an equivalent form of structured
    analysis.
-   Show the query or analysis steps used to produce the answer.
-   Provide charts or tables that communicate key findings.
-   Cite the datasets, filters, and time window that support each
    conclusion.
-   Clearly distinguish between:
    -   **Observed facts:** Findings directly supported by the data.
    -   **Hypotheses:** Plausible explanations that require further
        validation.
    -   **Recommendations:** Suggested actions based on the findings.

## 4. Advanced / Stretch Requirements

The following capabilities are desirable but are not essential to the
minimum successful demonstration:

-   Implement role-based access control and query restrictions.
-   Add data-quality checks and warnings for missing or inconsistent
    data.
-   Support cohort comparisons and drill-down analysis.
-   Add query cost and timeout controls, along with caching.
-   Evaluate generated queries against a set of known-answer test
    questions.
-   Explain confidence levels and uncertainty in generated conclusions.

## 5. Failure and Exception Scenarios

The system should account for scenarios such as:

-   A dataset contains missing or duplicated records.
-   A user requests data outside their permitted access scope.
-   Two data sources disagree about the same metric.
-   A decline in success rate is caused by a change in transaction mix
    rather than a decline within individual segments.
-   A question is ambiguous about the time period or metric denominator.
-   A generated query is expensive, unsafe, or otherwise unsuitable for
    execution.

## 6. Minimum Successful Demonstration

Demonstrate the system answering a business question using supplied
data. The demonstration should include:

1.  An executed query or equivalent structured analysis.
2.  A segmented analysis of the results.
3.  Visual evidence, such as a chart or table.
4.  An explanation that connects the findings to the original question.
5.  Explicit caveats, including relevant data limitations or
    assumptions.
6.  At least one demonstrated data-quality or access-control failure.

## 7. What This Challenge Is Designed to Reveal

This challenge evaluates the ability to:

-   Apply analytical reasoning to business questions.
-   Design and work with an appropriate data model.
-   Generate safe and reliable SQL from natural language.
-   Interpret analytical results in a business context.
-   Substantiate AI-generated conclusions with traceable evidence.
-   Communicate findings, uncertainty, and recommended actions clearly.

## 8. Scope and Delivery Expectations

Build a coherent, working vertical slice. You are **not** expected to
implement every enterprise feature or production-scale infrastructure
within the 48-hour timeframe.

Clearly document:

-   Assumptions made during implementation.
-   Dependencies or integrations that are mocked.
-   Features that are intentionally out of scope.
-   Known limitations and possible future improvements.

The priority is a functional end-to-end experience that demonstrates
reliable, evidence-backed business analysis---not a broad collection of
incomplete enterprise features.
