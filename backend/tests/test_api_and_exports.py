"""End-to-end API, filter responsiveness, economics, SQL library, and export consistency tests."""
from __future__ import annotations

import io
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app


def test_health_and_filters():
    with TestClient(app) as client:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["campaigns_loaded"] >= 100

        rf = client.get("/api/v1/filters")
        assert rf.status_code == 200
        fdata = rf.json()
        assert len(fdata["channels"]) == 8
        assert len(fdata["segments"]) == 6
        assert len(fdata["routes"]) == 36
        assert len(fdata["campaigns"]) >= 100


def test_overview_and_filter_propagation():
    with TestClient(app) as client:
        all_ov = client.get("/api/v1/overview").json()
        assert all_ov["kpis"]["total_campaigns"] >= 100
        assert all_ov["kpis"]["rct_campaigns"] >= 60
        assert all_ov["kpis"]["obs_campaigns"] >= 20

        # Filtering by channel must change totals cleanly
        ch_ov = client.get("/api/v1/overview?channel_id=1").json()
        assert 0 < ch_ov["kpis"]["total_campaigns"] < all_ov["kpis"]["total_campaigns"]
        assert ch_ov["kpis"]["total_spend"] < all_ov["kpis"]["total_spend"]

        # Filtering by date range must change totals cleanly
        dt_ov = client.get("/api/v1/overview?start_date=2025-01-01&end_date=2025-12-31").json()
        assert 0 < dt_ov["kpis"]["total_campaigns"] < all_ov["kpis"]["total_campaigns"]

        # Invalid date order returns 422
        bad = client.get("/api/v1/overview?start_date=2026-01-01&end_date=2025-01-01")
        assert bad.status_code == 422


def test_funnel_monotonicity_and_experiments_causal_guard():
    with TestClient(app) as client:
        fun = client.get("/api/v1/funnel").json()
        stages = fun["stages"]
        assert len(stages) == 6
        counts = [s["count"] for s in stages]
        assert counts == sorted(counts, reverse=True), f"Funnel not monotonic: {counts}"
        assert fun["assigned_vs_exposed_gap"]["assigned_targeted"] > fun["assigned_vs_exposed_gap"]["reached"]

        exps = client.get("/api/v1/experiments").json()["experiments"]
        rct = next(e for e in exps if e["experiment_type"] == "RCT")
        obs = next(e for e in exps if e["experiment_type"] == "Observational")

        rct_det = client.get(f"/api/v1/experiments/{rct['campaign_id']}").json()
        assert rct_det["diagnostics"]["is_rct"] is True
        assert rct_det["incremental_summary"]["causal_claim_allowed"] is True
        assert rct_det["incremental_summary"]["incremental_contribution"] is not None
        assert len(rct_det["metrics_table"]) == 5

        obs_det = client.get(f"/api/v1/experiments/{obs['campaign_id']}").json()
        assert obs_det["diagnostics"]["is_rct"] is False
        assert obs_det["incremental_summary"]["causal_claim_allowed"] is False
        assert obs_det["incremental_summary"]["incremental_contribution"] is None
        assert obs_det["diagnostics"]["selection_bias_warning"] is not None
        assert obs_det["diagnostics"]["max_covariate_smd"] > 0.20


def test_economics_customers_compare_simulator():
    with TestClient(app) as client:
        econ = client.get("/api/v1/economics").json()
        s = econ["summary"]
        assert abs((s["gross_revenue"] - s["discount_cost"] - s["variable_cost"] - s["bonus_miles_cost"] - s["other_promo_cost"]) - s["contribution_after_promo"]) < 2.0
        assert len(econ["formulas"]) >= 7

        cust = client.get("/api/v1/customers").json()
        assert cust["total_customers_scored"] >= 50000
        assert len(cust["model_runs"]) == 4
        assert len(cust["archetypes"]) >= 4

        camps = client.get("/api/v1/campaigns").json()["campaigns"]
        cmp_res = client.post("/api/v1/compare", json={"campaign_ids": [camps[0]["campaign_id"], camps[1]["campaign_id"]]}).json()
        assert len(cmp_res["campaigns"]) == 2

        sim = client.post(
            "/api/v1/simulator/run",
            json={
                "budget_multiplier": 1.35,
                "discount_pct": 12.0,
                "bonus_miles_offer": 4000,
                "exclude_sure_things": True,
            },
        ).json()
        assert "NOT A GUARANTEED OUTCOME" in sim["disclaimer"]
        assert sim["simulated"]["spend"] > sim["baseline"]["spend"]
        assert len(sim["discount_frontier"]) == 7


def test_sql_library_and_exports_match_dashboard():
    with TestClient(app) as client:
        sql_list = client.get("/api/v1/sql-analytics/queries").json()["queries"]
        assert len(sql_list) >= 8
        for q in sql_list:
            run_res = client.get(f"/api/v1/sql-analytics/queries/{q['id']}/run").json()
            assert run_res["row_count"] > 0, f"SQL query {q['id']} returned 0 rows"
            assert len(run_res["explain_plan"]) > 0

        # Verify segment & route filters propagate across funnel and economics
        fun_all = client.get("/api/v1/funnel").json()
        fun_seg = client.get("/api/v1/funnel?segment_id=3").json()
        assert 0 < fun_seg["stages"][1]["count"] < fun_all["stages"][1]["count"]

        econ_all = client.get("/api/v1/economics").json()
        econ_route = client.get("/api/v1/economics?route_market_id=21").json()
        assert 0 < econ_route["summary"]["gross_revenue"] < econ_all["summary"]["gross_revenue"]

        # Export consistency check: Report JSON vs PDF & Excel
        exps = client.get("/api/v1/experiments").json()["experiments"]
        rct_id = next(e["campaign_id"] for e in exps if e["experiment_type"] == "RCT")

        rep = client.get(f"/api/v1/reports/campaign/{rct_id}").json()
        exp_det = client.get(f"/api/v1/experiments/{rct_id}").json()
        assert rep["incremental_impact"]["incremental_contribution"] == exp_det["incremental_summary"]["incremental_contribution"]

        pdf_resp = client.get(f"/api/v1/reports/campaign/{rct_id}/pdf")
        assert pdf_resp.status_code == 200
        assert pdf_resp.content.startswith(b"%PDF")

        xlsx_resp = client.get(f"/api/v1/reports/campaign/{rct_id}/excel")
        assert xlsx_resp.status_code == 200
        wb = load_workbook(io.BytesIO(xlsx_resp.content))
        assert "Executive Summary" in wb.sheetnames
        assert "Experiment Statistics" in wb.sheetnames
        assert "Promotion Economics" in wb.sheetnames
        # Verify exact incremental contribution matches dashboard in Excel workbook
        econ_sheet = wb["Promotion Economics"]
        excel_vals = {row[0]: row[1] for row in econ_sheet.iter_rows(values_only=True) if row[0]}
        assert excel_vals["RCT Incremental Contribution"] == exp_det["incremental_summary"]["incremental_contribution"]

        csv_resp = client.get("/api/v1/campaigns/export/csv")
        assert csv_resp.status_code == 200
        assert b"campaign_code,campaign_name" in csv_resp.content

        camp_xlsx = client.get("/api/v1/campaigns/export/excel")
        assert camp_xlsx.status_code == 200
        assert camp_xlsx.content[:2] == b"PK"
