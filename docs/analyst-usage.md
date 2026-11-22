# Local payment analyst

Ask for the decision you want to make. For example, “Which recorded failure reason accounted for the most failures in the comparison period?” ranks counts and shows the share of failed attempts. “Which failure reason worsened most per completed attempt?” compares rates across periods. “Which bank and payment method contributed most to the change in success?” uses the contribution to overall movement. Supply dates and timezone for a new comparison.

Open **Measured findings and interpretation** to see the evidence behind the priority and what to check first. For order, retry and settlement questions, the proposed check uses the selected stage, denominator, unit and cutoff. Health recommendations describe telemetry coverage and which operational observations could help test a hypothesis. An ordinary period-level failure breakdown cannot identify the day on which those failures occurred.

Use **Ask follow-up** and enter “What steps should I take to address this?” to get actions for the saved finding. The follow-up can reuse its parent's snapshot with zero additional analytical SQL statements. A new filter or breakdown can require a fresh measurement. **SQL, quality and provenance** shows the resolved objective, table scope, time field, metric grain, SQL and bound parameters.

On the result screen, read your saved question and the answer underneath it. **Baseline** and **Comparison** refer to the two displayed date ranges. A daily trend can show a line chart, a bank comparison can show failure counts by bank, and a factual question can have just a text answer. When a chart appears, **Show chart data as tables** reveals the rows behind it.

Daily trend lines fit their vertical scale to the observed values across both periods so small changes are visible. Switch off **Fit y-axis to observed values** to see the scale from zero. Bar and area charts start at zero and offer the same control when the values vary.

Use **Ask follow-up** to continue that result. Open **Filters, dates and comparisons** to change the analysis with a form. **New question** in the sidebar starts another question in the same session. **Chat history** lets you reopen an earlier answer. For metric definitions, exact timestamps, quality checks and executed queries, open **SQL, quality and provenance**. [Generative UI guide](analyst-generative-ui.md)

You can use a bank name such as **Bank D** or **Fictional Bank D** in a question. On opening a database session the analyst reads bank IDs and names from the selected schema’s `banks` table using its restricted connection. An exact stored ID takes precedence. Names and IDs can also match on case, spaces, hyphens and underscores. A missing or ambiguous match prompts for clarification. A known bank with no matching payments has a zero denominator and an unavailable rate. If an older result used a label where SQL required an ID, **Recalculate** runs a fresh comparison with the resolved ID, saved dates and payment method. Chat history keeps both results and their executed SQL.

The application implements attempt-success comparisons over one administratively selected PostgreSQL fixture. When `lifecycle_v1` is selected, it also offers order conversion, first-attempt success, retry uptake/recovery, settlement count/amount completion and aligned bank health. See [lifecycle definitions and verification](analyst-lifecycle.md). It uses FastAPI, LangGraph, Streamlit/Plotly and a restricted Psycopg connection. NVIDIA Nemotron is the configured model: `nvidia/nemotron-3.5-super-vl-120b-a12b`.

**Lifecycle breadth (U8 / G2) passed on November 22, 2026.** Eight lifecycle/health metrics, all six original scenarios and four policy cases passed with real NVIDIA/API/PostgreSQL execution. Five browser journeys passed: conversion, retry recovery, settlement amount, health and dirty-data blocking. Each successful metric journey checks desktop/mobile rendering, exact chart values, SQL provenance and clarification clearing prior results. The scoped application suite passed 92 tests with two opt-in skips; live checks ran separately. All 43 protected files remain unchanged. See [current acceptance](../reports/analyst/lifecycle_acceptance.json) and [implementation status](../reports/analyst/implementation_status.json).

The first demo (U1-U7 / G1) passed on November 21, 2026; its [original acceptance report](../reports/analyst/final_acceptance.json) is preserved. During the lifecycle browser checks, one settlement quality query exceeded the existing 10-second timeout and safely failed without publishing evidence. An isolated rerun passed with unchanged runtime code and limits. Performance under load remains unverified.

Earlier networking and model-tool failures are preserved in the diagnosis reports. Network access now works in the agent session. Current acceptance links a single runtime snapshot to the successful model and browser runs; it does not rely on the earlier model-double evidence.

## Start from PowerShell

The local target-v1 verification covers saved-session recovery, replay of completed SQL, reauthorized chart selections, adaptive segment testing and comparisons between metric definitions. See the [acceptance report](../reports/analyst/durable_acceptance.json) for the live results and the limits observed during testing.

Run from `E:\pinelabs`. The isolated environment is `.local/analyst/venv`. To recreate dependencies:

```powershell
python -m venv .local/analyst/venv
.\.local\analyst\venv\Scripts\python.exe -m pip install -r requirements-analyst.lock
```

Set `NVIDIA_API_KEY=` in the root `.env` file. The host service reads this file automatically; environment variables take precedence. Do not paste the key into the UI. The selected endpoint is `https://integrate.api.nvidia.com/v1`. The operator confirmed free NVIDIA credits. `ANALYST_MAX_TOKENS=32768` and `ANALYST_FREE_CREDITS=true` are optional `.env` settings. Paid usage fails closed until a pricing/spend policy is implemented. [NVIDIA model documentation](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-super-vl-120b-a12b).

Check or start the existing native database without reimporting:

```powershell
python -B scripts/postgres_analytics.py status
# Only when it is stopped:
python -B scripts/postgres_analytics.py start
```

Start the API and UI together in one PowerShell terminal:

```powershell
.\start-analyst.ps1
```

Open **http://127.0.0.1:8501**, click **Start new session**, and ask, for example:

> Compare attempt success for October 1–14 and October 15–28, 2026 in Asia/Kolkata. Which bank and method segments contributed?

The API listens on `127.0.0.1:8000`. Both services must remain bound to loopback. The UI server reads the private API and workspace credentials from `.local/analyst/` each time it makes a request. Only the workspace credential can list or reopen the local operator’s sessions through the picker.

Press Q or Ctrl+C in the launcher's terminal to stop both services. PostgreSQL can remain running. `python -B scripts/postgres_analytics.py stop` shuts down the dedicated native cluster if desired.

When installing or upgrading the app, install the locked dependencies and initialize its private tables once, with the database running and before launching the app:

```powershell
.\.local\analyst\venv\Scripts\python.exe -m pip install -r requirements-analyst.lock
.\.local\analyst\venv\Scripts\python.exe scripts/setup_analyst_metadata.py
```

The setup can be rerun. It installs the PostgreSQL checkpoint saver in `analyst_meta` and stores the writer credential under `.local/analyst/`. The fixture reader and metadata writer use separate roles in `payments_analytics`.

## What answers mean

Each result names the selected dataset, filters and comparison windows. **Measured findings and interpretation** separates the observed facts, confidence in the comparison and recommended follow-up. For count-based rates, it shows how much one outcome would move each rate with the denominator held fixed. Settlement amount uses gross paise as its weight. An empty denominator makes a rate comparison unavailable. Quality warnings appear alongside the result, including gaps in bank-health coverage.

Open **Chat history** in the sidebar to read the current session’s questions and answer headlines in the order the questions were asked. Clarification exchanges appear with their question, and follow-ups identify their parent. Choose **Open investigation** to revisit a chart, inspect the SQL or continue a result. To switch conversations, select **Saved sessions** in the sidebar. Sessions saved before chat history was added show their original questions and saved answers.

The authenticated `GET /sessions/{session_id}/history` endpoint returns the same public conversation. Viewing an entry uses its saved evidence and consumes no analysis budget.

- Success rate is successful completed attempts divided by all completed attempts within the explicit half-open timestamp window and filters. It is not order conversion or settlement completion.
- Quality runs on raw text across the selected population before filtering, casting or joining. Missing or malformed timestamps, duplicate IDs, invalid values and broken references block certification. The app never repairs the fixtures.
- Overall, bank/method, daily and failure-label results share one read-only repeatable-read snapshot. Symmetric decomposition separates traffic mix from within-segment rate changes; appearing/disappearing segments make decomposition unavailable.
- Numerical prose comes from checked result cells and deterministic derivations. Provider prose and reasoning streams cannot become factual UI output. Recorded failure labels are observations, not causal proof.
- Expand **SQL, quality and provenance** to inspect SQL, bound values, quality counts, snapshot identity and checksums. Bar/table changes reuse existing evidence; authorization is still checked while results are displayed.
- Relative or missing comparison windows require clarification. Clarification replies carry their investigation version. Cancellation immediately removes published output; an in-flight SQL operation can take up to its 10-second statement timeout to stop, and a provider read has a bounded timeout.

The investigation budget is 120 seconds, 10 model tools, 2 structured-output repairs, 32,768 input/output tokens and at most 4,096 output tokens per model call. Before each call, the adapter reserves a conservative input/output allowance. A normally completed stream with a valid final provider usage receipt replaces that call's reservation with reported usage; missing or invalid receipts and interrupted streams retain the full reservation. The `tokens_reserved` diagnostic therefore includes settled usage plus unconfirmed reservations. No automatic SDK retries occur. Clarification waiting time counts toward the deadline. Each bundle meters up to 12 SQL statements including quality and transaction setup; authorization round trips and rollback cleanup are separate control operations. Result limits are 2,000 rows, 1 MiB per artifact and six dashboard components.

If an investigation reaches a limit, its error identifies the token, time, tool, SQL or result-size limit. A previous live evaluation exhausted token reservations after two invalid tool calls and successful SQL; this was not a 120-second timeout. The adapter now requests final streamed usage using NVIDIA's documented `stream_options` support. The accounting fix has regression coverage and passed the final six-scenario live run.

After an analytical bundle completes, the model is offered only evidence inspection and publication tools. A second analysis remains prohibited by the dispatcher. The evaluator accepts `blocked` as an expected result only for the dirty fixture with published quality evidence; a policy block without publication fails with its original error. The live report records the last investigation's ID, status, error and budget for diagnosis.

The host supplies the curated selected-schema catalog in the initial system context, after authorization. The model no longer needs to call a zero-argument metadata tool before analysis. This removes a repeated `get_context` argument-validation loop seen in live evaluation; arbitrary or extra tool arguments remain rejected. The final same-version live run passed all six scenarios. The real-model dirty browser journey displayed all three defects and published diagnostic evidence only.

For questions containing two explicit ISO date ranges in the form `2026-10-01 inclusive to 2026-10-15 exclusive` and a named timezone such as `Asia/Kolkata`, the host binds the exact midnight boundaries in the tool schema and rejects mismatches before SQL. This prevents the observed model error that added 24 minutes to an end date. Other phrasing remains model-interpreted; inspect the displayed windows. Incomplete or ambiguous requests require clarification.

## Scenario administration and restart

Only the operator can change the selected schema:

```powershell
python -B scripts/postgres_analytics.py select --scenario scenario_b
# Restore the default after evaluation:
python -B scripts/postgres_analytics.py select --scenario lifecycle_v1
```

The app saves each session in local PostgreSQL as you work. Browsers that open this single-operator app share the same workspace. Click a conversation in the **Saved sessions** list on the home screen to reopen it. The list shows conversations for the current dataset version, most recent first. Each entry shows its first question and the date of its latest question. Sessions with no questions appear as **Empty session**.

Reopening restores the most recent investigation. **Chat history** opens earlier questions, answers and charts. The API checks ownership, dataset selection and import version. Opening the same UI session in another tab transfers control to that tab. Work interrupted by a service restart resumes with its original deadline and spending limits. Deleting a session through the API revokes access and removes it from the picker.

Every administrative selection, including reselecting the same scenario, advances the selection generation. An import advances a separate fixture version. After either operation, start a new investigation under the current data. Sessions created by the earlier in-memory demo have no resume key. Its evidence files remain available locally for historical inspection.

Select a bank bar or use the follow-up control to narrow a verified result. Both interactions run a fresh query with the parent metric, periods, cutoff and existing filters. For attempt success, **Test the largest segment change** checks the observed direction of the largest segment change in a second query. It shares the original investigation budget, can run once and returns a limited result if the remaining allowance is insufficient. Compare two verified results from the same saved session to inspect differences in their definitions, windows, filters, counts and provenance.

This is a single-operator local application, not production authentication or an OS sandbox against the Windows account owner. There is no host-shell, filesystem, administrator or arbitrary-SQL tool available to the analyst model.

## Verification

Run only the scoped application tests, never broad discovery:

```powershell
.\.local\analyst\venv\Scripts\python.exe -B scripts/audit_analyst_schema.py
.\.local\analyst\venv\Scripts\python.exe -B scripts/evaluate_analyst.py
New-Item -ItemType Directory -Force .local/analyst/test-temp | Out-Null
$analystTestTemp = Join-Path (Resolve-Path .local/analyst/test-temp) ([guid]::NewGuid().ToString('N'))
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst -q -p no:cacheprovider --basetemp $analystTestTemp
```

The fresh workspace-local pytest directory avoids permissions left by a previous Windows session in the system temporary directory.

The evaluator changes scenarios sequentially through administrative tooling, uses fresh restricted clients, compares to original saved answers, checks permissions, and restores `lifecycle_v1` in `finally`. It does not import or regenerate fixtures. Stop active analyst sessions before running it.

For real provider checks from a PowerShell environment with NVIDIA network access:

```powershell
$env:ANALYST_LIVE_MODEL='1'
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst/test_live_model.py -q
.\.local\analyst\venv\Scripts\python.exe -B scripts/evaluate_analyst.py --live-model
```

For browser proof, stop application processes using ports 8000/8501 first. The test starts and stops its own services and uses the installed Chrome executable:

The test rejects occupied ports before opening a browser. It checks that an ambiguous follow-up displays clarification and removes the previous metrics, chart and evidence. These assertions passed with the real model, along with desktop/mobile rendering and actual chart values.

```powershell
# Real browser/API/database with a labeled deterministic model double:
$env:ANALYST_BROWSER_TEST='1'
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst/test_ui_journey.py -q

# Real provider as well; requires NVIDIA connectivity:
$env:ANALYST_BROWSER_REAL_MODEL='1'
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst/test_ui_journey.py -q
```

To reproduce the dirty browser check, administratively select `scenario_a_dirty`, set `ANALYST_BROWSER_SCENARIO=scenario_a_dirty`, and run the same browser test with both browser opt-in variables set. Restore `lifecycle_v1` and remove `ANALYST_BROWSER_SCENARIO` afterward, including on failure. The dirty check requires exactly 20 duplicate occurrences, 10 missing timestamps and 10 orphan merchants, with no certified metrics or chart.

Successful live checks write new evidence. The final acceptance report combines the full scenario run, browser evidence, source hashes and manual inspection. A later rerun must be reviewed on its own results; the evaluator deliberately leaves its aggregate demo gate pending until the corresponding browser and review evidence is assembled.

For saved-session and interaction checks, keep `lifecycle_v1` selected and run the following commands sequentially. The browser test uses temporary service ports. The administrative test exercises invalidation on a disposable native PostgreSQL cluster.

```powershell
.\.local\analyst\venv\Scripts\python.exe scripts/evaluate_durable.py
.\.local\analyst\venv\Scripts\python.exe scripts/evaluate_analyst_fences.py
$env:ANALYST_DURABLE_BROWSER='1'
.\.local\analyst\venv\Scripts\python.exe -m pytest tests/analyst/test_durable_browser.py -q
Remove-Item Env:ANALYST_DURABLE_BROWSER
```

To check how recommendations change with the question and with the data, run the journey evaluator below. It creates a disposable native PostgreSQL cluster, imports the fixtures there, checks failure rankings on two permutations, exercises all eight lifecycle metrics and follows up through the API. The report records the executed SQL, parameters, verified finding, recommended action and follow-up cost. With `--live-model`, a separate receipt records the hosted provider outcome. Use a fresh report filename for each run.

```powershell
.\.local\analyst\venv\Scripts\python.exe -B scripts/evaluate_payment_journey.py --report reports/analyst/journey_local_run.json --live-model
```
