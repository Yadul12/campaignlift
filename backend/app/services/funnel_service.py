"""Campaign Marketing Funnel Service: 6-stage monotonic airline funnel & drop-off diagnostics."""
from __future__ import annotations

from typing import Any

from app.db import fetch_all, fetch_one
from app.schemas.analytics import GlobalFilterParams
from app.services.filters import build_summary_where


def get_campaign_funnel(filters: GlobalFilterParams) -> dict[str, Any]:
    where_sql, params = build_summary_where(filters, alias="v")

    # Determine matching campaign IDs first (keeps all subsequent joins fast & consistent)
    camp_rows = fetch_all(
        f"SELECT v.campaign_id, v.eligible_audience_count, v.experiment_type FROM v_campaign_commercial_summary v WHERE {where_sql}",
        params,
    )
    if not camp_rows:
        return {
            "campaign_count": 0,
            "stages": [],
            "treatment_vs_control": None,
            "bottleneck": None,
            "by_channel": [],
            "by_segment": [],
            "assigned_vs_exposed_gap": {"assigned_targeted": 0, "reached": 0, "unreached": 0, "reach_rate": 0.0},
        }

    camp_ids = [int(r["campaign_id"]) for r in camp_rows]
    total_eligible = sum(int(r["eligible_audience_count"] or 0) for r in camp_rows)

    q_params: dict[str, Any] = {"camp_ids": camp_ids}
    seg_filter_sql = ""
    if filters.segment_id is not None:
        seg_filter_sql = "AND cu.segment_id = %(segment_id)s"
        q_params["segment_id"] = filters.segment_id
        # Scale eligible audience proportionally to segment share when segment filter is applied
        seg_share_row = fetch_one(
            "SELECT (COUNT(*) FILTER (WHERE segment_id = %s))::FLOAT8 / NULLIF(COUNT(*), 0) AS sh FROM customers",
            (filters.segment_id,),
        )
        seg_sh = float(seg_share_row["sh"] or 0.16) if seg_share_row else 0.16
        # Ensure eligible >= assigned later via max()
        total_eligible = int(round(total_eligible * seg_sh))

    route_filter_sql = ""
    if filters.route_market_id is not None:
        route_filter_sql = "AND b.route_market_id = %(route_market_id)s"
        q_params["route_market_id"] = filters.route_market_id

    # Core 6-stage funnel strictly separating Assigned vs. Reached/Exposed
    funnel_agg = fetch_one(
        f"""
        WITH scoped_assign AS (
            SELECT
                ca.assignment_id,
                ca.campaign_id,
                ca.customer_id,
                ca.channel_id,
                ca.assignment_group,
                cu.segment_id
            FROM campaign_assignments ca
            JOIN customers cu ON cu.customer_id = ca.customer_id
            WHERE ca.campaign_id = ANY(%(camp_ids)s)
            {seg_filter_sql}
        ),
        reached_flags AS (
            SELECT assignment_id, BOOL_OR(is_reached) AS is_reached
            FROM campaign_exposures
            WHERE campaign_id = ANY(%(camp_ids)s)
            GROUP BY assignment_id
        ),
        engaged_flags AS (
            SELECT assignment_id, BOOL_OR(engaged_flag) AS is_engaged
            FROM customer_responses
            WHERE campaign_id = ANY(%(camp_ids)s)
            GROUP BY assignment_id
        ),
        booked_flags AS (
            SELECT
                b.attributed_campaign_id AS campaign_id,
                b.customer_id,
                TRUE AS is_booked,
                BOOL_OR(b.travel_completed) AS is_completed
            FROM bookings b
            WHERE b.attributed_campaign_id = ANY(%(camp_ids)s)
              AND b.booking_status <> 'cancelled'
              {route_filter_sql}
            GROUP BY b.attributed_campaign_id, b.customer_id
        )
        SELECT
            COUNT(*) AS total_assigned_all,
            COUNT(*) FILTER (WHERE sa.assignment_group IN ('treatment', 'observational_targeted')) AS assigned_targeted,
            COUNT(*) FILTER (WHERE sa.assignment_group = 'control') AS assigned_control,
            COUNT(*) FILTER (WHERE sa.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE)) AS reached_count,
            COUNT(*) FILTER (WHERE sa.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE)) AS engaged_count,
            COUNT(*) FILTER (WHERE sa.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_booked, FALSE)) AS booked_count,
            COUNT(*) FILTER (WHERE sa.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_completed, FALSE)) AS completed_count
        FROM scoped_assign sa
        LEFT JOIN reached_flags rf ON rf.assignment_id = sa.assignment_id
        LEFT JOIN engaged_flags ef ON ef.assignment_id = sa.assignment_id
        LEFT JOIN booked_flags bf ON bf.campaign_id = sa.campaign_id AND bf.customer_id = sa.customer_id
        """,
        q_params,
    ) or {}

    total_assigned_all = int(funnel_agg.get("total_assigned_all") or 0)
    assigned_targeted = int(funnel_agg.get("assigned_targeted") or 0)
    assigned_control = int(funnel_agg.get("assigned_control") or 0)
    reached = int(funnel_agg.get("reached_count") or 0)
    engaged = int(funnel_agg.get("engaged_count") or 0)
    booked = int(funnel_agg.get("booked_count") or 0)
    completed = int(funnel_agg.get("completed_count") or 0)

    # Guarantee eligible >= total_assigned_all even after segment slicing
    eligible_eff = max(total_eligible, total_assigned_all)

    raw_stages = [
        ("eligible", "Eligible Audience", eligible_eff, "Customers meeting CRM, opt-in, segment, and frequency-cap criteria prior to campaign allocation."),
        ("assigned", "Assigned to Campaign (Targeted)", assigned_targeted, f"Customers assigned to receive the offer ({total_assigned_all:,} total assigned incl. {assigned_control:,} RCT holdout controls)."),
        ("reached", "Reached / Exposed", reached, "Targeted customers verified as delivered/impressed; excludes bounces, suppressions, and all control subjects."),
        ("engaged", "Engaged with Offer", engaged, "Reached customers who clicked, viewed offer terms, enrolled in miles, or applied a promo code."),
        ("booked", "Booked (Non-Cancelled)", booked, "Engaged customers completing a confirmed non-cancelled airline reservation attributed to the offer."),
        ("completed", "Completed Travel", completed, "Booked customers whose itinerary has flown and completed travel."),
    ]

    stages = []
    worst_dropoff = None
    for idx, (key, label, count, desc) in enumerate(raw_stages):
        prev_cnt = raw_stages[idx - 1][2] if idx > 0 else count
        step_conv = round(count / prev_cnt, 4) if (idx > 0 and prev_cnt > 0) else 1.0
        drop_abs = (prev_cnt - count) if idx > 0 else 0
        drop_pct = round(1.0 - step_conv, 4) if idx > 0 else 0.0
        cum_from_assigned = round(count / assigned_targeted, 4) if (assigned_targeted > 0 and idx >= 1) else (1.0 if idx == 0 else 0.0)
        stage_obj = {
            "stage_key": key,
            "stage_label": label,
            "count": count,
            "step_conversion_rate": step_conv,
            "dropoff_count": drop_abs,
            "dropoff_rate": drop_pct,
            "cumulative_from_assigned": cum_from_assigned,
            "description": desc,
        }
        stages.append(stage_obj)
        # Identify biggest post-assignment drop-off stage
        if idx >= 2 and (worst_dropoff is None or drop_pct > worst_dropoff["dropoff_rate"]):
            worst_dropoff = {
                "from_stage": raw_stages[idx - 1][1],
                "to_stage": label,
                "dropoff_count": drop_abs,
                "dropoff_rate": drop_pct,
                "step_conversion_rate": step_conv,
            }

    # Treatment vs. Control ITT booking & completed travel funnel comparison (RCT campaigns only)
    rct_ids = [int(r["campaign_id"]) for r in camp_rows if r["experiment_type"] == "RCT"]
    tvc = None
    if rct_ids:
        tvc_params = {"rct_ids": rct_ids}
        if filters.segment_id is not None:
            tvc_params["segment_id"] = filters.segment_id
        if filters.route_market_id is not None:
            tvc_params["route_market_id"] = filters.route_market_id
        tvc_row = fetch_one(
            f"""
            WITH rct_a AS (
                SELECT
                    ca.assignment_id,
                    ca.campaign_id,
                    ca.customer_id,
                    ca.assignment_group,
                    c.start_date,
                    (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS win_end
                FROM campaign_assignments ca
                JOIN campaigns c ON c.campaign_id = ca.campaign_id
                JOIN customers cu ON cu.customer_id = ca.customer_id
                WHERE ca.campaign_id = ANY(%(rct_ids)s)
                  AND ca.assignment_group IN ('treatment', 'control')
                  {seg_filter_sql}
            ),
            reached_t AS (
                SELECT assignment_id, BOOL_OR(is_reached) AS is_reached
                FROM campaign_exposures
                WHERE campaign_id = ANY(%(rct_ids)s)
                GROUP BY assignment_id
            ),
            outcomes AS (
                SELECT
                    ra.assignment_id,
                    ra.assignment_group,
                    COALESCE(rt.is_reached, FALSE) AS is_reached,
                    BOOL_OR(b.booking_id IS NOT NULL) AS booked_window,
                    BOOL_OR(COALESCE(b.travel_completed, FALSE)) AS completed_window
                FROM rct_a ra
                LEFT JOIN reached_t rt ON rt.assignment_id = ra.assignment_id
                LEFT JOIN bookings b
                    ON b.customer_id = ra.customer_id
                    AND b.booking_date BETWEEN ra.start_date AND ra.win_end
                    AND b.booking_status <> 'cancelled'
                    {route_filter_sql}
                GROUP BY ra.assignment_id, ra.assignment_group, rt.is_reached
            )
            SELECT
                COUNT(*) FILTER (WHERE assignment_group = 'treatment') AS t_assigned,
                COUNT(*) FILTER (WHERE assignment_group = 'treatment' AND is_reached) AS t_reached,
                COUNT(*) FILTER (WHERE assignment_group = 'treatment' AND booked_window) AS t_booked,
                COUNT(*) FILTER (WHERE assignment_group = 'treatment' AND completed_window) AS t_completed,
                COUNT(*) FILTER (WHERE assignment_group = 'control') AS c_assigned,
                COUNT(*) FILTER (WHERE assignment_group = 'control' AND booked_window) AS c_booked,
                COUNT(*) FILTER (WHERE assignment_group = 'control' AND completed_window) AS c_completed
            FROM outcomes
            """,
            tvc_params,
        ) or {}
        t_a = int(tvc_row.get("t_assigned") or 0)
        c_a = int(tvc_row.get("c_assigned") or 0)
        if t_a > 0 and c_a > 0:
            tvc = {
                "rct_campaign_count": len(rct_ids),
                "treatment": {
                    "assigned": t_a,
                    "reached": int(tvc_row.get("t_reached") or 0),
                    "reach_rate": round(int(tvc_row.get("t_reached") or 0) / t_a, 4),
                    "booked_itt": int(tvc_row.get("t_booked") or 0),
                    "booking_rate_itt": round(int(tvc_row.get("t_booked") or 0) / t_a, 4),
                    "completed_itt": int(tvc_row.get("t_completed") or 0),
                    "completion_rate_itt": round(int(tvc_row.get("t_completed") or 0) / t_a, 4),
                },
                "control": {
                    "assigned": c_a,
                    "reached": 0,
                    "reach_rate": 0.0,
                    "booked_itt": int(tvc_row.get("c_booked") or 0),
                    "booking_rate_itt": round(int(tvc_row.get("c_booked") or 0) / c_a, 4),
                    "completed_itt": int(tvc_row.get("c_completed") or 0),
                    "completion_rate_itt": round(int(tvc_row.get("c_completed") or 0) / c_a, 4),
                },
            }

    # Breakdown by Channel
    by_channel = fetch_all(
        f"""
        WITH scoped_assign AS (
            SELECT ca.assignment_id, ca.campaign_id, ca.customer_id, ca.channel_id
            FROM campaign_assignments ca
            JOIN customers cu ON cu.customer_id = ca.customer_id
            WHERE ca.campaign_id = ANY(%(camp_ids)s)
              AND ca.assignment_group IN ('treatment', 'observational_targeted')
              {seg_filter_sql}
        ),
        rf AS (SELECT assignment_id, BOOL_OR(is_reached) AS is_reached FROM campaign_exposures WHERE campaign_id = ANY(%(camp_ids)s) GROUP BY assignment_id),
        ef AS (SELECT assignment_id, BOOL_OR(engaged_flag) AS is_engaged FROM customer_responses WHERE campaign_id = ANY(%(camp_ids)s) GROUP BY assignment_id),
        bf AS (
            SELECT attributed_campaign_id AS campaign_id, customer_id, TRUE AS is_booked, BOOL_OR(travel_completed) AS is_completed
            FROM bookings b
            WHERE attributed_campaign_id = ANY(%(camp_ids)s) AND booking_status <> 'cancelled' {route_filter_sql}
            GROUP BY attributed_campaign_id, customer_id
        )
        SELECT
            ch.channel_name,
            COUNT(*) AS assigned,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE)) AS reached,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE)) AS engaged,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_booked, FALSE)) AS booked,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_completed, FALSE)) AS completed
        FROM scoped_assign sa
        JOIN campaign_channels ch ON ch.channel_id = sa.channel_id
        LEFT JOIN rf ON rf.assignment_id = sa.assignment_id
        LEFT JOIN ef ON ef.assignment_id = sa.assignment_id
        LEFT JOIN bf ON bf.campaign_id = sa.campaign_id AND bf.customer_id = sa.customer_id
        GROUP BY ch.channel_name
        ORDER BY assigned DESC
        """,
        q_params,
    )
    for row in by_channel:
        row["reach_rate"] = round(row["reached"] / row["assigned"], 4) if row["assigned"] else 0.0
        row["engage_rate"] = round(row["engaged"] / row["reached"], 4) if row["reached"] else 0.0
        row["book_of_engaged"] = round(row["booked"] / row["engaged"], 4) if row["engaged"] else 0.0
        row["end_to_end_rate"] = round(row["completed"] / row["assigned"], 4) if row["assigned"] else 0.0

    # Breakdown by Segment
    by_segment = fetch_all(
        f"""
        WITH scoped_assign AS (
            SELECT ca.assignment_id, ca.campaign_id, ca.customer_id, cu.segment_id
            FROM campaign_assignments ca
            JOIN customers cu ON cu.customer_id = ca.customer_id
            WHERE ca.campaign_id = ANY(%(camp_ids)s)
              AND ca.assignment_group IN ('treatment', 'observational_targeted')
              {seg_filter_sql}
        ),
        rf AS (SELECT assignment_id, BOOL_OR(is_reached) AS is_reached FROM campaign_exposures WHERE campaign_id = ANY(%(camp_ids)s) GROUP BY assignment_id),
        ef AS (SELECT assignment_id, BOOL_OR(engaged_flag) AS is_engaged FROM customer_responses WHERE campaign_id = ANY(%(camp_ids)s) GROUP BY assignment_id),
        bf AS (
            SELECT attributed_campaign_id AS campaign_id, customer_id, TRUE AS is_booked, BOOL_OR(travel_completed) AS is_completed
            FROM bookings b
            WHERE attributed_campaign_id = ANY(%(camp_ids)s) AND booking_status <> 'cancelled' {route_filter_sql}
            GROUP BY attributed_campaign_id, customer_id
        )
        SELECT
            cs.segment_name,
            COUNT(*) AS assigned,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE)) AS reached,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE)) AS engaged,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_booked, FALSE)) AS booked,
            COUNT(*) FILTER (WHERE COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(bf.is_completed, FALSE)) AS completed
        FROM scoped_assign sa
        JOIN customer_segments cs ON cs.segment_id = sa.segment_id
        LEFT JOIN rf ON rf.assignment_id = sa.assignment_id
        LEFT JOIN ef ON ef.assignment_id = sa.assignment_id
        LEFT JOIN bf ON bf.campaign_id = sa.campaign_id AND bf.customer_id = sa.customer_id
        GROUP BY cs.segment_name
        ORDER BY assigned DESC
        """,
        q_params,
    )
    for row in by_segment:
        row["reach_rate"] = round(row["reached"] / row["assigned"], 4) if row["assigned"] else 0.0
        row["engage_rate"] = round(row["engaged"] / row["reached"], 4) if row["reached"] else 0.0
        row["book_of_engaged"] = round(row["booked"] / row["engaged"], 4) if row["engaged"] else 0.0
        row["end_to_end_rate"] = round(row["completed"] / row["assigned"], 4) if row["assigned"] else 0.0

    return {
        "campaign_count": len(camp_rows),
        "stages": stages,
        "assigned_vs_exposed_gap": {
            "assigned_targeted": assigned_targeted,
            "reached": reached,
            "unreached": max(0, assigned_targeted - reached),
            "reach_rate": round(reached / assigned_targeted, 4) if assigned_targeted > 0 else 0.0,
        },
        "bottleneck": worst_dropoff,
        "treatment_vs_control": tvc,
        "by_channel": by_channel,
        "by_segment": by_segment,
    }
