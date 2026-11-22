"""Versioned semantic presentation grammar. All labels and components are host-owned."""
from typing import Literal

from pydantic import Field

from app.contracts import Component, Dashboard, StrictModel
from app.agent.objective import Objective

__all__ = ['Block', 'Layout', 'Component', 'Dashboard']


Source = Literal['overall', 'daily', 'banks', 'methods', 'segments', 'failures',
                 'merchant_categories', 'merchants', 'transactions', 'contributions', 'daily_summary']
Measure = Literal['rate', 'attempts', 'successes', 'failed_attempts', 'numerator', 'denominator']
Section = Literal['Summary', 'Trend', 'Breakdown', 'Investigation detail']


class Block(StrictModel):
    kind: Literal['kpi', 'comparison', 'bar', 'line', 'area', 'pie', 'table', 'insight']
    source: Source
    measure: Measure | None = None
    period: Literal['baseline', 'comparison'] | None = None
    section: Section | None = None
    drilldown: bool = Field(default=False, strict=True)


class Layout(StrictModel):
    version: Literal['1']
    evidence_id: str = Field(min_length=1, max_length=64)
    blocks: list[Block] = Field(max_length=6)
    headline_measure: Measure | None = None
    fallback: bool = False
    objective: Objective | None = Field(default=None, exclude_if=lambda value: value is None)
    finding_ref: str | None = Field(default=None, pattern='^[0-9a-f]{64}$', exclude_if=lambda value: value is None)
    response: Literal['answer', 'action', 'explanation'] = Field(default='answer', exclude_if=lambda value: value == 'answer')
