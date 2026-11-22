"""Shared typed boundaries. Model inputs never contain execution authority."""
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

LIFECYCLE_OBSERVATION_CUTOFF = datetime.fromisoformat('2026-11-01T00:00:00+05:30')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Window(StrictModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end:
            raise ValueError('Window end must follow its start')
        if (self.end - self.start).days > 366:
            raise ValueError('Window exceeds one year')
        return self


class Filters(StrictModel):
    payer_bank_id: str | None = Field(default=None, max_length=64)
    payment_method: str | None = Field(default=None, max_length=64)
    merchant_id: str | None = Field(default=None, max_length=64)


class ComparisonRequest(StrictModel):
    baseline: Window
    comparison: Window
    filters: Filters = Field(default_factory=Filters)

    @model_validator(mode='after')
    def disjoint(self):
        if self.baseline.end > self.comparison.start:
            raise ValueError('Comparison must follow baseline without overlap')
        return self


class Scope(StrictModel):
    subject: str = 'local-operator'
    scenario: str
    session_id: str
    investigation_id: str = Field(default_factory=lambda: uuid4().hex)
    version: int = 1


AttemptDetail = Literal['merchant_categories', 'merchants', 'transactions']


class AnalysisRequest(ComparisonRequest):
    metric: Literal['attempt_success'] = 'attempt_success'
    # Omit unused options from serialized requests to preserve historical evidence digests.
    detail: AttemptDetail | None = Field(default=None, exclude_if=lambda value: value is None)


class LifecycleRequest(ComparisonRequest):
    metric: Literal['order_conversion', 'first_attempt_success', 'retry_uptake',
                    'retry_recovery_all', 'retry_recovery_retried',
                    'settlement_count', 'settlement_amount', 'bank_health']
    observation_cutoff: AwareDatetime = LIFECYCLE_OBSERVATION_CUTOFF

    @model_validator(mode='after')
    def available_observation(self):
        if self.observation_cutoff > LIFECYCLE_OBSERVATION_CUTOFF:
            raise ValueError('Cutoff exceeds available observation horizon')
        return self


class Status(StrEnum):
    RECEIVED = 'received'
    RUNNING = 'running'
    CLARIFICATION = 'clarification_required'
    VERIFIED = 'verified'
    BLOCKED = 'blocked'
    LIMITED = 'limited'
    CANCELLED = 'cancelled'
    FAILED = 'failed'
    STALE = 'stale'


class QualityRecord(StrictModel):
    rule: str
    count: int
    status: Literal['PASS', 'WARN', 'BLOCK']
    metric: str = 'attempt_success'
    scope: str = 'entire selected payments population before window/filter selection'


class QueryRecord(StrictModel):
    name: str
    sql: str
    parameters: dict[str, Any]
    rows: list[dict[str, Any]]
    elapsed_ms: float
    sql_sha256: str


class Evidence(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    scope: Scope
    request: AnalysisRequest | LifecycleRequest
    semantic_version: str = '1.0.0'
    created_at: datetime
    snapshot: str
    observation_cutoff: str | None = None
    quality: list[QualityRecord]
    queries: list[QueryRecord]
    results: dict[str, Any]
    checksum: str = ''
    reused_from: str | None = Field(default=None, exclude_if=lambda value: value is None)


class Claim(StrictModel):
    evidence_id: str
    table: Literal['overall', 'segments', 'methods', 'banks', 'failures', 'daily']
    row: int = Field(ge=0)
    field: Literal['attempts', 'successes', 'rate', 'count', 'numerator', 'denominator']
    value: float
    unit: Literal['count', 'fraction']


class Component(StrictModel):
    kind: Literal['kpi', 'bar', 'line', 'table', 'quality', 'evidence']
    evidence_id: str
    table: Literal['overall', 'segments', 'methods', 'banks', 'failures', 'daily'] = 'overall'
    x: str | None = None
    y: Literal['attempts', 'successes', 'rate', 'count', 'numerator', 'denominator'] | None = None


class Dashboard(StrictModel):
    components: list[Component] = Field(max_length=6)
