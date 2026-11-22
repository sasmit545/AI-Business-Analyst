# Phase 3: payment lifecycle

Use `lifecycle_v1` in the existing `payments_analytics` database. This is a new
population; keep the five Phase 1 and 2 schemas separate. No AI analyst is implemented.

The final eight CSVs are in `data/synthetic/phase3/lifecycle_v1/`:

| Table | Rows | Meaning |
|---|---:|---|
| orders | 198,000 | Purchase intentions |
| payments | 199,734 | Completed attempts, including retries |
| settlements | 193,948 | One full-gross obligation per successful attempt |
| bank_health | 89,280 | Five-minute observations, five banks and two methods |
| merchants | 20 | Original fictional merchant attributes |
| banks | 5 | Original fictional bank attributes |
| payment_methods | 2 | CARD and UPI |
| failure_reasons | 4 | Technical, authentication and customer failure labels |

## Generate and validate

From `E:\pinelabs` in Windows PowerShell:

```powershell
# Validate the delivered files and saved SQL answers.
python -B scripts/validate_phase3.py --check-reproducibility
python -B -m unittest discover -s scripts -p test_phase3.py -v

# Import all six isolated schemas into the existing database, then test it.
python -B scripts/postgres_analytics.py setup
python -B scripts/postgres_analytics.py test
```

Setup selects `lifecycle_v1` for the read-only role. It reuses a reachable project
server and verifies its data directory. Imports replace the 23 managed tables in
one transaction; failures roll back. Original CSVs and evaluation files are never
changed by ingestion. `start` and `status` do not reimport anything.

To reproduce Phase 3 in a separate output directory:

```powershell
python -B scripts/generate_phase3.py --output-root .local/phase3-reproduction
```

The generator reads `profiles/lifecycle_v1.json` and original merchant/bank
dimensions. It writes only Phase 3 files beneath the requested output root. Do not
regenerate the delivered release just to run the database. The validator's two
reproducibility runs use temporary directories and compare all eight CSVs plus the
generation manifest. `--write-expected` is for deliberate initial release authoring,
never for concealing a validation failure.

## Generation contract

Schema and generator version: `1.0.0`. Seed: `42`. Orders are created October 1–28,
2026, in `+05:30`; observation cutoff is November 1 at midnight in that timezone.
198,000 orders yield approximately 200,000 attempts; the generator finishes every
chain and reports the actual count instead of truncating to a target.

Traffic uses the Phase 2 weights: exact largest-remainder merchant allocations,
a shuffled global bank pool, per-merchant method pools and joint date/hour quotas.
Earlier IDs/date-hour cells break allocation ties. Amounts retain the category
lognormal distribution, bounded to 1,000–10,000,000 integer INR paise. Success and
failure probabilities are inherited baseline parameters, not exact quotas.

Each initial attempt starts one second after creation. After a failure, retry
probability is 0.30, with at most three attempts. The next attempt starts five
minutes after the previous completion. Merchant, amount, currency, payment method
and payer bank stay fixed for the order; success ends the chain. No in-flight
attempts, duplicate captures, refunds, reversals, fees or partial settlements exist.

Each named random stream is seeded by SHA-256 of
`phase3:streams:v1:<seed>:<name>`. Traffic, amounts, outcomes, retries, latency,
ingestion and bank health have separate streams; changing bank-health parameters
does not change payment rows. Reproducibility assumes the same code, configuration
and Python random implementation; there is no wall-clock metadata in manifests.

Processing duration is lognormal with median 450 ms for UPI and 700 ms for CARD,
sigma 0.35, rounded and clipped to 50–5,000 ms. Ingestion follows completion by a
uniform integer 0–2,000 ms. All timestamps retain millisecond precision.

Bank health independently samples availability uniformly from 99–100%, rounded
to three decimals, and integer p95 latency from 700–1,200 ms for UPI or
1,000–1,800 ms for CARD. These are fictional observations, not measurements derived
from payments or hidden incident labels. Every five-minute bucket from October 1
through the cutoff is present for every bank/method. Match using bank, method and
the containing five-minute interval; joining only on bank multiplies attempts.

## Metric definitions and expected results

Reference parameters select October 1 inclusive through October 29 exclusive.
All percentages are rounded to six decimal places; count and amount comparisons
are exact. Empty denominators produce null, not zero percent.

| Metric | Denominator and numerator | Result |
|---|---|---|
| Attempt success | Completed attempts whose **attempt time** lies in the selected window; successful attempts | 193,947 / 199,733 = 97.103133% |
| 24-hour order conversion | Orders **created** in the window with 24 hours of observation; success completed within 24 hours of creation | 193,948 / 198,000 = 97.953535% |
| Longer-horizon paid orders | Same mature order cohort; success completed by cutoff | 193,948 |
| Retry recovery among retried orders | Mature initially failed orders that retried; later successful orders by cutoff | 1,680 / 1,719 = 97.731239% |
| Recovery among initial failures | Mature initially failed orders; recovered by cutoff | 1,680 / 5,732 = 29.309142% |
| Settlement completion | Selected-window successful attempts due by cutoff; settled by cutoff | 193,947 / 193,947 = 100% |
| Due backlog | Due obligations not settled by cutoff | 0 attempts / 0 paise |

There are 1,734 retry attempts overall. One retry crosses into October 29 and
succeeds: it belongs to its October-created order, but lies outside the selected
attempt window. Thus there are 199,734 stored attempts and 193,948 stored successes,
one more than the windowed attempt figures. `totals` reports the full stored counts.
Never change an order's denominator to make it equal an attempt denominator.

Settlement is due exactly 24 hours after successful completion, with the full
attempt amount. Baseline settlement occurs exactly at due time if due by cutoff;
otherwise it is PENDING with blank `settled_at`. All production obligations are due
by November 1, so there are no pending production rows. Late settlement is Phase 4.

## Independent evaluation and hand fixture

`evaluation/phase3/reference.sql` computes ten result sections from loaded CSVs
using temporary in-memory SQLite. It does not import generator logic. SQL results
and the SQL/fixture fingerprints are saved in `expected_answers.json`.
`database/phase3/reference.sql` is a PostgreSQL port; live validation compares every
section with those independent answers. Loaded database rows are also compared
with complete CSV row multisets, followed by lifecycle checks.

`evaluation/phase3/hand_fixture.json` is hand-authored and evaluator-only. Three
orders produce four attempts: a failure followed by success, a separate success,
and an unrecovered failure. Its earlier October 29 noon cutoff makes one successful
payment not yet due for settlement, and one order not yet mature for conversion.
The expected figures are two mature orders, one paid order, two successful attempts,
two failed attempts, one due-and-settled obligation and one not-yet-due obligation.
The fixture includes only the needed health buckets. It is not imported into the
production schema or mixed with the main dataset. Both SQLite and PostgreSQL tests
exercise it, with PostgreSQL temporary tables rolled back after the test.

The validator checks keys, foreign keys, outcomes, timestamps, consecutive attempt
numbers, retry timing, one success per order, amount agreement, settlement coverage,
full gross amounts, due times, observation coverage and count-preserving joins.
Database constraints enforce local keys/value checks and selected relationships;
cross-row lifecycle rules are additionally checked by the independent validator.
Do not rely on database constraints alone to certify arbitrary administrative edits.

`benchmark_questions.json` supplies evaluator questions and JSON-pointer answer
locations. Keep all evaluation artifacts, plans and answer-bearing documentation
outside the future analyst's runtime. Only the data dictionary and restricted
database connection are suitable analyst inputs. The database contains no answer
tables or evaluator views. The AI role sees exactly one selected scenario (eight
tables when lifecycle is selected) and cannot modify it or query another scenario.

The dataset gate is separate from the analyst gate. No analyst application exists,
so analyst behavior remains unverified. Phase 4 can use this lifecycle contract;
it must preserve this baseline and create its own fixtures.

Connection details are in [the PostgreSQL guide](phase1-postgresql.md). Runtime and
live-test evidence is in `reports/postgres_analytics_validation.json` and
`reports/postgres_analytics_last_run.json`. Earlier source preservation is checked
against `reports/phase3_preexisting_source_snapshot.json` (27 data/evaluation files).
