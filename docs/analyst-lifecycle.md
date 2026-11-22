# Lifecycle analysis

Lifecycle metrics use the administratively selected `lifecycle_v1` schema in the existing PostgreSQL database. Other selected schemas continue to expose attempt success only. The model cannot switch schemas.

**Verified November 22, 2026:** all eight metrics passed real NVIDIA/API/PostgreSQL evaluation against independent period and bank/method truths. All six original scenarios and four policy cases also passed. Five real browser journeys and 92 scoped application tests passed; two opt-in tests were skipped in the default suite and live checks ran separately. See [U8 / G2 acceptance](../reports/analyst/lifecycle_acceptance.json). Original fixtures and answers are unchanged.

| Metric | Numerator | Denominator | Window applies to |
|---|---|---|---|
| Order conversion | Orders paid within 24 hours of creation | Orders with at least 24 hours of observation | Order creation |
| First-attempt success | Mature orders whose first attempt succeeded | Mature orders | Order creation |
| Retry uptake | Initially failed mature orders with a retry | Initially failed mature orders | Order creation |
| Recovery among initial failures | Initially failed mature orders recovered by cutoff | Initially failed mature orders | Order creation |
| Recovery among retried orders | Initially failed mature orders recovered by cutoff | Retried initially failed mature orders | Order creation |
| Settlement count completion | Due obligations settled by cutoff | Obligations due by cutoff | Successful attempt start |
| Settlement amount completion | Gross paise settled for due obligations by cutoff | Gross paise due by cutoff | Successful attempt start |
| Attempt success with aligned health | Successful observed attempts | Observed completed attempts | Attempt start |

The default observation cutoff is November 1, 2026 at midnight in Asia/Kolkata, the available dataset horizon. An earlier explicit cutoff is supported. A later cutoff is rejected. Payment outcomes must be completed and ingested by cutoff. Retry recovery uses outcomes observed by cutoff; order conversion additionally requires success within 24 hours of creation. An order's successful retry can therefore count toward conversion even when its attempt falls outside the order-creation window.

Order outcomes are reduced to one row per order before metric aggregation. Quality checks establish one initial attempt per order, a consistent bank/method within each chain, and valid references and timestamps. Bank/method order filters use the observed initial attempt. Settlements have their own quality dependencies; invalid settlement data does not block order conversion. Not-yet-due obligations are shown separately from due backlog. Amounts use integer INR paise.

Health observations match on bank, method and the containing half-open five-minute interval. Missing, invalid or ambiguous observations are counted and excluded from telemetry summaries, while payment attempts remain in the attempt-success denominator. Availability and bucket p95 latency summaries are weighted by matched attempts. The average of bucket p95 observations is not a population p95. This schema has no telemetry ingestion timestamp, so it cannot establish telemetry arrival delays. Correlation does not establish a cause.

Example question:

> Compare 24-hour order conversion for 2026-10-01 inclusive to 2026-10-15 exclusive versus 2026-10-15 inclusive to 2026-10-29 exclusive in Asia/Kolkata. Use observation cutoff 2026-11-01T00:00:00+05:30.

Replace the metric with a precise name from the table. For retry recovery, specify which denominator. For settlement completion, specify count or amount. Each investigation executes one metric bundle, then publishes checked results, a chart/table and the SQL. Separate questions create separate investigations.

The existing 120-second investigation, 10-second SQL statement, 12-statement, 10-tool and token limits remain in place. Timestamp checks are split into bounded statements. All quality checks and analytical queries still share one read-only repeatable-read transaction. PostgreSQL fixtures and privileges are not broadened.

One settlement browser run reached the quality-query timeout and published no evidence; its isolated rerun passed without changing runtime code or increasing limits. The failed run remains recorded in the acceptance report. These checks do not certify performance under load.

## Reproduce verification

Stop active analyst sessions before evaluation. From `E:\pinelabs`:

```powershell
.\.local\analyst\venv\Scripts\python.exe scripts/evaluate_lifecycle.py
.\.local\analyst\venv\Scripts\python.exe scripts/evaluate_lifecycle.py --live-model
```

The evaluator independently calculates period and bank/method results from original CSVs and reconciles totals with the original Phase 3 SQL answers. It restores `lifecycle_v1` and checks protected hashes in `finally`. Hand tests use transaction-local temporary PostgreSQL tables; they never import hand cases into business schemas.

For a real browser check, leave ports 8000/8501 available:

```powershell
$env:ANALYST_BROWSER_TEST='1'
$env:ANALYST_BROWSER_REAL_MODEL='1'
$env:ANALYST_BROWSER_METRIC='order_conversion'
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst/test_ui_journey.py -q
Remove-Item Env:ANALYST_BROWSER_METRIC
```

Other browser metric selectors include `retry_recovery_retried`, `settlement_amount` and `bank_health`. For startup, saved-session recovery and chart drill-down, see [the application guide](analyst-usage.md).
