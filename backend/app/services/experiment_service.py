"""Experimentation Lab Service: RCT ITT analysis, HTE subgroup CIs, Observational bias audit, and Power Calculator."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.db import fetch_all, fetch_one
from app.schemas.analytics import GlobalFilterParams, SampleSizeRequest
from app.services.filters import build_summary_where
from app.services.stats_engine import estimate_sample_size, two_proportion_test, welch_t_test


TEST_RATIONALES = {
    "conversion_rate": {
        "primary_test": "Two-Proportion z-test & Pearson Chi-Square Test",
        "rationale": "Conversion is a binary outcome (booked >= 1 vs. 0) per randomized customer. The two-proportion z-test provides directional lift and Wald 95% CI, while Pearson's chi-square independently verifies contingency table independence.",
    },
    "booking_frequency": {
        "primary_test": "Welch's Two-Sample t-test (unequal variances)",
        "rationale": "Booking frequency per assigned customer is a zero-inflated discrete count whose variance often increases in the treatment arm. Welch's t-test avoids homoscedasticity assumptions and is asymptotically exact under CLT for large samples.",
    },
    "revenue_per_customer": {
        "primary_test": "Welch's Two-Sample t-test (ITT across all assigned customers)",
        "rationale": "Net ticket revenue per assigned customer combines conversion probability and order size in one unbiased Intention-to-Treat continuous metric without post-treatment selection bias. Welch's t-test accounts for right-skewed unequal variances.",
    },
    "average_booking_value": {
        "primary_test": "Welch's Two-Sample t-test (Conditional on Bookers — Caveated)",
        "rationale": "Average Booking Value (ABV) conditions on booking (a post-treatment outcome). Discounts can shift mix toward smaller leisure itineraries, so ABV differences must be interpreted alongside unconditional revenue per assigned customer.",
    },
    "contribution_per_customer": {
        "primary_test": "Welch's Two-Sample t-test (Net of Discounts, Variable Costs & Miles)",
        "rationale": "Contribution margin per assigned customer is the primary commercial profitability metric. Testing per assigned customer preserves randomization validity and directly reveals whether incremental demand outweighs discount cannibalization.",
    },
}


def list_experiments(filters: GlobalFilterParams) -> dict[str, Any]:
    where_sql, params = build_summary_where(filters, alias="v")
    rows = fetch_all(
        f"""
        SELECT
            v.campaign_id,
            v.campaign_code,
            v.campaign_name,
            v.campaign_type,
            v.experiment_type,
            v.channel_name,
            v.target_segment_name,
            v.start_date::TEXT AS start_date,
            v.end_date::TEXT AS end_date,
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            ers.n_treatment,
            ers.n_control,
            ers.exposure_compliance_rate::FLOAT8 AS exposure_compliance_rate,
            ers.srm_passed,
            ers.srm_p_value,
            ers.max_covariate_smd::FLOAT8 AS max_covariate_smd,
            ers.conversion_control::FLOAT8 AS conversion_control,
            ers.conversion_treatment::FLOAT8 AS conversion_treatment,
            ers.conversion_lift_abs::FLOAT8 AS conversion_lift_abs,
            ers.conversion_p_value,
            ers.contrib_per_cust_control::FLOAT8 AS contrib_per_cust_control,
            ers.contrib_per_cust_treatment::FLOAT8 AS contrib_per_cust_treatment,
            ers.contrib_per_cust_p_value,
            ers.incremental_bookings::FLOAT8 AS incremental_bookings,
            ers.incremental_contribution::FLOAT8 AS incremental_contribution,
            ers.marketing_spend::FLOAT8 AS marketing_spend,
            ers.is_statistically_significant,
            ers.recommendation_status
        FROM v_campaign_commercial_summary v
        JOIN experiment_results_store ers ON ers.campaign_id = v.campaign_id
        WHERE {where_sql}
        ORDER BY
            CASE WHEN v.experiment_type = 'RCT' THEN 0 ELSE 1 END,
            v.start_date DESC
        """,
        params,
    )
    rct_count = sum(1 for r in rows if r["experiment_type"] == "RCT")
    obs_count = len(rows) - rct_count
    srm_pass_count = sum(1 for r in rows if r["experiment_type"] == "RCT" and r["srm_passed"])
    sig_count = sum(1 for r in rows if r["is_statistically_significant"])

    return {
        "summary": {
            "total": len(rows),
            "rct_count": rct_count,
            "observational_count": obs_count,
            "srm_passed_count": srm_pass_count,
            "statistically_significant_count": sig_count,
        },
        "experiments": rows,
    }


def get_experiment_detail(campaign_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT
            v.campaign_id,
            v.campaign_code,
            v.campaign_name,
            v.campaign_type,
            v.experiment_type,
            v.channel_name,
            v.target_segment_name,
            v.target_route_code,
            v.start_date::TEXT AS start_date,
            v.end_date::TEXT AS end_date,
            v.booking_window_days,
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            c.hypothesis,
            c.eligibility_criteria,
            c.treatment_split_target::FLOAT8 AS treatment_split_target,
            ers.*
        FROM v_campaign_commercial_summary v
        JOIN campaigns c ON c.campaign_id = v.campaign_id
        JOIN experiment_results_store ers ON ers.campaign_id = v.campaign_id
        WHERE v.campaign_id = %s
        """,
        (campaign_id,),
    )
    if not row:
        return None

    is_rct = row["experiment_type"] == "RCT"
    detail_json = row["metrics_detail_json"] or {}
    conv = detail_json.get("conversion", {})
    freq = detail_json.get("booking_frequency", {})
    rev = detail_json.get("revenue_per_customer", {})
    abv = detail_json.get("avg_booking_value", {})
    contrib = detail_json.get("contribution_per_customer", {})
    ipw = detail_json.get("ipw_sensitivity", {})

    metrics_table = [
        {
            "metric_key": "conversion_rate",
            "metric_name": "Conversion Rate (Booked >= 1)",
            "unit": "percent",
            "is_conditional": False,
            "control_value": conv.get("control_rate", float(row["conversion_control"])),
            "treatment_value": conv.get("treatment_rate", float(row["conversion_treatment"])),
            "lift_abs": conv.get("lift_abs", float(row["conversion_lift_abs"])),
            "lift_rel": conv.get("lift_rel"),
            "ci_low": conv.get("ci_low"),
            "ci_high": conv.get("ci_high"),
            "test_stat": conv.get("z_stat"),
            "test_stat_label": "z",
            "secondary_stat": conv.get("chi2_stat"),
            "secondary_stat_label": "chi2",
            "secondary_p_value": conv.get("chi2_p_value"),
            "p_value": conv.get("p_value"),
            "power": conv.get("power"),
            "significant": bool(conv.get("significant")) if is_rct else False,
            **TEST_RATIONALES["conversion_rate"],
        },
        {
            "metric_key": "booking_frequency",
            "metric_name": "Booking Frequency per Customer",
            "unit": "count",
            "is_conditional": False,
            "control_value": freq.get("control_mean", float(row["booking_freq_control"])),
            "treatment_value": freq.get("treatment_mean", float(row["booking_freq_treatment"])),
            "lift_abs": freq.get("lift_abs"),
            "lift_rel": freq.get("lift_rel"),
            "ci_low": freq.get("ci_low"),
            "ci_high": freq.get("ci_high"),
            "test_stat": freq.get("t_stat"),
            "test_stat_label": "Welch t",
            "p_value": freq.get("p_value"),
            "power": freq.get("power"),
            "significant": bool(freq.get("significant")) if is_rct else False,
            **TEST_RATIONALES["booking_frequency"],
        },
        {
            "metric_key": "revenue_per_customer",
            "metric_name": "Net Revenue per Assigned Customer",
            "unit": "currency",
            "is_conditional": False,
            "control_value": rev.get("control_mean", float(row["rev_per_cust_control"])),
            "treatment_value": rev.get("treatment_mean", float(row["rev_per_cust_treatment"])),
            "lift_abs": rev.get("lift_abs"),
            "lift_rel": rev.get("lift_rel"),
            "ci_low": rev.get("ci_low"),
            "ci_high": rev.get("ci_high"),
            "test_stat": rev.get("t_stat"),
            "test_stat_label": "Welch t",
            "p_value": rev.get("p_value"),
            "power": rev.get("power"),
            "significant": bool(rev.get("significant")) if is_rct else False,
            **TEST_RATIONALES["revenue_per_customer"],
        },
        {
            "metric_key": "average_booking_value",
            "metric_name": "Average Booking Value (Bookers Only)",
            "unit": "currency",
            "is_conditional": True,
            "control_value": abv.get("control_mean"),
            "treatment_value": abv.get("treatment_mean"),
            "lift_abs": abv.get("lift_abs"),
            "lift_rel": abv.get("lift_rel"),
            "ci_low": abv.get("ci_low"),
            "ci_high": abv.get("ci_high"),
            "test_stat": abv.get("t_stat"),
            "test_stat_label": "Welch t",
            "p_value": abv.get("p_value"),
            "power": abv.get("power"),
            "significant": bool(abv.get("significant")) if is_rct else False,
            **TEST_RATIONALES["average_booking_value"],
        },
        {
            "metric_key": "contribution_per_customer",
            "metric_name": "Contribution Margin per Assigned Customer",
            "unit": "currency",
            "is_conditional": False,
            "control_value": contrib.get("control_mean", float(row["contrib_per_cust_control"])),
            "treatment_value": contrib.get("treatment_mean", float(row["contrib_per_cust_treatment"])),
            "lift_abs": contrib.get("lift_abs"),
            "lift_rel": contrib.get("lift_rel"),
            "ci_low": contrib.get("ci_low"),
            "ci_high": contrib.get("ci_high"),
            "test_stat": contrib.get("t_stat"),
            "test_stat_label": "Welch t",
            "p_value": contrib.get("p_value"),
            "power": contrib.get("power"),
            "significant": bool(contrib.get("significant")) if is_rct else False,
            **TEST_RATIONALES["contribution_per_customer"],
        },
    ]

    # Compute subgroup Heterogeneous Treatment Effects (HTE) by customer segment live from PostgreSQL
    treat_lbl = "treatment" if is_rct else "observational_targeted"
    ctrl_lbl = "control" if is_rct else "observational_comparison"

    sub_rows = fetch_all(
        """
        WITH assign_c AS (
            SELECT
                ca.customer_id,
                ca.assignment_group,
                cs.segment_name,
                c.start_date,
                (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS win_end
            FROM campaign_assignments ca
            JOIN campaigns c ON c.campaign_id = ca.campaign_id
            JOIN customers cu ON cu.customer_id = ca.customer_id
            JOIN customer_segments cs ON cs.segment_id = cu.segment_id
            WHERE ca.campaign_id = %s
        ),
        pm AS (
            SELECT booking_id, SUM(reward_liability_cost) AS miles_cost
            FROM loyalty_rewards
            WHERE campaign_id = %s
            GROUP BY booking_id
        )
        SELECT
            ac.segment_name,
            ac.assignment_group,
            CASE WHEN COUNT(DISTINCT b.booking_id) > 0 THEN 1 ELSE 0 END AS converted,
            COALESCE(SUM(tr.gross_total_revenue - tr.discount_amount - tr.estimated_variable_cost), 0)::FLOAT8
                - COALESCE(SUM(COALESCE(pm.miles_cost, 0)), 0)::FLOAT8 AS net_contribution
        FROM assign_c ac
        LEFT JOIN bookings b
            ON b.customer_id = ac.customer_id
            AND b.booking_date BETWEEN ac.start_date AND ac.win_end
            AND b.booking_status <> 'cancelled'
        LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
        LEFT JOIN pm ON pm.booking_id = b.booking_id
        GROUP BY ac.customer_id, ac.segment_name, ac.assignment_group
        """,
        (campaign_id, campaign_id),
    )

    hte_segments: list[dict[str, Any]] = []
    if sub_rows:
        sdf = pd.DataFrame(sub_rows)
        for seg_name, gdf in sdf.groupby("segment_name"):
            t_s = gdf[gdf["assignment_group"] == treat_lbl]
            c_s = gdf[gdf["assignment_group"] == ctrl_lbl]
            if len(t_s) < 25 or len(c_s) < 25:
                continue
            cr = two_proportion_test(int(t_s["converted"].sum()), len(t_s), int(c_s["converted"].sum()), len(c_s))
            mr = welch_t_test(t_s["net_contribution"].to_numpy(), c_s["net_contribution"].to_numpy())
            hte_segments.append({
                "segment_name": str(seg_name),
                "n_treatment": int(len(t_s)),
                "n_control": int(len(c_s)),
                "control_conv": round(cr["control_rate"], 4),
                "treatment_conv": round(cr["treatment_rate"], 4),
                "conv_lift_pp": round(cr["lift_abs"] * 100.0, 2),
                "conv_ci_low_pp": round(cr["ci_low"] * 100.0, 2),
                "conv_ci_high_pp": round(cr["ci_high"] * 100.0, 2),
                "conv_p_value": round(cr["p_value"], 4),
                "contrib_lift_per_cust": round(mr["lift_abs"], 2),
                "contrib_ci_low": round(mr["ci_low"], 2),
                "contrib_ci_high": round(mr["ci_high"], 2),
                "contrib_p_value": round(mr["p_value"], 4),
            })

    return {
        "campaign": {
            "campaign_id": int(row["campaign_id"]),
            "campaign_code": row["campaign_code"],
            "campaign_name": row["campaign_name"],
            "campaign_type": row["campaign_type"],
            "experiment_type": row["experiment_type"],
            "channel_name": row["channel_name"],
            "target_segment_name": row["target_segment_name"],
            "target_route_code": row["target_route_code"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "booking_window_days": int(row["booking_window_days"]),
            "discount_pct": float(row["discount_pct"]),
            "bonus_miles_offer": int(row["bonus_miles_offer"]),
            "hypothesis": row["hypothesis"],
            "eligibility_criteria": row["eligibility_criteria"],
            "treatment_split_target": float(row["treatment_split_target"]) if row["treatment_split_target"] is not None else None,
        },
        "diagnostics": {
            "is_rct": is_rct,
            "methodology": "Intention-to-Treat (ITT) across all randomized assignments" if is_rct else "Non-Randomized Observational Comparison (Confounded — Selection Bias Present)",
            "n_treatment": int(row["n_treatment"]),
            "n_control": int(row["n_control"]),
            "reached_treatment": int(row["reached_treatment"]),
            "exposure_compliance_rate": float(row["exposure_compliance_rate"]),
            "cace_approx_conv_lift": detail_json.get("cace_approx_conv_lift"),
            "srm_chi2": float(row["srm_chi2"]) if row["srm_chi2"] is not None else None,
            "srm_p_value": row["srm_p_value"],
            "srm_passed": row["srm_passed"],
            "max_covariate_smd": float(row["max_covariate_smd"]) if row["max_covariate_smd"] is not None else None,
            "covariate_balance": row["covariate_balance_json"] or [],
            "selection_bias_warning": None if is_rct else (
                f"Selection bias detected (max pre-period |SMD| = {float(row['max_covariate_smd'] or 0):.2f} > 0.20). "
                "Targeted customers had systematically higher historical travel activity and app engagement than the untargeted pool. "
                "Naive differences reflect targeting bias, NOT causal incremental lift. Use IPW sensitivity strictly as a directional bound and run a randomized holdout test before scaling budget."
            ),
            "ipw_sensitivity": ipw if not is_rct else None,
        },
        "incremental_summary": {
            "causal_claim_allowed": is_rct,
            "marketing_spend": float(row["marketing_spend"]),
            "incremental_bookings": float(row["incremental_bookings"]) if row["incremental_bookings"] is not None else None,
            "incremental_revenue": float(row["incremental_revenue"]) if row["incremental_revenue"] is not None else None,
            "incremental_contribution": float(row["incremental_contribution"]) if row["incremental_contribution"] is not None else None,
            "cost_per_incremental_booking": float(row["cost_per_incremental_booking"]) if row["cost_per_incremental_booking"] is not None else None,
            "recommendation_status": row["recommendation_status"],
        },
        "metrics_table": metrics_table,
        "subgroup_hte": hte_segments,
    }


def calculate_sample_size_service(req: SampleSizeRequest) -> dict[str, Any]:
    return estimate_sample_size(
        baseline_rate=req.baseline_rate,
        mde_abs=req.mde_abs,
        alpha=req.alpha,
        power=req.power,
        treatment_split=req.treatment_split,
    )
