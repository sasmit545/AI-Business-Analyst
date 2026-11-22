"""Compile registered attempt metrics. All user filter values remain bound."""
from app.context.catalog import catalog
from app.contracts import AnalysisRequest


def compile_queries(scenario: str, request: AnalysisRequest, *, adaptive=False):
    catalog(scenario)
    params = {'b_start': request.baseline.start.isoformat(), 'b_end': request.baseline.end.isoformat(),
              'c_start': request.comparison.start.isoformat(), 'c_end': request.comparison.end.isoformat()}
    timestamp = 'CAST(p.attempted_at AS TIMESTAMPTZ)'
    period = f'CASE WHEN {timestamp} >= %(b_start)s::timestamptz AND {timestamp} < %(b_end)s::timestamptz THEN 0 ELSE 1 END'
    where = f'(({timestamp} >= %(b_start)s::timestamptz AND {timestamp} < %(b_end)s::timestamptz) OR ({timestamp} >= %(c_start)s::timestamptz AND {timestamp} < %(c_end)s::timestamptz))'
    for name, value in request.filters.model_dump(exclude_none=True).items():
        where += f' AND p.{name} = %({name})s'
        params[name] = value
    source = f'FROM {scenario}.payments p JOIN {scenario}.banks b ON p.payer_bank_id = b.bank_id WHERE {where}'
    counts = "COUNT(*) AS attempts, COUNT(*) FILTER (WHERE p.status = 'SUCCESS') AS successes"
    fields = {
        'overall': [],
        'segments': ['p.payer_bank_id', 'b.bank_name', 'p.payment_method'],
        'daily': ["CAST(CAST(p.attempted_at AS TIMESTAMPTZ) AT TIME ZONE 'Asia/Kolkata' AS DATE) AS day"],
        'failures': ['p.payer_bank_id', 'b.bank_name', 'p.payment_method', 'p.failure_reason'],
    }
    if adaptive:
        fields = {'observations': [*fields['daily'], *fields['segments'], 'p.status', 'p.failure_reason']}
    queries = {}
    for name, dimensions in fields.items():
        selected = ', '.join([f'{period} AS period', *dimensions])
        aggregate = 'COUNT(*) AS count' if name == 'failures' else counts
        conditions = source + (" AND p.status = 'FAILED'" if name == 'failures' else '')
        positions = ', '.join(str(i) for i in range(1, len(dimensions)+2))
        queries[name] = f'SELECT {selected}, {aggregate} {conditions} GROUP BY {positions} ORDER BY {positions}'
    if not adaptive and request.detail in ('merchant_categories', 'merchants'):
        dim = 'm.category' if request.detail == 'merchant_categories' else 'm.merchant_id'
        queries[request.detail] = (
            f'SELECT {period} AS period, {dim}, {counts} FROM {scenario}.payments p '
            f'JOIN {scenario}.merchants m ON m.merchant_id = p.merchant_id WHERE {where} '
            'GROUP BY 1, 2 ORDER BY 1, 2'
        )
    elif not adaptive and request.detail == 'transactions':
        queries['transactions'] = (
            f'SELECT {period} AS period, p.attempt_id, p.attempted_at, p.merchant_id, '
            'p.payer_bank_id, p.payment_method, p.amount_paise, p.currency, p.status, p.failure_reason '
            f'FROM {scenario}.payments p WHERE {where} '
            f'ORDER BY {timestamp} DESC, p.attempt_id LIMIT 50'
        )
    return queries, params
