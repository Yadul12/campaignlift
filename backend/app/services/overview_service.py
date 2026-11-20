"""Executive Overview & Global Filter Metadata Services."""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import fetch_all, fetch_one
from app.schemas.analytics import GlobalFilterParams
from app.services.filters import build_summary_where


def get_filter_options() -> dict[str, Any]:
    date_bounds = fetch_one(
        "SELECT MIN(start_date) AS min_date, MAX(end_date) AS max_date FROM campaigns"
    ) or {}
    channels = fetch_all(
        "SELECT channel_id, channel_code, channel_name, cost_model FROM campaign_channels ORDER BY channel_name"
    )
    segments = fetch_all(
        "SELECT segment_id, segment_code, segment_name, target_margin_tier, incentive_affinity FROM customer_segments ORDER BY segment_id"
    )
    routes = fetch_all(
        "SELECT route_market_id, market_code, market_region, haul_type, avg_base_fare::FLOAT8 AS avg_base_fare, load_factor_baseline::FLOAT8 AS load_factor_baseline FROM route_markets ORDER BY market_region, market_code"
    )
    campaigns = fetch_all(
        """
        SELECT campaign_id, campaign_code, campaign_name, campaign_type, experiment_type, start_date, end_date
        FROM campaigns
        ORDER BY start_date DESC, campaign_id DESC
        """
    )
    campaign_types = sorted({c["campaign_type"] for c in campaigns})
    meta_rows = fetch_all("SELECT meta_key, meta_value FROM dataset_metadata")
    meta = {r["meta_key"]: r["meta_value"] for r in meta_rows}

    return {
        "dataset_label": settings.dataset_label,
        "metadata": meta,
        "date_bounds": {
            "min_date": str(date_bounds.get("min_date")) if date_bounds.get("min_date") else "2024-01-01",
            "max_date": str(date_bounds.get("max_date")) if date_bounds.get("max_date") else "2026-09-30",
        },
        "channels": channels,
        "segments": segments,
        "routes": routes,
        "campaigns": [
            {**c, "start_date": str(c["start_date"]), "end_date": str(c["end_date"])}
            for c in campaigns
        ],
        "campaign_types": campaign_types,
        "experiment_types": ["RCT", "Observational"],
    }


def get_executive_overview(filters: GlobalFilterParams) -> dict[str, Any]:
    where_sql, params = build_summary_where(filters, alias="v")

    # 1. Core KPI Rollup separating All Portfolio vs. Causal RCT Portfolio
    kpi_row = fetch_one(
        f"""
        SELECT
            COUNT(*) AS total_campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT') AS rct_campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'Observational') AS obs_campaigns,
            COALESCE(SUM(v.marketing_spend), 0)::FLOAT8 AS total_spend,
            COALESCE(SUM(v.marketing_spend) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_spend,
            COALESCE(SUM(v.customers_targeted), 0)::BIGINT AS customers_targeted,
            COALESCE(SUM(v.customers_reached), 0)::BIGINT AS customers_reached,
            COALESCE(SUM(v.customers_engaged), 0)::BIGINT AS customers_engaged,
            COALESCE(SUM(v.attributed_bookings), 0)::BIGINT AS attributed_bookings,
            COALESCE(SUM(v.attributed_bookers), 0)::BIGINT AS attributed_bookers,
            COALESCE(SUM(v.gross_booking_revenue), 0)::FLOAT8 AS gross_booking_revenue,
            COALESCE(SUM(v.discount_cost), 0)::FLOAT8 AS discount_cost,
            COALESCE(SUM(v.loyalty_reward_cost), 0)::FLOAT8 AS loyalty_reward_cost,
            COALESCE(SUM(v.variable_cost), 0)::FLOAT8 AS variable_cost,
            COALESCE(SUM(v.contribution_before_promo), 0)::FLOAT8 AS contribution_before_promo,
            COALESCE(SUM(v.contribution_after_promo), 0)::FLOAT8 AS contribution_after_promo,
            -- Strictly causal RCT incremental sums (NEVER mixes observational attribution!)
            COALESCE(SUM(v.incremental_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_bookings,
            COALESCE(SUM(v.incremental_revenue) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_revenue,
            COALESCE(SUM(v.incremental_contribution) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_contribution,
            COALESCE(SUM(v.attributed_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::BIGINT AS rct_attributed_bookings,
            COALESCE(SUM(v.contribution_after_promo) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_attributed_contribution,
            COALESCE(SUM(v.gross_booking_revenue) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_gross_revenue,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT' AND v.is_statistically_significant = TRUE) AS rct_significant_count,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT' AND v.incremental_contribution > 0) AS rct_value_creating_count,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT' AND v.incremental_contribution < 0) AS rct_value_destroying_count
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        """,
        params,
    ) or {}

    targeted = int(kpi_row.get("customers_targeted") or 0)
    reached = int(kpi_row.get("customers_reached") or 0)
    bookers = int(kpi_row.get("attributed_bookers") or 0)
    attr_bookings = int(kpi_row.get("attributed_bookings") or 0)
    rct_inc_bookings = float(kpi_row.get("rct_incremental_bookings") or 0.0)
    rct_spend = float(kpi_row.get("rct_spend") or 0.0)
    rct_inc_contrib = float(kpi_row.get("rct_incremental_contribution") or 0.0)
    contrib_before = float(kpi_row.get("contribution_before_promo") or 0.0)
    disc_cost = float(kpi_row.get("discount_cost") or 0.0)
    miles_cost = float(kpi_row.get("loyalty_reward_cost") or 0.0)

    kpis = {
        "total_campaigns": int(kpi_row.get("total_campaigns") or 0),
        "rct_campaigns": int(kpi_row.get("rct_campaigns") or 0),
        "obs_campaigns": int(kpi_row.get("obs_campaigns") or 0),
        "total_spend": round(float(kpi_row.get("total_spend") or 0.0), 2),
        "rct_spend": round(rct_spend, 2),
        "customers_targeted": targeted,
        "customers_reached": reached,
        "reach_rate": round(reached / targeted, 4) if targeted > 0 else 0.0,
        "campaign_conversion_rate": round(bookers / reached, 4) if reached > 0 else 0.0,
        "booking_conversion_rate": round(bookers / targeted, 4) if targeted > 0 else 0.0,
        "total_attributed_bookings": attr_bookings,
        "gross_booking_revenue": round(float(kpi_row.get("gross_booking_revenue") or 0.0), 2),
        "discount_cost": round(disc_cost, 2),
        "loyalty_reward_cost": round(miles_cost, 2),
        "contribution_margin": round(float(kpi_row.get("contribution_after_promo") or 0.0), 2),
        "margin_erosion_pct": round((disc_cost + miles_cost) / contrib_before, 4) if contrib_before > 0 else 0.0,
        "incremental_bookings": round(rct_inc_bookings, 1),
        "incremental_revenue": round(float(kpi_row.get("rct_incremental_revenue") or 0.0), 2),
        "incremental_contribution": round(rct_inc_contrib, 2),
        "cost_per_incremental_booking": round(rct_spend / rct_inc_bookings, 2) if rct_inc_bookings > 1 else None,
        "incremental_roas": round(float(kpi_row.get("rct_incremental_revenue") or 0.0) / rct_spend, 2) if rct_spend > 0 else None,
        "incremental_roi": round(rct_inc_contrib / rct_spend, 2) if rct_spend > 0 else None,
        "rct_attributed_bookings": int(kpi_row.get("rct_attributed_bookings") or 0),
        "rct_attributed_contribution": round(float(kpi_row.get("rct_attributed_contribution") or 0.0), 2),
        "attribution_overstatement_ratio": round(
            int(kpi_row.get("rct_attributed_bookings") or 0) / rct_inc_bookings, 2
        ) if rct_inc_bookings > 1 else None,
        "rct_significant_count": int(kpi_row.get("rct_significant_count") or 0),
        "rct_value_creating_count": int(kpi_row.get("rct_value_creating_count") or 0),
        "rct_value_destroying_count": int(kpi_row.get("rct_value_destroying_count") or 0),
    }

    # 2. Monthly Trend of Spend, Attributed Contribution, and Causal Incremental Contribution
    monthly_trend = fetch_all(
        f"""
        SELECT
            TO_CHAR(DATE_TRUNC('month', v.start_date), 'YYYY-MM') AS month,
            COUNT(*) AS campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT') AS rct_campaigns,
            COALESCE(SUM(v.marketing_spend), 0)::FLOAT8 AS total_spend,
            COALESCE(SUM(v.gross_booking_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(v.discount_cost + v.loyalty_reward_cost), 0)::FLOAT8 AS promo_incentive_cost,
            COALESCE(SUM(v.contribution_after_promo) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_attributed_contrib,
            COALESCE(SUM(v.incremental_contribution) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_contrib,
            COALESCE(SUM(v.incremental_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_bookings
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        GROUP BY DATE_TRUNC('month', v.start_date)
        ORDER BY month
        """,
        params,
    )

    # 3. Portfolio Efficiency Scatter (every filtered campaign for quadrant view)
    portfolio_scatter = fetch_all(
        f"""
        SELECT
            v.campaign_id,
            v.campaign_code,
            v.campaign_name,
            v.campaign_type,
            v.experiment_type,
            v.channel_name,
            v.target_segment_name,
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            v.marketing_spend::FLOAT8 AS marketing_spend,
            v.attributed_bookings,
            v.incremental_bookings::FLOAT8 AS incremental_bookings,
            v.incremental_revenue::FLOAT8 AS incremental_revenue,
            v.incremental_contribution::FLOAT8 AS incremental_contribution,
            v.cost_per_incremental_booking::FLOAT8 AS cost_per_incremental_booking,
            v.conversion_lift_abs::FLOAT8 AS conversion_lift_abs,
            v.conversion_p_value::FLOAT8 AS conversion_p_value,
            v.is_statistically_significant,
            v.recommendation_status
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        ORDER BY v.incremental_contribution DESC NULLS LAST
        """,
        params,
    )

    # 4. Channel Comparison
    by_channel = fetch_all(
        f"""
        SELECT
            v.channel_id,
            v.channel_name,
            COUNT(*) AS campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT') AS rct_campaigns,
            COALESCE(SUM(v.marketing_spend), 0)::FLOAT8 AS spend,
            COALESCE(SUM(v.marketing_spend) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_spend,
            COALESCE(SUM(v.customers_targeted), 0)::BIGINT AS targeted,
            COALESCE(SUM(v.customers_reached), 0)::BIGINT AS reached,
            COALESCE(SUM(v.attributed_bookings), 0)::BIGINT AS attributed_bookings,
            COALESCE(SUM(v.gross_booking_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(v.discount_cost + v.loyalty_reward_cost), 0)::FLOAT8 AS incentive_cost,
            COALESCE(SUM(v.incremental_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_bookings,
            COALESCE(SUM(v.incremental_revenue) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_revenue,
            COALESCE(SUM(v.incremental_contribution) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_contribution
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        GROUP BY v.channel_id, v.channel_name
        ORDER BY incremental_contribution DESC
        """,
        params,
    )
    for row in by_channel:
        inc_b = float(row["incremental_bookings"] or 0)
        row["cost_per_incremental_booking"] = round(float(row["rct_spend"]) / inc_b, 2) if inc_b > 1 else None
        row["reach_rate"] = round(row["reached"] / row["targeted"], 4) if row["targeted"] else 0.0

    # 5. Segment Comparison
    by_segment = fetch_all(
        f"""
        SELECT
            COALESCE(v.segment_id, 0) AS segment_id,
            v.target_segment_name AS segment_name,
            COUNT(*) AS campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT') AS rct_campaigns,
            COALESCE(SUM(v.marketing_spend), 0)::FLOAT8 AS spend,
            COALESCE(SUM(v.marketing_spend) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_spend,
            COALESCE(SUM(v.attributed_bookings), 0)::BIGINT AS attributed_bookings,
            COALESCE(SUM(v.discount_cost), 0)::FLOAT8 AS discount_cost,
            COALESCE(SUM(v.loyalty_reward_cost), 0)::FLOAT8 AS miles_cost,
            COALESCE(SUM(v.incremental_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_bookings,
            COALESCE(SUM(v.incremental_revenue) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_revenue,
            COALESCE(SUM(v.incremental_contribution) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS incremental_contribution
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        GROUP BY COALESCE(v.segment_id, 0), v.target_segment_name
        ORDER BY incremental_contribution DESC
        """,
        params,
    )
    for row in by_segment:
        inc_b = float(row["incremental_bookings"] or 0)
        row["cost_per_incremental_booking"] = round(float(row["rct_spend"]) / inc_b, 2) if inc_b > 1 else None

    # 6. Campaign Type Comparison (Attribution vs Causal Bridge)
    by_campaign_type = fetch_all(
        f"""
        SELECT
            v.campaign_type,
            COUNT(*) AS campaigns,
            COUNT(*) FILTER (WHERE v.experiment_type = 'RCT') AS rct_campaigns,
            COALESCE(SUM(v.marketing_spend) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_spend,
            COALESCE(SUM(v.attributed_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::BIGINT AS rct_attributed_bookings,
            COALESCE(SUM(v.incremental_bookings) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_bookings,
            COALESCE(SUM(v.contribution_after_promo) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_attributed_contrib,
            COALESCE(SUM(v.incremental_contribution) FILTER (WHERE v.experiment_type = 'RCT'), 0)::FLOAT8 AS rct_incremental_contrib,
            COALESCE(AVG(v.discount_pct), 0)::FLOAT8 AS avg_discount_pct
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        GROUP BY v.campaign_type
        ORDER BY rct_incremental_contrib DESC
        """,
        params,
    )

    # 7. Decision Queue: Top Scale & Top Pause/Redesign RCT Campaigns
    scale_queue = [c for c in portfolio_scatter if c["recommendation_status"] == "Scale Budget"][:6]
    action_risk_queue = [
        c for c in sorted(
            [x for x in portfolio_scatter if x["experiment_type"] == "RCT"],
            key=lambda x: float(x["incremental_contribution"] or 0.0),
        )
        if (c["incremental_contribution"] or 0.0) < 0
    ][:6]

    return {
        "kpis": kpis,
        "monthly_trend": monthly_trend,
        "portfolio_scatter": portfolio_scatter,
        "by_channel": by_channel,
        "by_segment": by_segment,
        "by_campaign_type": by_campaign_type,
        "decision_queue": {
            "scale_winners": scale_queue,
            "margin_dilutive": action_risk_queue,
        },
    }
