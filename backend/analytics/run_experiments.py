"""
Batch Experimentation Pipeline: Computes Intention-to-Treat (ITT) statistical
results for all RCT campaigns and selection-bias + IPW sensitivity diagnostics
for all Observational campaigns directly from PostgreSQL source tables, and
persists reproducible results into `experiment_results_store`.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.services.stats_engine import (
    compute_covariate_balance,
    ipw_observational_sensitivity,
    sample_ratio_mismatch_test,
    two_proportion_test,
    welch_t_test,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.experiments")


FETCH_CUSTOMER_OUTCOMES_SQL = """
WITH base_assign AS (
    SELECT
        ca.campaign_id,
        c.experiment_type,
        c.treatment_split_target,
        c.start_date,
        (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS window_end_date,
        ca.assignment_id,
        ca.customer_id,
        ca.assignment_group,
        cu.segment_id,
        cu.loyalty_tier,
        cu.historical_trips_12m,
        cu.historical_spend_12m,
        cu.tenure_months,
        cu.miles_balance,
        CASE WHEN cu.app_active THEN 1.0 ELSE 0.0 END AS app_active_num,
        COALESCE(BOOL_OR(ce.is_reached), FALSE) AS is_reached
    FROM campaign_assignments ca
    JOIN campaigns c ON c.campaign_id = ca.campaign_id
    JOIN customers cu ON cu.customer_id = ca.customer_id
    LEFT JOIN campaign_exposures ce ON ce.assignment_id = ca.assignment_id
    GROUP BY
        ca.campaign_id, c.experiment_type, c.treatment_split_target, c.start_date,
        c.end_date, c.booking_window_days, ca.assignment_id, ca.customer_id,
        ca.assignment_group, cu.segment_id, cu.loyalty_tier, cu.historical_trips_12m,
        cu.historical_spend_12m, cu.tenure_months, cu.miles_balance, cu.app_active
),
promo_miles AS (
    SELECT booking_id, campaign_id, SUM(reward_liability_cost) AS miles_cost
    FROM loyalty_rewards
    WHERE campaign_id IS NOT NULL
    GROUP BY booking_id, campaign_id
)
SELECT
    ba.campaign_id,
    ba.experiment_type,
    ba.treatment_split_target,
    ba.customer_id,
    ba.assignment_group,
    ba.segment_id,
    ba.loyalty_tier,
    ba.historical_trips_12m,
    ba.historical_spend_12m::FLOAT8 AS historical_spend_12m,
    ba.tenure_months,
    ba.miles_balance,
    ba.app_active_num::FLOAT8 AS app_active_num,
    ba.is_reached,
    COUNT(DISTINCT b.booking_id) AS booking_count,
    CASE WHEN COUNT(DISTINCT b.booking_id) > 0 THEN 1 ELSE 0 END AS converted,
    COALESCE(SUM(tr.net_ticket_revenue), 0)::FLOAT8 AS net_revenue,
    COALESCE(SUM(tr.gross_total_revenue), 0)::FLOAT8 AS gross_revenue,
    COALESCE(SUM(tr.discount_amount), 0)::FLOAT8 AS discount_amount,
    COALESCE(SUM(tr.gross_total_revenue - tr.discount_amount - tr.estimated_variable_cost), 0)::FLOAT8
        - COALESCE(SUM(COALESCE(pm.miles_cost, 0)), 0)::FLOAT8 AS net_contribution
FROM base_assign ba
LEFT JOIN bookings b
    ON b.customer_id = ba.customer_id
    AND b.booking_date BETWEEN ba.start_date AND ba.window_end_date
    AND b.booking_status <> 'cancelled'
LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
LEFT JOIN promo_miles pm ON pm.booking_id = b.booking_id AND pm.campaign_id = ba.campaign_id
GROUP BY
    ba.campaign_id, ba.experiment_type, ba.treatment_split_target, ba.customer_id,
    ba.assignment_group, ba.segment_id, ba.loyalty_tier, ba.historical_trips_12m,
    ba.historical_spend_12m, ba.tenure_months, ba.miles_balance, ba.app_active_num,
    ba.is_reached;
"""


def classify_recommendation(
    is_rct: bool,
    srm_passed: bool,
    conv_sig: bool,
    contrib_p: float,
    inc_contrib: float | None,
    inc_bookings: float | None,
    spend: float,
) -> str:
    if not is_rct:
        return "Run Controlled RCT"
    if not srm_passed:
        return "Audit Randomization"
    if inc_contrib is None or inc_bookings is None:
        return "Retest"
    if inc_contrib > 0 and (contrib_p < 0.10 or (conv_sig and inc_contrib > spend * 0.5)):
        return "Scale Budget"
    if inc_contrib < -spend * 0.5 and (contrib_p < 0.10 or inc_bookings <= 0):
        return "Pause / Redesign"
    if conv_sig and inc_bookings > 0 and inc_contrib <= 0:
        return "Reduce Discount / Optimize"
    return "Inconclusive — Retest"


def run_all_experiments() -> int:
    t0 = time.perf_counter()
    logger.info("Fetching customer-level observation-window outcomes across all campaigns...")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(FETCH_CUSTOMER_OUTCOMES_SQL)
            rows = cur.fetchall()
            cur.execute("SELECT campaign_id, COALESCE(SUM(amount_usd), 0)::FLOAT8 AS spend FROM marketing_costs GROUP BY campaign_id")
            spend_map = {r["campaign_id"]: float(r["spend"]) for r in cur.fetchall()}

    df = pd.DataFrame(rows)
    logger.info("Loaded %d assignment-level outcome rows in %.1fs. Running statistical tests...", len(df), time.perf_counter() - t0)

    upsert_sql = """
    INSERT INTO experiment_results_store (
        campaign_id, experiment_type, methodology_version,
        n_treatment, n_control, reached_treatment, exposure_compliance_rate,
        srm_chi2, srm_p_value, srm_passed, max_covariate_smd, covariate_balance_json,
        conversion_control, conversion_treatment, conversion_lift_abs, conversion_lift_rel,
        conversion_z_stat, conversion_p_value, conversion_chi2_stat, conversion_chi2_p_value,
        conversion_ci_low, conversion_ci_high, conversion_power,
        booking_freq_control, booking_freq_treatment, booking_freq_p_value, booking_freq_ci_low, booking_freq_ci_high,
        rev_per_cust_control, rev_per_cust_treatment, rev_per_cust_p_value, rev_per_cust_ci_low, rev_per_cust_ci_high,
        abv_control, abv_treatment, abv_p_value,
        contrib_per_cust_control, contrib_per_cust_treatment, contrib_per_cust_p_value, contrib_per_cust_ci_low, contrib_per_cust_ci_high,
        incremental_bookings, incremental_revenue, incremental_contribution,
        marketing_spend, cost_per_incremental_booking,
        ipw_conversion_lift_abs, ipw_contrib_lift_per_cust,
        is_statistically_significant, recommendation_status, metrics_detail_json
    ) VALUES (
        %(campaign_id)s, %(experiment_type)s, %(methodology_version)s,
        %(n_treatment)s, %(n_control)s, %(reached_treatment)s, %(exposure_compliance_rate)s,
        %(srm_chi2)s, %(srm_p_value)s, %(srm_passed)s, %(max_covariate_smd)s, %(covariate_balance_json)s::jsonb,
        %(conversion_control)s, %(conversion_treatment)s, %(conversion_lift_abs)s, %(conversion_lift_rel)s,
        %(conversion_z_stat)s, %(conversion_p_value)s, %(conversion_chi2_stat)s, %(conversion_chi2_p_value)s,
        %(conversion_ci_low)s, %(conversion_ci_high)s, %(conversion_power)s,
        %(booking_freq_control)s, %(booking_freq_treatment)s, %(booking_freq_p_value)s, %(booking_freq_ci_low)s, %(booking_freq_ci_high)s,
        %(rev_per_cust_control)s, %(rev_per_cust_treatment)s, %(rev_per_cust_p_value)s, %(rev_per_cust_ci_low)s, %(rev_per_cust_ci_high)s,
        %(abv_control)s, %(abv_treatment)s, %(abv_p_value)s,
        %(contrib_per_cust_control)s, %(contrib_per_cust_treatment)s, %(contrib_per_cust_p_value)s, %(contrib_per_cust_ci_low)s, %(contrib_per_cust_ci_high)s,
        %(incremental_bookings)s, %(incremental_revenue)s, %(incremental_contribution)s,
        %(marketing_spend)s, %(cost_per_incremental_booking)s,
        %(ipw_conversion_lift_abs)s, %(ipw_contrib_lift_per_cust)s,
        %(is_statistically_significant)s, %(recommendation_status)s, %(metrics_detail_json)s::jsonb
    )
    ON CONFLICT (campaign_id) DO UPDATE SET
        computed_at = NOW(),
        n_treatment = EXCLUDED.n_treatment,
        n_control = EXCLUDED.n_control,
        reached_treatment = EXCLUDED.reached_treatment,
        exposure_compliance_rate = EXCLUDED.exposure_compliance_rate,
        srm_chi2 = EXCLUDED.srm_chi2,
        srm_p_value = EXCLUDED.srm_p_value,
        srm_passed = EXCLUDED.srm_passed,
        max_covariate_smd = EXCLUDED.max_covariate_smd,
        covariate_balance_json = EXCLUDED.covariate_balance_json,
        conversion_control = EXCLUDED.conversion_control,
        conversion_treatment = EXCLUDED.conversion_treatment,
        conversion_lift_abs = EXCLUDED.conversion_lift_abs,
        conversion_lift_rel = EXCLUDED.conversion_lift_rel,
        conversion_z_stat = EXCLUDED.conversion_z_stat,
        conversion_p_value = EXCLUDED.conversion_p_value,
        conversion_chi2_stat = EXCLUDED.conversion_chi2_stat,
        conversion_chi2_p_value = EXCLUDED.conversion_chi2_p_value,
        conversion_ci_low = EXCLUDED.conversion_ci_low,
        conversion_ci_high = EXCLUDED.conversion_ci_high,
        conversion_power = EXCLUDED.conversion_power,
        booking_freq_control = EXCLUDED.booking_freq_control,
        booking_freq_treatment = EXCLUDED.booking_freq_treatment,
        booking_freq_p_value = EXCLUDED.booking_freq_p_value,
        booking_freq_ci_low = EXCLUDED.booking_freq_ci_low,
        booking_freq_ci_high = EXCLUDED.booking_freq_ci_high,
        rev_per_cust_control = EXCLUDED.rev_per_cust_control,
        rev_per_cust_treatment = EXCLUDED.rev_per_cust_treatment,
        rev_per_cust_p_value = EXCLUDED.rev_per_cust_p_value,
        rev_per_cust_ci_low = EXCLUDED.rev_per_cust_ci_low,
        rev_per_cust_ci_high = EXCLUDED.rev_per_cust_ci_high,
        abv_control = EXCLUDED.abv_control,
        abv_treatment = EXCLUDED.abv_treatment,
        abv_p_value = EXCLUDED.abv_p_value,
        contrib_per_cust_control = EXCLUDED.contrib_per_cust_control,
        contrib_per_cust_treatment = EXCLUDED.contrib_per_cust_treatment,
        contrib_per_cust_p_value = EXCLUDED.contrib_per_cust_p_value,
        contrib_per_cust_ci_low = EXCLUDED.contrib_per_cust_ci_low,
        contrib_per_cust_ci_high = EXCLUDED.contrib_per_cust_ci_high,
        incremental_bookings = EXCLUDED.incremental_bookings,
        incremental_revenue = EXCLUDED.incremental_revenue,
        incremental_contribution = EXCLUDED.incremental_contribution,
        marketing_spend = EXCLUDED.marketing_spend,
        cost_per_incremental_booking = EXCLUDED.cost_per_incremental_booking,
        ipw_conversion_lift_abs = EXCLUDED.ipw_conversion_lift_abs,
        ipw_contrib_lift_per_cust = EXCLUDED.ipw_contrib_lift_per_cust,
        is_statistically_significant = EXCLUDED.is_statistically_significant,
        recommendation_status = EXCLUDED.recommendation_status,
        metrics_detail_json = EXCLUDED.metrics_detail_json;
    """

    records: list[dict[str, Any]] = []
    for camp_id, grp_df in df.groupby("campaign_id"):
        cid = int(camp_id)
        exp_type = str(grp_df["experiment_type"].iloc[0])
        is_rct = exp_type == "RCT"
        treat_lbl = "treatment" if is_rct else "observational_targeted"
        ctrl_lbl = "control" if is_rct else "observational_comparison"

        t_df = grp_df[grp_df["assignment_group"] == treat_lbl]
        c_df = grp_df[grp_df["assignment_group"] == ctrl_lbl]

        n_t = int(len(t_df))
        n_c = int(len(c_df))
        reached_t = int(t_df["is_reached"].sum())
        compliance = (reached_t / n_t) if n_t > 0 else 0.0
        spend = float(spend_map.get(cid, 0.0))

        # SRM check (only meaningful for RCTs)
        if is_rct:
            expected_split = float(grp_df["treatment_split_target"].iloc[0] or 0.5)
            srm = sample_ratio_mismatch_test(n_t, n_c, expected_split)
        else:
            srm = {"chi2": None, "p_value": None, "passed": None}

        # Covariate balance
        cov_rows, max_smd = compute_covariate_balance(grp_df, "assignment_group", treat_lbl, ctrl_lbl)

        # Core statistical tests
        conv_res = two_proportion_test(int(t_df["converted"].sum()), n_t, int(c_df["converted"].sum()), n_c)
        freq_res = welch_t_test(t_df["booking_count"].to_numpy(), c_df["booking_count"].to_numpy())
        rev_res = welch_t_test(t_df["net_revenue"].to_numpy(), c_df["net_revenue"].to_numpy())
        contrib_res = welch_t_test(t_df["net_contribution"].to_numpy(), c_df["net_contribution"].to_numpy())

        # Conditional Average Booking Value (ABV among bookers only — caveated for selection)
        t_bookers = t_df[t_df["booking_count"] > 0]
        c_bookers = c_df[c_df["booking_count"] > 0]
        t_abv_arr = (t_bookers["net_revenue"] / t_bookers["booking_count"]).to_numpy()
        c_abv_arr = (c_bookers["net_revenue"] / c_bookers["booking_count"]).to_numpy()
        abv_res = welch_t_test(t_abv_arr, c_abv_arr)

        # Causal incremental totals ONLY computed as causal claims for RCTs!
        # Observational campaigns leave causal incremental columns NULL to prevent
        # confusing biased attribution with causal incremental lift.
        if is_rct:
            inc_bookings = round(freq_res["lift_abs"] * n_t, 2)
            inc_revenue = round(rev_res["lift_abs"] * n_t, 2)
            inc_contrib = round((contrib_res["lift_abs"] * n_t) - spend, 2)
            icpa = round(spend / inc_bookings, 2) if inc_bookings > 1.0 else None
            ipw_res = {"ipw_conversion_lift_abs": None, "ipw_contrib_lift_per_cust": None, "overlap_pct": None}
            is_sig = bool(conv_res["significant"])
        else:
            inc_bookings = None
            inc_revenue = None
            inc_contrib = None
            icpa = None
            ipw_res = ipw_observational_sensitivity(grp_df)
            is_sig = False  # Do not badge observational selection bias as causal significance

        rec = classify_recommendation(
            is_rct=is_rct,
            srm_passed=bool(srm["passed"]) if is_rct else False,
            conv_sig=bool(conv_res["significant"]),
            contrib_p=float(contrib_res["p_value"]),
            inc_contrib=inc_contrib,
            inc_bookings=inc_bookings,
            spend=spend,
        )

        metrics_detail = {
            "conversion": conv_res,
            "booking_frequency": freq_res,
            "revenue_per_customer": rev_res,
            "avg_booking_value": abv_res,
            "contribution_per_customer": contrib_res,
            "ipw_sensitivity": ipw_res,
            "cace_approx_conv_lift": round(conv_res["lift_abs"] / compliance, 6) if (is_rct and compliance > 0.1) else None,
        }

        records.append({
            "campaign_id": cid,
            "experiment_type": exp_type,
            "methodology_version": "itt-v1.0" if is_rct else "observational-audit-v1.0",
            "n_treatment": n_t,
            "n_control": n_c,
            "reached_treatment": reached_t,
            "exposure_compliance_rate": round(compliance, 4),
            "srm_chi2": round(srm["chi2"], 4) if srm["chi2"] is not None else None,
            "srm_p_value": srm["p_value"],
            "srm_passed": srm["passed"],
            "max_covariate_smd": max_smd,
            "covariate_balance_json": json.dumps(cov_rows),
            "conversion_control": round(conv_res["control_rate"], 6),
            "conversion_treatment": round(conv_res["treatment_rate"], 6),
            "conversion_lift_abs": round(conv_res["lift_abs"], 6),
            "conversion_lift_rel": round(conv_res["lift_rel"], 4) if conv_res["lift_rel"] is not None else None,
            "conversion_z_stat": round(conv_res["z_stat"], 4),
            "conversion_p_value": conv_res["p_value"],
            "conversion_chi2_stat": round(conv_res["chi2_stat"], 4),
            "conversion_chi2_p_value": conv_res["chi2_p_value"],
            "conversion_ci_low": round(conv_res["ci_low"], 6),
            "conversion_ci_high": round(conv_res["ci_high"], 6),
            "conversion_power": round(conv_res["power"], 4),
            "booking_freq_control": round(freq_res["control_mean"], 6),
            "booking_freq_treatment": round(freq_res["treatment_mean"], 6),
            "booking_freq_p_value": freq_res["p_value"],
            "booking_freq_ci_low": round(freq_res["ci_low"], 6),
            "booking_freq_ci_high": round(freq_res["ci_high"], 6),
            "rev_per_cust_control": round(rev_res["control_mean"], 4),
            "rev_per_cust_treatment": round(rev_res["treatment_mean"], 4),
            "rev_per_cust_p_value": rev_res["p_value"],
            "rev_per_cust_ci_low": round(rev_res["ci_low"], 4),
            "rev_per_cust_ci_high": round(rev_res["ci_high"], 4),
            "abv_control": round(abv_res["control_mean"], 4) if len(c_abv_arr) else None,
            "abv_treatment": round(abv_res["treatment_mean"], 4) if len(t_abv_arr) else None,
            "abv_p_value": abv_res["p_value"] if (len(c_abv_arr) >= 2 and len(t_abv_arr) >= 2) else None,
            "contrib_per_cust_control": round(contrib_res["control_mean"], 4),
            "contrib_per_cust_treatment": round(contrib_res["treatment_mean"], 4),
            "contrib_per_cust_p_value": contrib_res["p_value"],
            "contrib_per_cust_ci_low": round(contrib_res["ci_low"], 4),
            "contrib_per_cust_ci_high": round(contrib_res["ci_high"], 4),
            "incremental_bookings": inc_bookings,
            "incremental_revenue": inc_revenue,
            "incremental_contribution": inc_contrib,
            "marketing_spend": round(spend, 2),
            "cost_per_incremental_booking": icpa,
            "ipw_conversion_lift_abs": ipw_res["ipw_conversion_lift_abs"],
            "ipw_contrib_lift_per_cust": ipw_res["ipw_contrib_lift_per_cust"],
            "is_statistically_significant": is_sig,
            "recommendation_status": rec,
            "metrics_detail_json": json.dumps(metrics_detail),
        })

    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            for rec in records:
                cur.execute(upsert_sql, rec)
        conn.commit()

    rct_recs = [r for r in records if r["experiment_type"] == "RCT"]
    sig_rct = sum(1 for r in rct_recs if r["is_statistically_significant"])
    pos_contrib = sum(1 for r in rct_recs if (r["incremental_contribution"] or 0) > 0)
    neg_contrib = sum(1 for r in rct_recs if (r["incremental_contribution"] or 0) < 0)
    srm_pass = sum(1 for r in rct_recs if r["srm_passed"])
    logger.info(
        "Persisted %d experiment results in %.1fs. RCT=%d (SRM pass=%d, Conv Sig=%d, +IncContrib=%d, -IncContrib=%d), Observational=%d",
        len(records),
        time.perf_counter() - t0,
        len(rct_recs),
        srm_pass,
        sig_rct,
        pos_contrib,
        neg_contrib,
        len(records) - len(rct_recs),
    )
    return len(records)


if __name__ == "__main__":
    run_all_experiments()
