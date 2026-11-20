"""Shared parameterized SQL filter builder for global dashboard filters."""
from __future__ import annotations

from typing import Any

from app.schemas.analytics import GlobalFilterParams


def build_summary_where(filters: GlobalFilterParams, alias: str = "v") -> tuple[str, dict[str, Any]]:
    """
    Build safe parameterized WHERE clause for `v_campaign_commercial_summary` (alias `v`).
    Handles date overlap, campaign, channel, experiment type, campaign type,
    segment (targeted OR active assignments in segment), and route (targeted OR attributed bookings on route).
    """
    clauses: list[str] = ["1 = 1"]
    params: dict[str, Any] = {}

    if filters.start_date is not None:
        clauses.append(f"{alias}.end_date >= %(start_date)s")
        params["start_date"] = filters.start_date
    if filters.end_date is not None:
        clauses.append(f"{alias}.start_date <= %(end_date)s")
        params["end_date"] = filters.end_date
    if filters.campaign_id is not None:
        clauses.append(f"{alias}.campaign_id = %(campaign_id)s")
        params["campaign_id"] = filters.campaign_id
    if filters.channel_id is not None:
        clauses.append(f"{alias}.channel_id = %(channel_id)s")
        params["channel_id"] = filters.channel_id
    if filters.experiment_type is not None:
        clauses.append(f"{alias}.experiment_type = %(experiment_type)s")
        params["experiment_type"] = filters.experiment_type
    if filters.campaign_type is not None:
        clauses.append(f"{alias}.campaign_type = %(campaign_type)s")
        params["campaign_type"] = filters.campaign_type
    if filters.segment_id is not None:
        clauses.append(
            f"({alias}.segment_id = %(segment_id)s OR ({alias}.segment_id IS NULL AND EXISTS ("
            f"SELECT 1 FROM campaign_assignments ca_f JOIN customers cu_f ON cu_f.customer_id = ca_f.customer_id "
            f"WHERE ca_f.campaign_id = {alias}.campaign_id AND cu_f.segment_id = %(segment_id)s)))"
        )
        params["segment_id"] = filters.segment_id
    if filters.route_market_id is not None:
        clauses.append(
            f"({alias}.route_market_id = %(route_market_id)s OR EXISTS ("
            f"SELECT 1 FROM bookings b_f WHERE b_f.attributed_campaign_id = {alias}.campaign_id "
            f"AND b_f.route_market_id = %(route_market_id)s AND b_f.booking_status <> 'cancelled'))"
        )
        params["route_market_id"] = filters.route_market_id

    return " AND ".join(clauses), params
