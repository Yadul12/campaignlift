"""FastAPI v1 Router exposing all CampaignLift commercial analytics, experimentation, simulation, SQL & report endpoints."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.config import settings
from app.db import fetch_one
from app.schemas.analytics import (
    BudgetSimulationRequest,
    CompareCampaignsRequest,
    GlobalFilterParams,
    SampleSizeRequest,
)
from app.services.campaign_service import (
    export_campaigns_csv,
    export_campaigns_excel,
    get_campaign_detail,
    list_campaigns,
)
from app.services.comparison_service import compare_campaigns
from app.services.customer_service import get_customer_response_analytics
from app.services.economics_service import get_promotion_economics
from app.services.experiment_service import (
    calculate_sample_size_service,
    get_experiment_detail,
    list_experiments,
)
from app.services.funnel_service import get_campaign_funnel
from app.services.overview_service import get_executive_overview, get_filter_options
from app.services.report_service import (
    build_executive_report,
    render_executive_report_excel,
    render_executive_report_pdf,
)
from app.services.simulator_service import get_simulator_defaults, run_budget_simulation
from app.services.sql_analytics_service import (
    execute_curated_query,
    export_sql_query_csv,
    get_data_audit_summary,
    list_sql_queries,
)

router = APIRouter(prefix="/api/v1")


def parse_global_filters(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    campaign_id: int | None = Query(default=None, ge=1),
    channel_id: int | None = Query(default=None, ge=1),
    segment_id: int | None = Query(default=None, ge=1),
    route_market_id: int | None = Query(default=None, ge=1),
    experiment_type: str | None = Query(default=None, pattern="^(RCT|Observational)$"),
    campaign_type: str | None = Query(default=None),
) -> GlobalFilterParams:
    try:
        return GlobalFilterParams(
            start_date=start_date,
            end_date=end_date,
            campaign_id=campaign_id,
            channel_id=channel_id,
            segment_id=segment_id,
            route_market_id=route_market_id,
            experiment_type=experiment_type,
            campaign_type=campaign_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/health", tags=["System"])
def health_check() -> dict[str, Any]:
    row = fetch_one("SELECT COUNT(*) AS campaigns FROM campaigns")
    return {
        "status": "ok",
        "version": settings.app_version,
        "dataset_label": settings.dataset_label,
        "campaigns_loaded": int(row["campaigns"]) if row else 0,
    }


@router.get("/filters", tags=["Filters"])
def filters_metadata() -> dict[str, Any]:
    return get_filter_options()


@router.get("/overview", tags=["Executive Overview"])
def executive_overview(filters: GlobalFilterParams = Depends(parse_global_filters)) -> dict[str, Any]:
    return get_executive_overview(filters)


@router.get("/campaigns", tags=["Campaign Performance"])
def campaigns_list(
    filters: GlobalFilterParams = Depends(parse_global_filters),
    search: str | None = Query(default=None, max_length=120),
    sort_by: str = Query(default="incremental_contribution"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    return list_campaigns(filters, search=search, sort_by=sort_by, sort_dir=sort_dir)


@router.get("/campaigns/export/csv", tags=["Campaign Performance"])
def campaigns_export_csv(
    filters: GlobalFilterParams = Depends(parse_global_filters),
    search: str | None = Query(default=None, max_length=120),
) -> Response:
    payload = export_campaigns_csv(filters, search=search)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="campaignlift_campaigns.csv"'},
    )


@router.get("/campaigns/export/excel", tags=["Campaign Performance"])
def campaigns_export_excel(
    filters: GlobalFilterParams = Depends(parse_global_filters),
    search: str | None = Query(default=None, max_length=120),
) -> Response:
    payload = export_campaigns_excel(filters, search=search)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="campaignlift_campaigns.xlsx"'},
    )


@router.get("/campaigns/{campaign_id}", tags=["Campaign Performance"])
def campaign_detail(campaign_id: int) -> dict[str, Any]:
    res = get_campaign_detail(campaign_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return res


@router.get("/funnel", tags=["Campaign Funnel"])
def campaign_funnel(filters: GlobalFilterParams = Depends(parse_global_filters)) -> dict[str, Any]:
    return get_campaign_funnel(filters)


@router.get("/experiments", tags=["Experimentation Lab"])
def experiments_list(filters: GlobalFilterParams = Depends(parse_global_filters)) -> dict[str, Any]:
    return list_experiments(filters)


@router.get("/experiments/{campaign_id}", tags=["Experimentation Lab"])
def experiment_detail(campaign_id: int) -> dict[str, Any]:
    res = get_experiment_detail(campaign_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Experiment for campaign {campaign_id} not found")
    return res


@router.post("/experiments/sample-size", tags=["Experimentation Lab"])
def sample_size_calculator(req: SampleSizeRequest) -> dict[str, Any]:
    return calculate_sample_size_service(req)


@router.get("/economics", tags=["Promotion Economics"])
def promotion_economics(filters: GlobalFilterParams = Depends(parse_global_filters)) -> dict[str, Any]:
    return get_promotion_economics(filters)


@router.get("/customers", tags=["Customer Response"])
def customer_response(
    filters: GlobalFilterParams = Depends(parse_global_filters),
    archetype: str | None = Query(default=None),
    limit: int = Query(default=50, ge=10, le=200),
) -> dict[str, Any]:
    return get_customer_response_analytics(filters, archetype=archetype, limit=limit)


@router.post("/compare", tags=["Campaign Comparison"])
def campaigns_compare(req: CompareCampaignsRequest) -> dict[str, Any]:
    res = compare_campaigns(req.campaign_ids)
    if len(res["campaigns"]) < 2:
        raise HTTPException(status_code=404, detail="At least two valid campaign IDs are required for comparison")
    return res


@router.get("/simulator/defaults", tags=["Budget Simulator"])
def simulator_defaults() -> dict[str, Any]:
    return get_simulator_defaults()


@router.post("/simulator/run", tags=["Budget Simulator"])
def simulator_run(req: BudgetSimulationRequest) -> dict[str, Any]:
    return run_budget_simulation(req)


@router.get("/sql-analytics/queries", tags=["SQL Analytics"])
def sql_library_list() -> dict[str, Any]:
    return {"queries": list_sql_queries()}


@router.get("/sql-analytics/queries/{query_id}/run", tags=["SQL Analytics"])
def sql_library_run(query_id: str, include_explain: bool = Query(default=True)) -> dict[str, Any]:
    res = execute_curated_query(query_id, include_explain=include_explain)
    if not res:
        raise HTTPException(status_code=404, detail=f"Curated SQL query '{query_id}' not found")
    return res


@router.get("/sql-analytics/queries/{query_id}/csv", tags=["SQL Analytics"])
def sql_library_csv(query_id: str) -> Response:
    payload = export_sql_query_csv(query_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Curated SQL query '{query_id}' not found")
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="campaignlift_sql_{query_id}.csv"'},
    )


@router.get("/sql-analytics/audit", tags=["SQL Analytics"])
def data_audit() -> dict[str, Any]:
    return get_data_audit_summary()


@router.get("/reports/campaign/{campaign_id}", tags=["Reports"])
def campaign_report_preview(campaign_id: int) -> dict[str, Any]:
    rep = build_executive_report(campaign_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return rep


@router.get("/reports/campaign/{campaign_id}/pdf", tags=["Reports"])
def campaign_report_pdf(campaign_id: int) -> Response:
    pdf_bytes = render_executive_report_pdf(campaign_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="campaignlift_report_{campaign_id}.pdf"'},
    )


@router.get("/reports/campaign/{campaign_id}/excel", tags=["Reports"])
def campaign_report_excel(campaign_id: int) -> Response:
    xlsx_bytes = render_executive_report_excel(campaign_id)
    if xlsx_bytes is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="campaignlift_report_{campaign_id}.xlsx"'},
    )
