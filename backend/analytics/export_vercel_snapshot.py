"""
Exports a complete, 100% PostgreSQL-sourced analytical snapshot and OLAP cubes
into `frontend/src/data/snapshot/campaignlift_snapshot.json` (plus baseline PDF/Excel
artifacts in `frontend/public/exports/`) so CampaignLift runs with 100% interactive
filtering, drill-downs, A/B experimentation, simulation, SQL inspection, and downloads
on Vercel Serverless deployments while using live FastAPI + PostgreSQL in Docker/local dev.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db import fetch_all
from app.schemas.analytics import GlobalFilterParams
from app.services.campaign_service import get_campaign_detail, list_campaigns
from app.services.customer_service import get_customer_response_analytics
from app.services.economics_service import METRIC_FORMULAS
from app.services.experiment_service import get_experiment_detail
from app.services.overview_service import get_filter_options
from app.services.report_service import (
    build_executive_report,
    render_executive_report_excel,
    render_executive_report_pdf,
)
from app.services.simulator_service import get_simulator_defaults
from app.services.sql_analytics_service import (
    execute_curated_query,
    get_data_audit_summary,
    list_sql_queries,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.snapshot")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_snapshot(out_path: Path) -> None:
    logger.info("Exporting CampaignLift PostgreSQL snapshot to %s ...", out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    filters_meta = get_filter_options()
    all_campaigns_res = list_campaigns(GlobalFilterParams())
    campaigns_list = all_campaigns_res["campaigns"]

    # 1. Per-campaign detail drawers & experiment details & executive reports
    campaign_details: dict[str, Any] = {}
    experiment_details: dict[str, Any] = {}
    executive_reports: dict[str, Any] = {}

    for c in campaigns_list:
        cid = int(c["campaign_id"])
        k = str(cid)
        campaign_details[k] = get_campaign_detail(cid)
        experiment_details[k] = get_experiment_detail(cid)
        executive_reports[k] = build_executive_report(cid)

    # 2. Campaign x Segment funnel & ITT outcome cube (for dynamic segment/channel/date/study filtering)
    funnel_cube = fetch_all(
        """
        WITH assign_base AS (
            SELECT
                ca.assignment_id,
                ca.campaign_id,
                ca.customer_id,
                ca.channel_id,
                ch.channel_name,
                ca.assignment_group,
                cu.segment_id,
                cs.segment_name,
                c.experiment_type,
                c.start_date,
                (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS win_end
            FROM campaign_assignments ca
            JOIN campaigns c ON c.campaign_id = ca.campaign_id
            JOIN campaign_channels ch ON ch.channel_id = ca.channel_id
            JOIN customers cu ON cu.customer_id = ca.customer_id
            JOIN customer_segments cs ON cs.segment_id = cu.segment_id
        ),
        rf AS (
            SELECT assignment_id, BOOL_OR(is_reached) AS is_reached
            FROM campaign_exposures
            GROUP BY assignment_id
        ),
        ef AS (
            SELECT assignment_id, BOOL_OR(engaged_flag) AS is_engaged
            FROM customer_responses
            GROUP BY assignment_id
        ),
        attr_bf AS (
            SELECT
                attributed_campaign_id AS campaign_id,
                customer_id,
                TRUE AS is_booked,
                BOOL_OR(travel_completed) AS is_completed
            FROM bookings
            WHERE attributed_campaign_id IS NOT NULL AND booking_status <> 'cancelled'
            GROUP BY attributed_campaign_id, customer_id
        ),
        itt_bf AS (
            SELECT
                ab.assignment_id,
                BOOL_OR(b.booking_id IS NOT NULL) AS itt_booked,
                BOOL_OR(COALESCE(b.travel_completed, FALSE)) AS itt_completed
            FROM assign_base ab
            LEFT JOIN bookings b
                ON b.customer_id = ab.customer_id
                AND b.booking_date BETWEEN ab.start_date AND ab.win_end
                AND b.booking_status <> 'cancelled'
            GROUP BY ab.assignment_id
        )
        SELECT
            ab.campaign_id,
            ab.channel_id,
            ab.channel_name,
            ab.segment_id,
            ab.segment_name,
            ab.experiment_type,
            COUNT(*) AS total_assigned_all,
            COUNT(*) FILTER (WHERE ab.assignment_group IN ('treatment', 'observational_targeted')) AS assigned_targeted,
            COUNT(*) FILTER (WHERE ab.assignment_group = 'control') AS assigned_control,
            COUNT(*) FILTER (WHERE ab.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE)) AS reached_count,
            COUNT(*) FILTER (WHERE ab.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE)) AS engaged_count,
            COUNT(*) FILTER (WHERE ab.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(abf.is_booked, FALSE)) AS booked_count,
            COUNT(*) FILTER (WHERE ab.assignment_group IN ('treatment', 'observational_targeted') AND COALESCE(rf.is_reached, FALSE) AND COALESCE(ef.is_engaged, FALSE) AND COALESCE(abf.is_completed, FALSE)) AS completed_count,
            COUNT(*) FILTER (WHERE ab.assignment_group = 'treatment' AND COALESCE(ibf.itt_booked, FALSE)) AS rct_t_booked_itt,
            COUNT(*) FILTER (WHERE ab.assignment_group = 'treatment' AND COALESCE(ibf.itt_completed, FALSE)) AS rct_t_completed_itt,
            COUNT(*) FILTER (WHERE ab.assignment_group = 'control' AND COALESCE(ibf.itt_booked, FALSE)) AS rct_c_booked_itt,
            COUNT(*) FILTER (WHERE ab.assignment_group = 'control' AND COALESCE(ibf.itt_completed, FALSE)) AS rct_c_completed_itt
        FROM assign_base ab
        LEFT JOIN rf ON rf.assignment_id = ab.assignment_id
        LEFT JOIN ef ON ef.assignment_id = ab.assignment_id
        LEFT JOIN attr_bf abf ON abf.campaign_id = ab.campaign_id AND abf.customer_id = ab.customer_id
        LEFT JOIN itt_bf ibf ON ibf.assignment_id = ab.assignment_id
        GROUP BY ab.campaign_id, ab.channel_id, ab.channel_name, ab.segment_id, ab.segment_name, ab.experiment_type
        ORDER BY ab.campaign_id, ab.segment_id
        """
    )

    # 3. Campaign x Route Market attributed booking cube
    route_cube = fetch_all(
        """
        SELECT
            b.attributed_campaign_id AS campaign_id,
            c.campaign_code,
            rm.route_market_id,
            rm.market_code,
            rm.market_region,
            rm.haul_type,
            rm.load_factor_baseline::FLOAT8 AS load_factor_baseline,
            COUNT(DISTINCT b.booking_id) AS attributed_bookings,
            COALESCE(SUM(tr.gross_total_revenue), 0)::FLOAT8 AS gross_revenue,
            COALESCE(SUM(tr.discount_amount), 0)::FLOAT8 AS discount_cost,
            COALESCE(SUM(tr.net_ticket_revenue), 0)::FLOAT8 AS net_revenue,
            COALESCE(SUM(tr.contribution_before_promo - tr.discount_amount), 0)::FLOAT8 AS net_contribution
        FROM bookings b
        JOIN campaigns c ON c.campaign_id = b.attributed_campaign_id
        JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        JOIN route_markets rm ON rm.route_market_id = b.route_market_id
        WHERE b.attributed_campaign_id IS NOT NULL
          AND b.booking_status <> 'cancelled'
        GROUP BY b.attributed_campaign_id, c.campaign_code, rm.route_market_id, rm.market_code, rm.market_region, rm.haul_type, rm.load_factor_baseline
        ORDER BY b.attributed_campaign_id, net_contribution DESC
        """
    )

    # 4. Customer response analytics (all segments + per-segment slices + 200 cohort sample)
    customers_all = get_customer_response_analytics(GlobalFilterParams(), limit=200)
    customers_by_segment: dict[str, Any] = {}
    for seg in filters_meta["segments"]:
        sid = int(seg["segment_id"])
        customers_by_segment[str(sid)] = get_customer_response_analytics(
            GlobalFilterParams(segment_id=sid), limit=120
        )

    # 5. Simulator defaults
    sim_defaults = get_simulator_defaults()

    # 6. SQL Analytics Library & Data Audit
    sql_queries = list_sql_queries()
    sql_results = {q["id"]: execute_curated_query(q["id"], include_explain=True) for q in sql_queries}
    audit_summary = get_data_audit_summary()

    # 7. Pre-render compact PDF & Excel bytes (base64) for top representative campaigns + fallback
    sample_pdf_b64: dict[str, str] = {}
    sample_xlsx_b64: dict[str, str] = {}
    for c in campaigns_list[:15]:
        cid = int(c["campaign_id"])
        pdf_b = render_executive_report_pdf(cid)
        xlsx_b = render_executive_report_excel(cid)
        if pdf_b:
            sample_pdf_b64[str(cid)] = base64.b64encode(pdf_b).decode("ascii")
        if xlsx_b:
            sample_xlsx_b64[str(cid)] = base64.b64encode(xlsx_b).decode("ascii")

    payload = {
        "filters": filters_meta,
        "campaigns": campaigns_list,
        "campaign_details": campaign_details,
        "experiment_details": experiment_details,
        "executive_reports": executive_reports,
        "funnel_cube": funnel_cube,
        "route_cube": route_cube,
        "economics_formulas": METRIC_FORMULAS,
        "customers_all": customers_all,
        "customers_by_segment": customers_by_segment,
        "simulator_defaults": sim_defaults,
        "sql_queries": sql_queries,
        "sql_results": sql_results,
        "audit_summary": audit_summary,
        "report_pdfs_b64": sample_pdf_b64,
        "report_xlsxs_b64": sample_xlsx_b64,
    }

    raw = json.dumps(payload, default=_json_default, separators=(",", ":"))
    out_path.write_text(raw, encoding="utf-8")
    logger.info("Exported snapshot (%d bytes / %.2f MB) to %s", len(raw), len(raw) / (1024 * 1024), out_path)


if __name__ == "__main__":
    target = Path("/app/snapshot_out/campaignlift_snapshot.json")
    export_snapshot(target)
