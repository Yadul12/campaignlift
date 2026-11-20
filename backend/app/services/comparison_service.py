"""Campaign Comparison Service: Side-by-side multi-campaign evaluation across spend, lift, economics, segment, channel & route."""
from __future__ import annotations

from typing import Any

from app.db import fetch_all


def compare_campaigns(campaign_ids: list[int]) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(campaign_ids))
    if len(unique_ids) < 2:
        return {"campaigns": [], "segment_matrix": [], "route_overlap": []}

    rows = fetch_all(
        """
        SELECT
            v.campaign_id,
            v.campaign_code,
            v.campaign_name,
            v.campaign_type,
            v.experiment_type,
            v.start_date::TEXT AS start_date,
            v.end_date::TEXT AS end_date,
            v.channel_name,
            v.target_segment_name,
            v.target_route_code,
            v.target_route_region,
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            v.marketing_spend::FLOAT8 AS marketing_spend,
            v.customers_targeted,
            v.customers_reached,
            v.customers_engaged,
            v.attributed_bookings,
            v.attributed_bookers,
            v.gross_booking_revenue::FLOAT8 AS gross_booking_revenue,
            v.discount_cost::FLOAT8 AS discount_cost,
            v.loyalty_reward_cost::FLOAT8 AS loyalty_reward_cost,
            v.contribution_before_promo::FLOAT8 AS contribution_before_promo,
            v.contribution_after_promo::FLOAT8 AS contribution_after_promo,
            v.conversion_control::FLOAT8 AS conversion_control,
            v.conversion_treatment::FLOAT8 AS conversion_treatment,
            v.conversion_lift_abs::FLOAT8 AS conversion_lift_abs,
            v.conversion_lift_rel::FLOAT8 AS conversion_lift_rel,
            v.conversion_p_value::FLOAT8 AS conversion_p_value,
            v.incremental_bookings::FLOAT8 AS incremental_bookings,
            v.incremental_revenue::FLOAT8 AS incremental_revenue,
            v.incremental_contribution::FLOAT8 AS incremental_contribution,
            v.cost_per_incremental_booking::FLOAT8 AS cost_per_incremental_booking,
            v.is_statistically_significant,
            v.recommendation_status,
            ers.conversion_ci_low::FLOAT8 AS conversion_ci_low,
            ers.conversion_ci_high::FLOAT8 AS conversion_ci_high,
            ers.exposure_compliance_rate::FLOAT8 AS exposure_compliance_rate,
            ers.max_covariate_smd::FLOAT8 AS max_covariate_smd
        FROM v_campaign_commercial_summary v
        LEFT JOIN experiment_results_store ers ON ers.campaign_id = v.campaign_id
        WHERE v.campaign_id = ANY(%s)
        ORDER BY ARRAY_POSITION(%s::INT[], v.campaign_id)
        """,
        (unique_ids, unique_ids),
    )

    for r in rows:
        targeted = int(r["customers_targeted"] or 0)
        reached = int(r["customers_reached"] or 0)
        bookers = int(r["attributed_bookers"] or 0)
        cb = float(r["contribution_before_promo"] or 0)
        spend = float(r["marketing_spend"] or 0)
        inc_c = float(r["incremental_contribution"]) if r["incremental_contribution"] is not None else None
        r["reach_rate"] = round(reached / targeted, 4) if targeted > 0 else 0.0
        r["booking_conversion_rate"] = round(bookers / targeted, 4) if targeted > 0 else 0.0
        r["margin_erosion_pct"] = round((float(r["discount_cost"]) + float(r["loyalty_reward_cost"])) / cb, 4) if cb > 0 else 0.0
        r["incremental_roi"] = round(inc_c / spend, 2) if (inc_c is not None and spend > 0) else None

    # Segment-level treatment conversion & contribution across selected campaigns
    seg_matrix = fetch_all(
        """
        WITH assign_sub AS (
            SELECT
                ca.campaign_id,
                c.campaign_code,
                cs.segment_name,
                ca.customer_id,
                ca.assignment_group,
                c.start_date,
                (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS win_end
            FROM campaign_assignments ca
            JOIN campaigns c ON c.campaign_id = ca.campaign_id
            JOIN customers cu ON cu.customer_id = ca.customer_id
            JOIN customer_segments cs ON cs.segment_id = cu.segment_id
            WHERE ca.campaign_id = ANY(%s)
        ),
        cust_out AS (
            SELECT
                a.campaign_id,
                a.campaign_code,
                a.segment_name,
                a.assignment_group,
                a.customer_id,
                CASE WHEN COUNT(DISTINCT b.booking_id) > 0 THEN 1.0 ELSE 0.0 END AS converted
            FROM assign_sub a
            LEFT JOIN bookings b
                ON b.customer_id = a.customer_id
                AND b.booking_date BETWEEN a.start_date AND a.win_end
                AND b.booking_status <> 'cancelled'
            GROUP BY a.campaign_id, a.campaign_code, a.segment_name, a.assignment_group, a.customer_id
        )
        SELECT
            campaign_id,
            campaign_code,
            segment_name,
            COUNT(*) FILTER (WHERE assignment_group IN ('treatment', 'observational_targeted')) AS n_targeted,
            ROUND(AVG(converted) FILTER (WHERE assignment_group IN ('treatment', 'observational_targeted'))::NUMERIC, 4)::FLOAT8 AS treatment_conv,
            ROUND(AVG(converted) FILTER (WHERE assignment_group IN ('control', 'observational_comparison'))::NUMERIC, 4)::FLOAT8 AS control_conv
        FROM cust_out
        GROUP BY campaign_id, campaign_code, segment_name
        HAVING COUNT(*) FILTER (WHERE assignment_group IN ('treatment', 'observational_targeted')) >= 20
        ORDER BY segment_name, campaign_id
        """,
        (unique_ids,),
    )
    for m in seg_matrix:
        tc = m.get("treatment_conv")
        cc = m.get("control_conv")
        m["lift_pp"] = round((float(tc) - float(cc)) * 100.0, 2) if (tc is not None and cc is not None) else None

    # Route market overlap across selected campaigns
    route_overlap = fetch_all(
        """
        SELECT
            rm.market_code,
            rm.market_region,
            rm.haul_type,
            b.attributed_campaign_id AS campaign_id,
            c.campaign_code,
            COUNT(*) AS bookings,
            COALESCE(SUM(tr.net_ticket_revenue), 0)::FLOAT8 AS net_revenue
        FROM bookings b
        JOIN campaigns c ON c.campaign_id = b.attributed_campaign_id
        JOIN route_markets rm ON rm.route_market_id = b.route_market_id
        JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        WHERE b.attributed_campaign_id = ANY(%s)
          AND b.booking_status <> 'cancelled'
        GROUP BY rm.market_code, rm.market_region, rm.haul_type, b.attributed_campaign_id, c.campaign_code
        ORDER BY net_revenue DESC
        LIMIT 40
        """,
        (unique_ids,),
    )

    return {
        "campaigns": rows,
        "segment_matrix": seg_matrix,
        "route_overlap": route_overlap,
    }
