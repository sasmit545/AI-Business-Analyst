"""Versioned CSV field contract; no evaluation answers or generation logic."""
SCHEMA_VERSION = '1.0.0'
FIELDS = {
    'merchants': ('merchant_id', 'merchant_name', 'category', 'region'),
    'banks': ('bank_id', 'bank_name'),
    'payment_methods': ('payment_method', 'label', 'role'),
    'failure_reasons': ('failure_reason', 'label', 'category'),
    'orders': ('order_id', 'merchant_id', 'created_at', 'amount_paise', 'currency'),
    'payments': ('attempt_id', 'attempted_at', 'merchant_id', 'payer_bank_id',
                 'payment_method', 'amount_paise', 'currency', 'status', 'failure_reason',
                 'order_id', 'attempt_number', 'completed_at', 'processing_duration_ms', 'ingested_at'),
    'settlements': ('settlement_id', 'attempt_id', 'due_at', 'settled_at',
                    'settlement_status', 'gross_amount_paise'),
    'bank_health': ('bank_id', 'payment_method', 'observed_at', 'availability_pct', 'p95_latency_ms'),
}


def data_dir(root):
    return root / 'data/synthetic/phase3/lifecycle_v1'
