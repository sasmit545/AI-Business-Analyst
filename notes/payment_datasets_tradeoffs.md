# Payment Dataset Landscape for an AI Business Analyst

## 1. Project objective

The goal is to build an AI business analyst that can answer questions
such as:

-   Why did payment success rates decline?
-   Which merchants, banks, payment methods, or regions contributed most
    to the decline?
-   Did the decline occur across all segments or was it concentrated in
    a few?
-   Which failure reasons explain the change?
-   What changed between two comparable time periods?
-   Can the system support its conclusions with SQL results, charts, and
    traceable evidence?

The ideal dataset should contain transaction-level payment attempts,
both successful and failed outcomes, timestamps, joinable merchant or
bank identifiers, multiple segments, and documented permission to use
the data.

**Important distinction:** payment authorization failures, clearing
failures, settlement exceptions, refunds, and fraud labels are different
concepts. They should not be treated as interchangeable measures of
payment failure.

------------------------------------------------------------------------

## 2. Executive summary and ranking

The ranking below considers relevance to the project, not just row
count. It also distinguishes free candidates from paid ones. The user's
preferred constraint is free access, so paid options are included for
completeness but are not recommended as the starting point.

  -----------------------------------------------------------------------------------------------------------------------
            Rank Dataset            Approx. size Access           Main strength               Main trade-off
                                 stated in prior                                              
                                        research                                              
  -------------- -------------- ---------------- ---------------- --------------------------- ---------------------------
               1 UPI Payment      270,000 merged Public           Closest to                  No verified separate
                 Failure                 records repository;      bank/merchant-category      merchant master or detailed
                 Analysis                        source licensing payment success analysis    failure reason field
                 (270K)                          needs                                        
                                                 confirmation                                 

               2 Payment Funnel 40,000 simulated Free; MIT        Explicit authorization      Single transaction table;
                 Analysis       payment attempts repository       decline reasons and payment limited dimension tables
                                                 license reported lifecycle stages            

               3 Adyen DABStep    `payments.csv` Free; CC BY 4.0  Processor-style payment     No confirmed bank master;
                                reported as 23.6 reported         data and rich dimensions    refusal reason detail needs
                                              MB                                              inspection

               4 UPI Payment       250K+ records Public           Similar UPI bank and        Full source dataset may
                 Failure                         repository;      merchant-category analysis  require separate Kaggle
                 Analysis                        original dataset                             access
                 (250K)                          access/license                               
                                                 needs                                        
                                                 confirmation                                 

               5 SETTLEMENTIQ     40,390 records Free; MIT        Strong relational structure Settlement/reconciliation
                                     across five reported         and intentional             focus, not authorization
                                           feeds                  data-quality issues         success/failure

               6 Synthetic Bank        5,000-row Public Hugging   Approved/declined/pending   Preview is small; no
                 Transactions   preview reported Face dataset;    status and merchant IDs     verified separate merchant
                 (Hugging Face)                  license needs                                dimension
                                                 verification                                 

               7 ATLYS payment    500K+ attempts Public GitHub    Payment gateway, method,    Domain-specific visa
                 gateway                reported repository;      status, and related         application context; bank
                 analytics                       license needs    application/event data      and decline reason fields
                                                 verification                                 not established

               8 SQL Shed           343,840 rows Free; CC0 1.0    Excellent relational        Posted transactions only;
                 Banking             across five reported         banking schema, Parquet,    no authorization decline
                 Transactions             tables                  and long time coverage      outcome

               9 Misata US Bank        7,627,186 Paid (\$15       Rich authorization,         Not free; synthetic;
                 & Card           records across reported)        merchant, account, card,    different from
                 Transactions          14 tables                  and decline data            merchant-acquirer gateway
                                                                                              model
  -----------------------------------------------------------------------------------------------------------------------

The ranking is provisional. Some repositories were reviewed through
their documentation and file inventories, but not every full dataset was
independently downloaded and profiled. "Publicly accessible" does not
automatically mean "openly licensed."

------------------------------------------------------------------------

## 3. Dataset-by-dataset assessment

### 3.1 UPI Payment Failure Analysis --- 270K merged records

**Repository:**
https://github.com/Abhijeet-109/UPI-Payment-Failure-Analysis

**Reported scale:** 270,000 merged transaction records, assembled from
two underlying datasets described as 250K and 20K records.

**Reported format and files:** - Merged transaction data. -
`Datasets/Kaggle/Cleaned/Datasets.zip` - NPCI aggregate-statistics
workbooks: - `NPCI-Ecosystem-Stats-Master_workbook.xlsx` -
`NPCI-Product-Stats-Master_workbook.xlsx`

**Reported fields include:** - Transaction ID - Timestamp - Status -
Amount - Sender bank - Receiver bank - Merchant category - Transaction
type - Payment mode - Device type - Sender state

**Relationships and joins:** - Bank and merchant-category attributes
appear to be embedded in the transaction-level records. - A separate
merchant master keyed by `merchant_id` has not been established. - A
normalized bank dimension has not been established.

**Time coverage:** - Timestamp field and monthly analysis are
described. - The exact minimum and maximum dates should be checked
directly in the downloaded data before benchmarking.

**Payment outcomes:** - Success and failure statuses are reported. -
Detailed, standardized failure reason codes are not established in the
documented schema.

**Access and license:** - Repository and files are publicly
discoverable. - No explicit repository data license was established in
the earlier review. - The original Kaggle dataset terms and permissions
must be checked separately before redistribution or commercial use.

**Strengths:** - Strong fit for UPI success-rate trends. - Multiple
bank, payment-mode, transaction-type, state, and merchant-category
segments. - Large enough for time-period and contribution analysis. -
Indian payment context is relevant to UPI-style business questions.

**Trade-offs / risks:** - The two source datasets may have different
schemas and missing-value patterns. - A merged dataset is not the same
as a clean relational model. - Merchant category is not a substitute for
merchant-level identity. - Failure reason analysis may be limited. -
Source licensing and provenance remain unresolved.

**Best use:** Main benchmark for success-rate trends and bank/category
contribution analysis, subject to profiling and licensing checks.

------------------------------------------------------------------------

### 3.2 Payment Funnel Analysis --- 40K simulated payments

**Repository:**
https://github.com/pratyaksh26may-code/payment-funnel-analysis-sql

**Reported scale:** 40,000 simulated payment attempts.

**Reported files:** - `funnel_data_40k.csv` - `setup_40k.sql` -
`analysis_queries.sql`

**Reported characteristics:** - Four card networks. - Twenty
merchants. - Authorization, clearing, and settlement stages. -
Authorization declines and downstream payment lifecycle failures.

**Reported decline/failure reasons include:** - Insufficient funds -
Expired card - Invalid card - Limit exceeded - Do not honor

**Relationships and joins:** - Merchant and card-network attributes are
reported in the transaction dataset. - A separate normalized merchant or
bank dimension was not established. - The documented design is primarily
a transaction-level table plus SQL setup/analysis assets.

**Time coverage:** - A payment date field is reported. - Exact start/end
dates, timestamp granularity, and coverage across comparable periods
must be checked in the CSV.

**Payment outcomes:** - Approved and declined authorization outcomes. -
Clearing and settlement failures are represented separately. - Do not
combine authorization decline rate with settlement exception rate
without defining a metric.

**Access and license:** - Public GitHub repository. - MIT license
reported for the repository. - Confirm that the license covers the data
file as well as code and documentation.

**Strengths:** - Explicit failure reason categories. - Manageable size
for rapid experimentation. - Good for explaining changes in decline
reasons. - Payment lifecycle stages make it useful for testing metric
definitions. - SQL assets can help validate expected query logic.

**Trade-offs / risks:** - Simulated rather than observed production
data. - Only twenty merchants and four networks, limiting segment
diversity. - No established bank dimension. - A single flat file is less
useful for testing complex multi-table joins. - Temporal range and data
distributions still need direct verification.

**Best use:** Free failure-reason and payment-lifecycle benchmark.

------------------------------------------------------------------------

### 3.3 Adyen DABStep

**Dataset:** https://huggingface.co/datasets/adyen/DABstep

**Reported downloadable file:** `data/context/payments.csv`\
**Reported file size:** approximately 23.6 MB.

**Reported format:** CSV, hosted on Hugging Face.

**Reported characteristics and fields:** - Payment records. - Refusal
indicator. - Merchant-related information. - Card scheme. - Issuing
country. - Acquirer country. - Device and payment interaction
information. - Date/time components such as year, day of year, hour, and
minute.

**Relationships and joins:** - Merchant and payment dimensions are
represented in the dataset context. - A separate bank master has not
been established. - Card BIN or issuing country must not be treated as a
verified bank ID/dimension. - Some identifiers are hashed or anonymized.

**Time coverage:** - The dataset documentation references 2023
analytical questions. - Exact minimum and maximum dates in the
downloadable file must be measured.

**Payment outcomes:** - Refusal indicator is documented. - The exact
mapping of refusal values and the availability of detailed refusal
reason codes should be inspected. - Refusal is useful for authorization
analysis, but verify whether all rows represent comparable payment
attempts.

**Access and license:** - Hugging Face dataset is publicly accessible. -
CC BY 4.0 was reported. - Attribution is required; check dataset card
and any upstream data terms before use.

**Strengths:** - Payment-processor-style data is highly relevant to a
gateway analyst. - Richer dimensions than many toy transaction
datasets. - Good for merchant, card scheme, geography, and device
comparisons. - Independent of the UPI examples, useful for testing
whether the analyst generalizes.

**Trade-offs / risks:** - No confirmed normalized bank dimension. -
Refusal reason detail may be limited. - Hashed identifiers reduce
interpretability. - Dataset may be designed for a specific benchmark
task rather than general payment operations. - File size and schema
should be checked before designing a full data model.

**Best use:** Independent processor-style benchmark for merchant,
scheme, geography, and device analysis.

------------------------------------------------------------------------

### 3.4 UPI Payment Failure Analysis --- 250K+

**Repository:**
https://github.com/khushboo761/UPI-Payment-Failure-Analysis

**Reported scale:** 250K+ transactions.

**Reported fields include:** - Transaction ID - Timestamp - Transaction
status - Sender bank - Receiver bank - Merchant category - Device type -
Network type - Amount - State

**Files/access:** - Repository reports a `sample_data.csv`. - The full
underlying Kaggle dataset may need to be obtained separately.

**Relationships and joins:** - Bank and merchant-category fields are
reported in the transaction data. - Separate merchant and bank dimension
tables have not been established.

**Time coverage:** - Timestamp is reported. - Exact date range and
completeness must be checked in the full data.

**Payment outcomes:** - Success/failure status is reported. - Detailed
failure reason codes are not established.

**License:** - The full original Kaggle dataset's license and access
terms need verification. - Do not assume the repository's public
availability grants rights to redistribute the original dataset.

**Strengths:** - Large UPI transaction population. - Bank and
merchant-category comparisons. - Useful alternative to the 270K UPI
candidate.

**Trade-offs / risks:** - Full data availability may depend on the
upstream Kaggle source. - Sample file may not be sufficient for the
intended benchmark. - Similar limitations to the 270K candidate: no
verified merchant master and no documented failure reasons. - Need to
check whether it overlaps with the 270K dataset or uses the same source
data.

**Best use:** Alternative UPI benchmark if the full dataset is
accessible and independently useful.

------------------------------------------------------------------------

### 3.5 SETTLEMENTIQ

**Repository:** https://github.com/vinayygoudd/SETTLEMENTIQ

**Reported scale:** 40,390 records across five operational feeds.

**Reported files and row counts:**

  File                   Reported rows
  -------------------- ---------------
  `transactions.csv`             9,955
  `merchants.csv`                   25
  `settlements.csv`             10,090
  `bank_entries.csv`            10,070
  `refunds.csv`                    250

**Relationships and joins:** - Transactions connect to merchants through
merchant IDs. - Settlement, bank-entry, and refund feeds provide
additional operational relationships. - Inspect the schema and key
constraints to determine the exact join cardinalities.

**Time coverage:** - Timestamps are present. - Exact start/end date and
whether there are at least two comparable periods need verification.

**Payment outcomes:** - The project is focused on settlement and
reconciliation. - Reconciliation statuses, unmatched bank entries, and
settlement exceptions are not equivalent to authorization
success/failure. - Do not use reconciliation status as the payment
success metric.

**Data quality:** - Intentionally includes missing timestamps, malformed
amounts, duplicates, and orphan/mismatched records, according to
repository documentation.

**Access and license:** - Public GitHub repository. - MIT license
reported.

**Strengths:** - Best documented relational structure among the free
candidates. - Separate merchant, transaction, settlement, bank-entry,
and refund feeds. - Excellent for multi-table SQL, join validation,
reconciliation, and data-quality detection. - Small enough to understand
and debug.

**Trade-offs / risks:** - Not a primary authorization success/failure
dataset. - Small merchant dimension (25 merchants). - Reconciliation
exceptions should not be misrepresented as declined payments. - Exact
time coverage and key integrity need direct profiling.

**Best use:** Relational SQL and data-quality benchmark, kept separate
from authorization-performance benchmarks.

------------------------------------------------------------------------

### 3.6 Synthetic Bank Transactions --- Hugging Face

**Dataset:**
https://huggingface.co/datasets/Abdulmajeedyahya/1M-Fraud-Labeled-Synthetic-Bank-Transactions

**Reported available preview:** 5,000 rows.

**Reported fields include:** - Transaction ID - Timestamp - Merchant
ID - Merchant name - Transaction status (`APPROVED`, `DECLINED`,
`PENDING`) - Payment rail - Merchant sector - Amount - Currency -
Fraud-related fields

**Relationships and joins:** - Merchant IDs and merchant names are
present in the transaction records. - A separate merchant master has not
been established. - Bank dimensions and join keys are not established.

**Time coverage:** - Timestamp field is reported. - Exact date range and
temporal distribution need inspection.

**Payment outcomes:** - Approved, declined, and pending states are
reported. - Fraud/non-fraud is a separate label and must not be used as
a substitute for payment outcome. - Detailed decline reason codes are
not established.

**Access and license:** - Public Hugging Face dataset page. - License
should be verified on the dataset card before use. - A 5K preview does
not prove that the full 1M records are downloadable under acceptable
terms.

**Strengths:** - Has explicit payment statuses. - Merchant identifiers
and payment rail can support basic segmentation. - Useful for
prototyping a small transaction analysis pipeline.

**Trade-offs / risks:** - Available preview is below the preferred
size. - Dataset name emphasizes fraud, which may encourage incorrect use
of fraud labels. - No established bank dimension. - Full dataset access
and license need confirmation.

**Best use:** Small prototype or supplemental status-analysis dataset,
not the primary benchmark.

------------------------------------------------------------------------

### 3.7 ATLYS --- Payment Gateway Analytics

**Repository:**
https://github.com/Rishi-gupta-data/ATLYS-Visa-Application-Analytics-Transformation-Case-study

**Reported scale:** 500K+ payment attempts.

**Reported fields include:** - `payment_id` - `application_id` -
`payment_method` - `payment_gateway` - `payment_amount` -
`payment_status` - `payment_date`

**Related data:** - Application and user-event datasets are reported. -
Application IDs can connect payment records to application context.

**Relationships and joins:** - Payment-to-application relationship is a
useful join. - Merchant and bank dimensions are not established. -
Gateway is not equivalent to issuing bank or acquiring bank.

**Time coverage:** - Payment date is reported. - Exact date range and
granularity need verification.

**Payment outcomes:** - Payment status is reported. - Detailed
bank/processor decline reasons are not established.

**Access and license:** - Public GitHub repository. - Explicit data
license and rights to use the data need verification.

**Strengths:** - Large reported transaction volume. - Multiple related
business datasets. - Gateway and payment-method analysis. - Useful for
studying payment conversion in a specific business funnel.

**Trade-offs / risks:** - Domain-specific visa application context. - No
verified bank dimension. - Failure reason detail not established. -
Application funnel outcomes may confound payment performance if metrics
are not carefully defined.

**Best use:** Supplementary payment-conversion benchmark and multi-table
business-context analysis.

------------------------------------------------------------------------

### 3.8 SQL Shed Banking Transactions

**Dataset:** https://sqlshed.com/practice-datasets/banking-transactions/

**Reported scale:** 343,840 rows across five tables.

**Reported tables:** - Branches - Merchants - Customers - Accounts -
Transactions

**Reported formats:** - Parquet - SQL schema

**Relationships and joins:** - Relational banking schema with merchant,
account, customer, and branch dimensions. - Exact foreign keys and join
cardinalities should be checked in the provided schema.

**Time coverage:** - Two years reported.

**Payment outcomes:** - Posted transactions are represented. -
Authorization attempts, declined payments, and failure reasons are not
established. - It should not be treated as a payment authorization
success/failure dataset.

**Access and license:** - Public downloads. - CC0 1.0 reported.

**Strengths:** - Strong relational model. - Good time coverage. -
Parquet and SQL schema make it useful for data engineering and join
tests. - CC0 is permissive.

**Trade-offs / risks:** - No transaction-level authorization decline
outcome. - Posted transaction presence cannot establish the denominator
of all payment attempts. - Not suitable for explaining a decline in
payment success rates.

**Best use:** SQL, schema-joining, and time-series benchmark only; not
the core payment-failure benchmark.

------------------------------------------------------------------------

### 3.9 Misata --- US Bank & Card Transactions (paid option)

**Dataset:**
https://www.misata.studio/datasets/premium/us-bank-transactions

**Reported price:** \$15. This conflicts with the free-only preference,
so it is not a recommended starting choice. It is included because it
appears to have the richest documented structure.

**Reported scale:** 7,627,186 records across 14 tables.

**Reported table examples:** - `authorizations.csv` --- reported
3,097,327 authorization attempts. - `transactions.csv` --- reported
4,096,158 posted transactions. - `merchants.csv` --- reported 163,647
merchants. - `accounts.csv` - `cards.csv` - `customers.csv`

**Reported authorization details:** - Approved and declined
authorization attempts. - Authorization timestamps. - ISO response
codes. - Categorized decline reasons. - 54,726 declined authorizations
reported.

**Relationships and joins:** - Merchant, account, card, and customer
relationships are documented. - Bank/issuer information is represented
through the banking/card model. - The earlier review reported 899 orphan
merchant references in authorizations; this should be investigated
before using the data.

**Time coverage:** - Two years reported.

**Payment outcomes:** - Authorization-level approval and decline data is
the key strength. - Posted transactions are a separate lifecycle table
and should not be used as the authorization denominator.

**Access and license:** - Paid access reported at \$15. - Confirm exact
license, permitted use, and redistribution terms before purchase.

**Strengths:** - Richest reported authorization-level outcome and
decline-reason structure. - Large merchant population. - Multiple
relational tables. - Two-year time coverage. - Excellent for issuer,
merchant, and decline-reason analysis.

**Trade-offs / risks:** - Not free. - Synthetic data. - US bank/card
model may not match UPI or a payment gateway's acquiring model. - Orphan
merchant references require data-quality handling. - Large size may add
unnecessary infrastructure overhead for an initial prototype.

**Best use:** Best upgrade candidate if a small budget becomes available
and the license permits the intended use.

------------------------------------------------------------------------

## 4. Cross-dataset trade-off matrix

  -----------------------------------------------------------------------------------------------------------------------------------------------------------
  Dataset        Outcome quality             Failure reason   Merchant         Bank/issuer       Relational joins      Time         Main role
                                             detail           segmentation     segmentation                            coverage     
  -------------- --------------------------- ---------------- ---------------- ----------------- --------------------- ------------ -------------------------
  UPI 270K       Strong reported             Not established  Category-level   Sender/receiver   Limited               Timestamp;   Main UPI benchmark
                                                                               bank                                    exact range  
                                                                                                                       to verify    

  Payment Funnel Strong reported             Strong           20 merchants     Card networks,    Limited               Date; exact  Failure-reason benchmark
  40K                                                                          not banks                               range to     
                                                                                                                       verify       

  Adyen DABStep  Refusal indicator           Needs inspection Stronger         Countries/BIN,    Context files;        2023         Processor-style benchmark
                                                              merchant         not bank master   inspect               context;     
                                                              dimensions                                               exact range  
                                                                                                                       to verify    

  UPI 250K       Strong reported             Not established  Category-level   Sender/receiver   Limited               Timestamp;   Alternative UPI benchmark
                                                                               bank                                    exact range  
                                                                                                                       to verify    

  SETTLEMENTIQ   Not authorization outcomes  Reconciliation   Merchant master  Bank-entry feed   Strong                Timestamp;   Relational/data-quality
                                             exceptions                                                                exact range  benchmark
                                                                                                                       to verify    

  HF synthetic   Approved/declined/pending   Not established  Merchant ID/name Not established   Limited               Timestamp;   Small prototype
  bank                                                                                                                 exact range  
                                                                                                                       to verify    

  ATLYS          Payment status              Not established  Not established  Gateway, not bank Payment/application   Date; exact  Funnel/context benchmark
                                                                                                                       range to     
                                                                                                                       verify       

  SQL Shed       Posted transactions         None established Merchant master  Branch/account    Strong                Two years    SQL/time-series benchmark
                                                                               context                                 reported     

  Misata         Strong authorization        Strong reported  Very strong      Issuer/bank model Strong                Two years    Rich paid benchmark
                 outcomes                                                                                              reported     
  -----------------------------------------------------------------------------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 5. Recommended evaluation strategy

Do not force all datasets into one combined table. They represent
different payment systems and lifecycle definitions. Use separate
benchmarks and make the analyst identify which metric is valid for each
source.

### Benchmark A --- UPI payment performance

**Preferred dataset:** UPI 270K.

Test: 1. Overall success rate by week. 2. Week-over-week and
month-over-month change. 3. Sender-bank and receiver-bank contribution
to the decline. 4. Merchant-category contribution. 5. Payment-mode and
transaction-type comparisons. 6. State and device segmentation. 7.
Duplicate IDs, missing timestamps, invalid amounts, and inconsistent
statuses.

### Benchmark B --- Decline reason and payment lifecycle

**Preferred dataset:** Payment Funnel 40K.

Test: 1. Authorization approval rate. 2. Decline rate by reason. 3.
Change in reason distribution between periods. 4. Merchant and
card-network contribution. 5. Separate authorization, clearing, and
settlement metrics. 6. Avoid double-counting a payment that fails at
more than one stage.

### Benchmark C --- Processor-style generalization

**Preferred dataset:** Adyen DABStep.

Test: 1. Refusal rate by merchant. 2. Refusal rate by card scheme. 3.
Issuing-country and acquirer-country comparisons. 4. Device and
payment-interaction analysis. 5. Hour-of-day and day-of-week trends. 6.
Verify refusal indicator semantics before defining success rate.

### Benchmark D --- Relational SQL and data quality

**Preferred dataset:** SETTLEMENTIQ.

Test: 1. Transaction-to-merchant joins. 2. Transaction-to-settlement
reconciliation. 3. Bank-entry matching. 4. Refund relationships. 5.
Duplicate and orphan key detection. 6. Missing and malformed data
detection. 7. Evidence lineage across joined tables.

### Optional Benchmark E --- Broad banking schema

**Preferred dataset:** SQL Shed.

Use it to test joins, schema discovery, Parquet ingestion, and
long-range time queries. Do not use it to claim that the system can
explain authorization failures.

------------------------------------------------------------------------

## 6. Data profiling checklist before adoption

Run these checks on every candidate before using it in the benchmark.

### File and schema checks

-   [ ] Confirm the complete files can be downloaded without
    authentication or payment.
-   [ ] Record file names, formats, sizes, and row counts.
-   [ ] Inspect column names, data types, nullability, and
    documentation.
-   [ ] Confirm the dataset license and upstream source terms.
-   [ ] Record whether the data is real, synthetic, anonymized, or
    simulated.

### Payment outcome checks

-   [ ] Identify the exact payment attempt denominator.
-   [ ] Enumerate all status values.
-   [ ] Separate approved, declined, pending, cancelled, reversed,
    refunded, and unknown states.
-   [ ] Confirm whether one row represents one attempt or one final
    transaction.
-   [ ] Check whether retries create multiple rows for the same logical
    payment.
-   [ ] Identify documented decline reason codes.
-   [ ] Do not use fraud labels as payment outcome labels.

### Time checks

-   [ ] Compute minimum and maximum timestamps.
-   [ ] Count transactions per day and per week.
-   [ ] Check gaps in date coverage.
-   [ ] Confirm time zone and timestamp precision.
-   [ ] Confirm at least two comparable periods.
-   [ ] Check whether one period has materially different volume or data
    collection rules.

### Segment checks

-   [ ] Count unique merchants.
-   [ ] Count unique banks, issuers, acquirers, gateways, networks, and
    payment methods separately.
-   [ ] Check whether merchant and bank IDs are stable.
-   [ ] Check segment cardinality and whether a few segments dominate
    the data.
-   [ ] Confirm whether dimension attributes are available in separate
    tables or embedded in transactions.

### Join and data-quality checks

-   [ ] Identify primary keys and foreign keys.
-   [ ] Check duplicate transaction and attempt IDs.
-   [ ] Check orphan merchant, bank, account, and settlement references.
-   [ ] Validate join cardinality.
-   [ ] Check missing IDs and timestamps.
-   [ ] Check invalid amounts and currency values.
-   [ ] Check inconsistent status or reason-code mappings.
-   [ ] Document every cleaning decision.

------------------------------------------------------------------------

## 7. Metric definitions the AI analyst should use

A common source of incorrect explanations is mixing payment lifecycle
stages. Define metrics explicitly.

### Authorization approval rate

For a defined set of authorization attempts:

`approval_rate = approved_authorizations / eligible_authorization_attempts`

The denominator should exclude only explicitly defined non-attempt
records. Do not silently remove declines.

### Authorization decline rate

`decline_rate = declined_authorizations / eligible_authorization_attempts`

State how pending, cancelled, reversed, and unknown records are handled.

### Segment contribution to a decline

For each segment, calculate: - Its approval rate in the baseline
period. - Its approval rate in the comparison period. - Its attempt
volume in both periods. - Its contribution to the overall rate change.

Do not equate the segment with the largest decline in rate to the
segment contributing most to the overall decline. Volume matters.

### Payment lifecycle rates

Keep separate measures for: - Authorization approval. - Capture/clearing
success. - Settlement completion. - Refund rate. - Reconciliation match
rate.

A settlement exception is not automatically an authorization failure.

### Evidence-backed explanations

Each generated explanation should retain: - SQL query or reproducible
calculation. - Time windows compared. - Segment and filter
definitions. - Numerator and denominator. - Baseline and comparison
rates. - Absolute and relative changes. - Supporting row counts. -
Relevant data-quality warnings.

------------------------------------------------------------------------

## 8. Final recommendation

For a free-first implementation:

1.  **Start with UPI 270K** as the main business-performance dataset,
    after confirming the upstream license and profiling the CSV.
2.  **Use Payment Funnel 40K** as the explicit decline-reason and
    payment-lifecycle benchmark.
3.  **Add Adyen DABStep** as an independent processor-style benchmark,
    after validating the refusal semantics and date coverage.
4.  **Use SETTLEMENTIQ** separately for multi-table joins and
    data-quality reasoning.
5.  Keep SQL Shed, the 250K UPI candidate, the Hugging Face synthetic
    bank data, and ATLYS as supplementary candidates.
6.  Treat Misata as a paid fallback, not part of the free-first plan.

**No single free candidate has yet been verified to satisfy every
requirement simultaneously.** In particular, a fully documented free
dataset combining transaction-level authorization attempts, detailed
decline reasons, a separate merchant dimension, a separate bank/issuer
dimension, and several weeks or months of coverage remains the ideal
target.

The strongest project design is therefore a small suite of complementary
benchmarks rather than one artificially merged dataset.

------------------------------------------------------------------------

## 9. Source links

1.  UPI Payment Failure Analysis (270K):
    https://github.com/Abhijeet-109/UPI-Payment-Failure-Analysis
2.  Payment Funnel Analysis (40K):
    https://github.com/pratyaksh26may-code/payment-funnel-analysis-sql
3.  Adyen DABStep: https://huggingface.co/datasets/adyen/DABstep
4.  Adyen payments CSV:
    https://huggingface.co/datasets/adyen/DABstep/resolve/main/data/context/payments.csv
5.  UPI Payment Failure Analysis (250K):
    https://github.com/khushboo761/UPI-Payment-Failure-Analysis
6.  SETTLEMENTIQ: https://github.com/vinayygoudd/SETTLEMENTIQ
7.  Synthetic Bank Transactions:
    https://huggingface.co/datasets/Abdulmajeedyahya/1M-Fraud-Labeled-Synthetic-Bank-Transactions
8.  ATLYS payment analytics:
    https://github.com/Rishi-gupta-data/ATLYS-Visa-Application-Analytics-Transformation-Case-study
9.  SQL Shed Banking Transactions:
    https://sqlshed.com/practice-datasets/banking-transactions/
10. Misata US Bank & Card Transactions (paid):
    https://www.misata.studio/datasets/premium/us-bank-transactions
