"""Customer Response Analysis, Behavioral Archetypes & Predictive/Uplift Model Service."""
from __future__ import annotations

from typing import Any

from app.db import fetch_all
from app.schemas.analytics import GlobalFilterParams


def get_customer_response_analytics(
    filters: GlobalFilterParams,
    archetype: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    cust_clauses = ["1 = 1"]
    cust_params: dict[str, Any] = {}
    if filters.segment_id is not None:
        cust_clauses.append("cu.segment_id = %(segment_id)s")
        cust_params["segment_id"] = filters.segment_id
    if archetype:
        cust_clauses.append("cps.response_archetype = %(archetype)s")
        cust_params["archetype"] = archetype

    where_cust = " AND ".join(cust_clauses)

    # 1. Six Behavioral Response Archetypes (computed from scored customer population)
    archetype_summary = fetch_all(
        f"""
        SELECT
            cps.response_archetype,
            cps.recommended_incentive,
            COUNT(*) AS customer_count,
            ROUND(AVG(cu.historical_trips_12m)::NUMERIC, 2)::FLOAT8 AS avg_trips_12m,
            ROUND(AVG(cu.historical_spend_12m)::NUMERIC, 2)::FLOAT8 AS avg_spend_12m,
            ROUND(AVG(cu.miles_balance)::NUMERIC, 0)::FLOAT8 AS avg_miles_balance,
            ROUND(AVG(cps.baseline_booking_prob)::NUMERIC, 4)::FLOAT8 AS avg_baseline_prob,
            ROUND(AVG(cps.promo_booking_prob)::NUMERIC, 4)::FLOAT8 AS avg_promo_prob,
            ROUND(AVG(cps.predicted_uplift)::NUMERIC, 4)::FLOAT8 AS avg_predicted_uplift,
            ROUND(AVG(cps.discount_uplift_score)::NUMERIC, 4)::FLOAT8 AS avg_discount_uplift,
            ROUND(AVG(cps.miles_uplift_score)::NUMERIC, 4)::FLOAT8 AS avg_miles_uplift
        FROM customer_propensity_scores cps
        JOIN customers cu ON cu.customer_id = cps.customer_id
        WHERE {where_cust}
        GROUP BY cps.response_archetype, cps.recommended_incentive
        ORDER BY avg_predicted_uplift DESC
        """,
        cust_params,
    )
    total_scored = sum(int(r["customer_count"]) for r in archetype_summary)
    for r in archetype_summary:
        r["share_pct"] = round(int(r["customer_count"]) / total_scored, 4) if total_scored > 0 else 0.0

    # 2. Segment x Incentive Preference Matrix (Fare Discount vs Bonus Miles real RCT uplift!)
    seg_clause = "WHERE cu.segment_id = %(segment_id)s" if filters.segment_id is not None else ""
    segment_incentive_matrix = fetch_all(
        f"""
        SELECT
            cs.segment_id,
            cs.segment_name,
            cs.incentive_affinity,
            COUNT(*) AS customers,
            ROUND(AVG(cps.baseline_booking_prob)::NUMERIC, 4)::FLOAT8 AS baseline_prob,
            ROUND(AVG(cps.discount_uplift_score)::NUMERIC, 4)::FLOAT8 AS discount_uplift,
            ROUND(AVG(cps.miles_uplift_score)::NUMERIC, 4)::FLOAT8 AS miles_uplift,
            ROUND(AVG(cu.historical_spend_12m)::NUMERIC, 2)::FLOAT8 AS avg_spend_12m,
            COUNT(*) FILTER (WHERE cps.response_archetype = 'Sure Things (Baseline Bookers)') AS sure_things_cnt,
            COUNT(*) FILTER (WHERE cps.response_archetype IN ('Discount-Sensitive Responders', 'Loyalty-Incentive Responders', 'Highly Responsive Persuadables')) AS persuadable_cnt
        FROM customers cu
        JOIN customer_segments cs ON cs.segment_id = cu.segment_id
        JOIN customer_propensity_scores cps ON cps.customer_id = cu.customer_id
        {seg_clause}
        GROUP BY cs.segment_id, cs.segment_name, cs.incentive_affinity
        ORDER BY AVG(cps.discount_uplift_score) + AVG(cps.miles_uplift_score) DESC
        """,
        cust_params,
    )

    # 3. Persisted ML Model Runs (Naive vs Linear Baseline vs GBDT vs Causal T-Learner Uplift)
    model_runs = fetch_all(
        """
        SELECT
            run_id,
            run_timestamp::TEXT AS run_timestamp,
            model_name,
            model_role,
            train_period,
            val_period,
            test_period,
            n_train,
            n_val,
            n_test,
            roc_auc,
            roc_auc_ci_low,
            roc_auc_ci_high,
            pr_auc,
            pr_auc_ci_low,
            pr_auc_ci_high,
            brier_score,
            log_loss_val,
            f1_score_val,
            precision_top_20,
            lift_top_decile,
            qini_auc,
            training_seconds,
            confusion_matrix_json AS confusion_matrix,
            calibration_json AS calibration,
            feature_importance_json AS feature_importance,
            slice_metrics_json AS slice_metrics,
            uplift_deciles_json AS uplift_deciles,
            limitations_json AS limitations
        FROM ml_model_runs
        ORDER BY run_id ASC
        """
    )

    # 4. Sample Customer Cohort Records (for drill-down table)
    cohort_params = {**cust_params, "lim": max(10, min(200, limit))}
    customer_samples = fetch_all(
        f"""
        SELECT
            cu.customer_code,
            cs.segment_name,
            cu.loyalty_tier,
            cu.home_airport,
            cu.historical_trips_12m,
            cu.historical_spend_12m::FLOAT8 AS historical_spend_12m,
            cu.miles_balance,
            ROUND(cps.baseline_booking_prob::NUMERIC, 4)::FLOAT8 AS baseline_booking_prob,
            ROUND(cps.predicted_uplift::NUMERIC, 4)::FLOAT8 AS predicted_uplift,
            ROUND(cps.discount_uplift_score::NUMERIC, 4)::FLOAT8 AS discount_uplift_score,
            ROUND(cps.miles_uplift_score::NUMERIC, 4)::FLOAT8 AS miles_uplift_score,
            cps.uplift_decile,
            cps.response_archetype,
            cps.recommended_incentive
        FROM customer_propensity_scores cps
        JOIN customers cu ON cu.customer_id = cps.customer_id
        JOIN customer_segments cs ON cs.segment_id = cu.segment_id
        WHERE {where_cust}
        ORDER BY cps.predicted_uplift DESC
        LIMIT %(lim)s
        """,
        cohort_params,
    )

    return {
        "total_customers_scored": total_scored,
        "archetypes": archetype_summary,
        "segment_incentive_matrix": segment_incentive_matrix,
        "model_runs": model_runs,
        "customer_cohort_sample": customer_samples,
    }
