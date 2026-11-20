from __future__ import annotations

from datetime import date
from typing import Any
from pydantic import BaseModel, Field, field_validator


class GlobalFilterParams(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    campaign_id: int | None = None
    channel_id: int | None = None
    segment_id: int | None = None
    route_market_id: int | None = None
    experiment_type: str | None = Field(default=None, pattern="^(RCT|Observational)$")
    campaign_type: str | None = None

    @field_validator("end_date")
    @classmethod
    def check_date_order(cls, v: date | None, info) -> date | None:
        start = info.data.get("start_date")
        if v is not None and start is not None and v < start:
            raise ValueError("end_date must be greater than or equal to start_date")
        return v


class SampleSizeRequest(BaseModel):
    baseline_rate: float = Field(..., gt=0.001, lt=0.95)
    mde_abs: float = Field(..., gt=0.0005, lt=0.50)
    alpha: float = Field(default=0.05, gt=0.001, lt=0.25)
    power: float = Field(default=0.80, gt=0.50, lt=0.995)
    treatment_split: float = Field(default=0.50, ge=0.10, le=0.90)


class ChannelAllocationItem(BaseModel):
    channel_id: int
    share_pct: float = Field(..., ge=0.0, le=100.0)


class BudgetSimulationRequest(BaseModel):
    base_campaign_id: int | None = None
    budget_multiplier: float = Field(default=1.0, ge=0.25, le=3.0)
    discount_pct: float = Field(default=12.0, ge=0.0, le=40.0)
    bonus_miles_offer: int = Field(default=2500, ge=0, le=25000)
    target_segment_id: int | None = None
    exclude_sure_things: bool = False
    route_market_id: int | None = None
    channel_allocations: list[ChannelAllocationItem] | None = None


class CompareCampaignsRequest(BaseModel):
    campaign_ids: list[int] = Field(..., min_length=2, max_length=6)


class APIErrorResponse(BaseModel):
    error: str
    detail: Any = None
