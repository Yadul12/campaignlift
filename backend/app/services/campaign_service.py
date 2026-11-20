"""Campaign Performance, Drill-Down Inspector, and Tabular Export Service."""
from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.db import fetch_all, fetch_one
from app.schemas.analytics import GlobalFilterParams
from app.services.filters import build_summary_where


SORT_COLUMNS = {
    "start_date": "v.start_date",
    "campaign_name": "v.campaign_name",
    "marketing_spend": "v.marketing_spend",
    "attributed_bookings": "v.attributed_bookings",
    "gross_booking_revenue": "v.gross_booking_revenue",
    "discount_cost": "v.discount_cost",
    "contribution_after_promo": "v.contribution_after_promo",
    "incremental_bookings": "v.incremental_bookings",
    "incremental_revenue": "v.incremental_revenue",
    "incremental_contribution": "v.incremental_contribution",
    "cost_per_incremental_booking": "v.cost_per_incremental_booking",
    "conversion_p_value": "v.conversion_p_value",
}


def list_campaigns(
    filters: GlobalFilterParams,
    search: str | None = None,
    sort_by: str = "incremental_contribution",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    where_sql, params = build_summary_where(filters, alias="v")
    if search and search.strip():
        where_sql += " AND (v.campaign_name ILIKE %(q)s OR v.campaign_code ILIKE %(q)s OR v.campaign_type ILIKE %(q)s OR v.channel_name ILIKE %(q)s OR v.target_segment_name ILIKE %(q)s OR v.target_route_code ILIKE %(q)s)"
        params["q"] = f"%{search.strip()}%"

    col = SORT_COLUMNS.get(sort_by, "v.incremental_contribution")
    direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

    rows = fetch_all(
        f"""
        SELECT
            v.campaign_id,
            v.campaign_code,
            v.campaign_name,
            v.campaign_type,
            v.experiment_type,
            v.start_date,
            v.end_date,
            v.booking_window_days,
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            v.status,
            v.channel_id,
            v.channel_name,
            v.segment_id,
            v.target_segment_name,
            v.route_market_id,
            v.target_route_code,
            v.target_route_region,
            v.eligible_audience_count,
            v.total_assigned,
            v.customers_targeted,
            v.control_customers,
            v.customers_reached,
            v.customers_engaged,
            v.attributed_bookings,
            v.attributed_bookers,
            v.completed_travelers,
            v.marketing_spend::FLOAT8 AS marketing_spend,
            v.gross_booking_revenue::FLOAT8 AS gross_booking_revenue,
            v.discount_cost::FLOAT8 AS discount_cost,
            v.loyalty_reward_cost::FLOAT8 AS loyalty_reward_cost,
            v.variable_cost::FLOAT8 AS variable_cost,
            v.contribution_before_promo::FLOAT8 AS contribution_before_promo,
            v.contribution_after_promo::FLOAT8 AS contribution_after_promo,
            v.conversion_control::FLOAT8 AS conversion_control,
            v.conversion_treatment::FLOAT8 AS conversion_treatment,
            v.conversion_lift_abs::FLOAT8 AS conversion_lift_abs,
            v.conversion_lift_rel::FLOAT8 AS conversion_lift_rel,
            v.conversion_p_value::FLOAT8 AS conversion_p_value,
            v.contrib_per_cust_p_value::FLOAT8 AS contrib_per_cust_p_value,
            v.incremental_bookings::FLOAT8 AS incremental_bookings,
            v.incremental_revenue::FLOAT8 AS incremental_revenue,
            v.incremental_contribution::FLOAT8 AS incremental_contribution,
            v.cost_per_incremental_booking::FLOAT8 AS cost_per_incremental_booking,
            v.is_statistically_significant,
            v.srm_passed,
            v.recommendation_status
        FROM v_campaign_commercial_summary v
        WHERE {where_sql}
        ORDER BY {col} {direction} NULLS LAST, v.campaign_id DESC
        """,
        params,
    )

    items = []
    for r in rows:
        targeted = int(r["customers_targeted"] or 0)
        reached = int(r["customers_reached"] or 0)
        bookers = int(r["attributed_bookers"] or 0)
        cb = float(r["contribution_before_promo"] or 0.0)
        items.append({
            **r,
            "start_date": str(r["start_date"]),
            "end_date": str(r["end_date"]),
            "reach_rate": round(reached / targeted, 4) if targeted > 0 else 0.0,
            "campaign_conversion_rate": round(bookers / reached, 4) if reached > 0 else 0.0,
            "booking_conversion_rate": round(bookers / targeted, 4) if targeted > 0 else 0.0,
            "margin_erosion_pct": round((float(r["discount_cost"]) + float(r["loyalty_reward_cost"])) / cb, 4) if cb > 0 else 0.0,
        })

    # Route market breakdown across filtered campaigns
    route_breakdown = fetch_all(
        f"""
        SELECT
            rm.route_market_id,
            rm.market_code,
            rm.market_region,
            rm.haul_type,
            rm.load_factor_baseline::FLOAT8 AS load_factor_baseline,
            COUNT(DISTINCT b.booking_id) AS attributed_bookings,
            COALESCE(SUM(tr.gross_total_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(tr.discount_amount), 0)::FLOAT8 AS discount_cost,
            COALESCE(SUM(tr.contribution_before_promo - tr.discount_amount), 0)::FLOAT8 AS net_contribution
        FROM bookings b
        JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        JOIN route_markets rm ON rm.route_market_id = b.route_market_id
        JOIN v_campaign_commercial_summary v ON v.campaign_id = b.attributed_campaign_id
        WHERE b.booking_status <> 'cancelled'
          AND {where_sql}
        GROUP BY rm.route_market_id, rm.market_code, rm.market_region, rm.haul_type, rm.load_factor_baseline
        ORDER BY net_contribution DESC
        LIMIT 25
        """,
        params,
    )

    return {
        "count": len(items),
        "campaigns": items,
        "route_breakdown": route_breakdown,
    }


def get_campaign_detail(campaign_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT
            v.*,
            c.hypothesis,
            c.eligibility_criteria,
            c.treatment_split_target::FLOAT8 AS treatment_split_target,
            ers.srm_p_value,
            ers.max_covariate_smd::FLOAT8 AS max_covariate_smd,
            ers.exposure_compliance_rate::FLOAT8 AS exposure_compliance_rate,
            ers.conversion_ci_low::FLOAT8 AS conversion_ci_low,
            ers.conversion_ci_high::FLOAT8 AS conversion_ci_high,
            ers.contrib_per_cust_control::FLOAT8 AS contrib_per_cust_control,
            ers.contrib_per_cust_treatment::FLOAT8 AS contrib_per_cust_treatment
        FROM v_campaign_commercial_summary v
        JOIN campaigns c ON c.campaign_id = v.campaign_id
        LEFT JOIN experiment_results_store ers ON ers.campaign_id = v.campaign_id
        WHERE v.campaign_id = %s
        """,
        (campaign_id,),
    )
    if not row:
        return None

    cost_breakdown = fetch_all(
        """
        SELECT cost_category, SUM(amount_usd)::FLOAT8 AS amount_usd
        FROM marketing_costs
        WHERE campaign_id = %s
        GROUP BY cost_category
        ORDER BY amount_usd DESC
        """,
        (campaign_id,),
    )

    daily_bookings = fetch_all(
        """
        SELECT
            b.booking_date::TEXT AS booking_date,
            COUNT(*) AS attributed_bookings,
            COALESCE(SUM(tr.gross_total_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(tr.discount_amount), 0)::FLOAT8 AS discount_cost
        FROM bookings b
        JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        WHERE b.attributed_campaign_id = %s AND b.booking_status <> 'cancelled'
        GROUP BY b.booking_date
        ORDER BY b.booking_date
        """,
        (campaign_id,),
    )

    segment_mix = fetch_all(
        """
        SELECT
            cs.segment_name,
            COUNT(*) FILTER (WHERE ca.assignment_group IN ('treatment', 'observational_targeted')) AS targeted,
            COUNT(*) FILTER (WHERE ca.assignment_group = 'control') AS control,
            COUNT(DISTINCT b.booking_id) AS attributed_bookings,
            COALESCE(SUM(tr.net_ticket_revenue), 0)::FLOAT8 AS net_revenue
        FROM campaign_assignments ca
        JOIN customers cu ON cu.customer_id = ca.customer_id
        JOIN customer_segments cs ON cs.segment_id = cu.segment_id
        LEFT JOIN bookings b ON b.customer_id = ca.customer_id
            AND b.attributed_campaign_id = ca.campaign_id
            AND b.booking_status <> 'cancelled'
        LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        WHERE ca.campaign_id = %s
        GROUP BY cs.segment_name
        ORDER BY targeted DESC
        """,
        (campaign_id,),
    )

    top_routes = fetch_all(
        """
        SELECT
            rm.market_code,
            rm.market_region,
            COUNT(*) AS bookings,
            COALESCE(SUM(tr.gross_total_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(tr.discount_amount), 0)::FLOAT8 AS discount_cost
        FROM bookings b
        JOIN route_markets rm ON rm.route_market_id = b.route_market_id
        JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        WHERE b.attributed_campaign_id = %s AND b.booking_status <> 'cancelled'
        GROUP BY rm.market_code, rm.market_region
        ORDER BY gross_revenue DESC
        LIMIT 8
        """,
        (campaign_id,),
    )

    # Convert Decimal/date fields cleanly
    detail = {
        k: (str(v) if k in ("start_date", "end_date") else (float(v) if hasattr(v, "as_tuple") else v))
        for k, v in row.items()
    }
    return {
        "campaign": detail,
        "cost_breakdown": cost_breakdown,
        "daily_bookings": daily_bookings,
        "segment_mix": segment_mix,
        "top_routes": top_routes,
    }


def export_campaigns_csv(filters: GlobalFilterParams, search: str | None = None) -> bytes:
    data = list_campaigns(filters, search=search)
    buf = io.StringIO()
    cols = [
        "campaign_code", "campaign_name", "campaign_type", "experiment_type", "start_date", "end_date",
        "channel_name", "target_segment_name", "target_route_code", "discount_pct", "bonus_miles_offer",
        "marketing_spend", "customers_targeted", "customers_reached", "attributed_bookings",
        "gross_booking_revenue", "discount_cost", "loyalty_reward_cost", "contribution_after_promo",
        "incremental_bookings", "incremental_revenue", "incremental_contribution",
        "cost_per_incremental_booking", "conversion_p_value", "recommendation_status",
    ]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in data["campaigns"]:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def export_campaigns_excel(filters: GlobalFilterParams, search: str | None = None) -> bytes:
    data = list_campaigns(filters, search=search)
    wb = Workbook()
    ws = wb.active
    ws.title = "Campaign Performance"

    headers = [
        "Code", "Campaign Name", "Type", "Study Design", "Start Date", "End Date",
        "Channel", "Segment", "Route Market", "Discount %", "Bonus Miles",
        "Spend ($)", "Targeted", "Reached", "Attributed Bookings",
        "Gross Revenue ($)", "Discount Cost ($)", "Miles Cost ($)", "Contrib After Promo ($)",
        "Incremental Bookings", "Incremental Revenue ($)", "Incremental Contrib ($)",
        "Cost / Inc Booking ($)", "Conv p-value", "Recommendation",
    ]
    keys = [
        "campaign_code", "campaign_name", "campaign_type", "experiment_type", "start_date", "end_date",
        "channel_name", "target_segment_name", "target_route_code", "discount_pct", "bonus_miles_offer",
        "marketing_spend", "customers_targeted", "customers_reached", "attributed_bookings",
        "gross_booking_revenue", "discount_cost", "loyalty_reward_cost", "contribution_after_promo",
        "incremental_bookings", "incremental_revenue", "incremental_contribution",
        "cost_per_incremental_booking", "conversion_p_value", "recommendation_status",
    ]

    navy_fill = PatternFill(start_color="0F2942", end_color="0F2942", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)

    ws.append(["CampaignLift — Airline Marketing Promotions Portfolio Export (SYNTHETIC DATASET)"])
    ws["A1"].font = Font(bold=True, size=12, color="0F2942")
    ws.append([])
    ws.append(headers)
    for cell in ws[3]:
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in data["campaigns"]:
        ws.append([row.get(k) for k in keys])

    ws.freeze_panes = "A4"
    for col_cells in ws.columns:
        max_len = max(len(str(c.value or "")) for c in col_cells[:40])
        ws.column_dimensions[col_cells[0].column_letter].width = min(38, max(12, max_len + 3))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
