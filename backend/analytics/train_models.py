"""
Reproducible Customer Response & Causal Uplift Modeling Pipeline.

Follows strict ML best practices:
1. Chronological train / validation / test split by campaign start_date (zero temporal leakage).
2. Strict pre-campaign feature set ONLY (zero post-exposure, click, or redemption leakage).
3. Preprocessing (OrdinalEncoder + OneHotEncoder + StandardScaler) fitted STRICTLY on training fold.
4. Compares Naive Baseline, Regularized Logistic Regression Baseline, HistGradientBoostingClassifier,
   and a Causal T-Learner Uplift model trained exclusively on RCT assignments.
5. Calculates bootstrap 95% confidence intervals, calibration curves, confusion matrices,
   permutation feature importances, segment slice error metrics, and Qini / uplift deciles
   from real out-of-sample test predictions.
6. Persists run metadata in `ml_model_runs` and customer archetype/uplift scores in
   `customer_propensity_scores`.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.rows import dict_row
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.ml")

FEATURE_SQL = """
WITH assign_base AS (
    SELECT
        ca.assignment_id,
        ca.campaign_id,
        ca.customer_id,
        ca.assignment_group,
        c.experiment_type,
        c.campaign_type,
        c.start_date,
        (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS window_end_date,
        c.discount_pct::FLOAT8 AS discount_pct,
        c.bonus_miles_offer,
        ch.channel_name,
        COALESCE(rm.haul_type, 'Network') AS target_haul_type,
        cal.travel_season,
        cu.segment_id,
        cs.segment_name,
        cu.loyalty_tier,
        cu.region,
        cu.age_band,
        cu.tenure_months,
        cu.historical_trips_12m,
        cu.historical_spend_12m::FLOAT8 AS historical_spend_12m,
        cu.miles_balance,
        CASE WHEN cu.email_opt_in THEN 1 ELSE 0 END AS email_opt_in,
        CASE WHEN cu.push_opt_in THEN 1 ELSE 0 END AS push_opt_in,
        CASE WHEN cu.app_active THEN 1 ELSE 0 END AS app_active
    FROM campaign_assignments ca
    JOIN campaigns c ON c.campaign_id = ca.campaign_id
    JOIN campaign_channels ch ON ch.channel_id = ca.channel_id
    JOIN calendar_dimension cal ON cal.calendar_date = c.start_date
    JOIN customers cu ON cu.customer_id = ca.customer_id
    JOIN customer_segments cs ON cs.segment_id = cu.segment_id
    LEFT JOIN route_markets rm ON rm.route_market_id = c.target_route_market_id
    WHERE c.experiment_type = 'RCT'
      AND ca.assignment_group IN ('treatment', 'control')
)
SELECT
    ab.*,
    CASE WHEN EXISTS (
        SELECT 1
        FROM bookings b
        WHERE b.customer_id = ab.customer_id
          AND b.booking_date BETWEEN ab.start_date AND ab.window_end_date
          AND b.booking_status <> 'cancelled'
    ) THEN 1 ELSE 0 END AS booked_in_window
FROM assign_base ab;
"""

ALL_CUSTOMERS_SQL = """
SELECT
    cu.customer_id,
    cu.segment_id,
    cs.segment_name,
    cu.loyalty_tier,
    cu.region,
    cu.age_band,
    cu.tenure_months,
    cu.historical_trips_12m,
    cu.historical_spend_12m::FLOAT8 AS historical_spend_12m,
    cu.miles_balance,
    CASE WHEN cu.email_opt_in THEN 1 ELSE 0 END AS email_opt_in,
    CASE WHEN cu.push_opt_in THEN 1 ELSE 0 END AS push_opt_in,
    CASE WHEN cu.app_active THEN 1 ELSE 0 END AS app_active
FROM customers cu
JOIN customer_segments cs ON cs.segment_id = cu.segment_id
ORDER BY cu.customer_id;
"""

NUM_FEATURES = [
    "tenure_months",
    "historical_trips_12m",
    "historical_spend_12m",
    "miles_balance",
    "email_opt_in",
    "push_opt_in",
    "app_active",
    "discount_pct",
    "bonus_miles_offer",
]
ORD_FEATURES = ["loyalty_tier", "age_band"]
ORD_CATEGORIES = [
    ["None", "Silver", "Gold", "Platinum", "Executive"],
    ["18-29", "30-44", "45-59", "60+"],
]
CAT_FEATURES = ["segment_name", "region", "campaign_type", "channel_name", "target_haul_type", "travel_season"]
ALL_FEATURES = NUM_FEATURES + ORD_FEATURES + CAT_FEATURES


def build_preprocessor(dense_output: bool = False) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUM_FEATURES),
            ("ord", OrdinalEncoder(categories=ORD_CATEGORIES, handle_unknown="use_encoded_value", unknown_value=-1), ORD_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=not dense_output), CAT_FEATURES),
        ],
        remainder="drop",
    )


def bootstrap_metric_ci(y_true: np.ndarray, y_prob: np.ndarray, metric_fn, n_boot: int = 160, seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(y_true)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        yt = y_true[idx]
        if len(np.unique(yt)) < 2:
            continue
        vals.append(float(metric_fn(yt, y_prob[idx])))
    if not vals:
        return 0.0, 0.0
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def evaluate_classifier(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    seg_series: pd.Series,
    optimal_threshold: float,
) -> dict[str, Any]:
    y_prob_clip = np.clip(y_prob, 1e-6, 1.0 - 1e-6)
    roc = float(roc_auc_score(y_true, y_prob_clip))
    pr = float(average_precision_score(y_true, y_prob_clip))
    brier = float(brier_score_loss(y_true, y_prob_clip))
    ll = float(log_loss(y_true, y_prob_clip))
    roc_lo, roc_hi = bootstrap_metric_ci(y_true, y_prob_clip, roc_auc_score)
    pr_lo, pr_hi = bootstrap_metric_ci(y_true, y_prob_clip, average_precision_score)

    y_pred = (y_prob_clip >= optimal_threshold).astype(int)
    f1 = float(f1_score(y_true, y_pred, zero_division=0))
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    # Top-20% precision & Top-Decile Lift
    order = np.argsort(-y_prob_clip)
    k20 = max(1, int(len(y_true) * 0.20))
    k10 = max(1, int(len(y_true) * 0.10))
    prec_top20 = float(y_true[order[:k20]].mean())
    base_rate = float(y_true.mean())
    lift_top10 = float(y_true[order[:k10]].mean() / base_rate) if base_rate > 0 else 1.0

    # Calibration bins
    prob_true, prob_pred = calibration_curve(y_true, y_prob_clip, n_bins=10, strategy="quantile")
    calib_bins = [
        {"bin": idx + 1, "mean_predicted": round(float(pp), 4), "observed_rate": round(float(pt), 4)}
        for idx, (pt, pp) in enumerate(zip(prob_true, prob_pred))
    ]

    # Slice metrics by customer segment
    slice_rows = []
    for seg_name in sorted(seg_series.unique()):
        mask = (seg_series == seg_name).to_numpy()
        yt_s = y_true[mask]
        yp_s = y_prob_clip[mask]
        if len(yt_s) < 30 or len(np.unique(yt_s)) < 2:
            continue
        slice_rows.append({
            "segment": str(seg_name),
            "n_test": int(len(yt_s)),
            "actual_rate": round(float(yt_s.mean()), 4),
            "predicted_rate": round(float(yp_s.mean()), 4),
            "roc_auc": round(float(roc_auc_score(yt_s, yp_s)), 4),
            "pr_auc": round(float(average_precision_score(yt_s, yp_s)), 4),
            "brier": round(float(brier_score_loss(yt_s, yp_s)), 4),
        })

    return {
        "roc_auc": round(roc, 4),
        "roc_auc_ci_low": round(roc_lo, 4),
        "roc_auc_ci_high": round(roc_hi, 4),
        "pr_auc": round(pr, 4),
        "pr_auc_ci_low": round(pr_lo, 4),
        "pr_auc_ci_high": round(pr_hi, 4),
        "brier_score": round(brier, 4),
        "log_loss_val": round(ll, 4),
        "f1_score_val": round(f1, 4),
        "precision_top_20": round(prec_top20, 4),
        "lift_top_decile": round(lift_top10, 3),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp), "threshold": round(optimal_threshold, 4)},
        "calibration": calib_bins,
        "slice_metrics": slice_rows,
    }


def compute_uplift_deciles(y_true: np.ndarray, t_flag: np.ndarray, uplift_pred: np.ndarray) -> tuple[list[dict[str, Any]], float]:
    """Evaluate causal uplift model on out-of-time RCT test set by predicted uplift decile."""
    df_u = pd.DataFrame({"y": y_true, "t": t_flag, "u": uplift_pred})
    df_u["decile"] = pd.qcut(df_u["u"].rank(method="first"), 10, labels=list(range(10, 0, -1))).astype(int)
    deciles = []
    cum_inc = 0.0
    qini_x = [0.0]
    qini_y = [0.0]
    total_n = len(df_u)

    for dec in range(1, 11):
        sub = df_u[df_u["decile"] == dec]
        t_sub = sub[sub["t"] == 1]
        c_sub = sub[sub["t"] == 0]
        r_t = float(t_sub["y"].mean()) if len(t_sub) else 0.0
        r_c = float(c_sub["y"].mean()) if len(c_sub) else 0.0
        obs_uplift = r_t - r_c
        pred_u = float(sub["u"].mean())
        cum_inc += obs_uplift * len(t_sub)
        qini_x.append(dec / 10.0)
        qini_y.append(cum_inc)
        deciles.append({
            "decile": dec,
            "n_customers": int(len(sub)),
            "predicted_uplift_pp": round(pred_u * 100.0, 2),
            "observed_treatment_rate_pct": round(r_t * 100.0, 2),
            "observed_control_rate_pct": round(r_c * 100.0, 2),
            "observed_uplift_pp": round(obs_uplift * 100.0, 2),
            "cumulative_incremental_bookings": round(cum_inc, 1),
        })

    # Normalize Qini area above random targeting line
    area_model = float(np.trapezoid(qini_y, qini_x))
    area_random = 0.5 * qini_y[-1]
    qini_gain = (area_model - area_random) / max(1.0, abs(qini_y[-1]))
    return deciles, round(qini_gain, 4)


def run_ml_pipeline() -> None:
    t0 = time.perf_counter()
    logger.info("Loading RCT customer-campaign feature table for leakage-free modeling...")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(FEATURE_SQL)
            df = pd.DataFrame(cur.fetchall())
            cur.execute(ALL_CUSTOMERS_SQL)
            df_customers = pd.DataFrame(cur.fetchall())

    df["start_date"] = pd.to_datetime(df["start_date"])
    df["t_flag"] = (df["assignment_group"] == "treatment").astype(int)

    # Strict chronological split (no random leak across time)
    train_mask = df["start_date"] <= "2025-05-31"
    val_mask = (df["start_date"] > "2025-05-31") & (df["start_date"] <= "2025-11-30")
    test_mask = df["start_date"] > "2025-11-30"

    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    test_df = df[test_mask].copy()

    logger.info(
        "Chronological splits: train=%d (2024-01..2025-05), val=%d (2025-06..2025-11), test=%d (2025-12..2026-08)",
        len(train_df), len(val_df), len(test_df),
    )

    # Response prediction models evaluated on treated RCT population
    tr_t = train_df[train_df["t_flag"] == 1]
    va_t = val_df[val_df["t_flag"] == 1]
    te_t = test_df[test_df["t_flag"] == 1]

    X_train, y_train = tr_t[ALL_FEATURES], tr_t["booked_in_window"].to_numpy()
    X_val, y_val = va_t[ALL_FEATURES], va_t["booked_in_window"].to_numpy()
    X_test, y_test = te_t[ALL_FEATURES], te_t["booked_in_window"].to_numpy()

    limitations = [
        "Trained on synthetic airline CRM records; real carrier deployment requires live PNR, search-intent, and fare-class availability signals.",
        "Chronological holdout guards against temporal leakage, but seasonal demand shocks or competitor fare wars can shift calibration.",
        "T-Learner uplift estimates inherit finite-sample variance from individual RCT groups; production targeting should enforce exploration holdouts.",
        "Propensity scores reflect booking likelihood, not margin profitability — always pair uplift scores with expected contribution margin before targeting.",
    ]

    runs_to_store: list[dict[str, Any]] = []

    # 1. Naive Base-Rate Baseline
    base_rate_tr = float(y_train.mean())
    naive_prob = np.full(len(y_test), base_rate_tr)
    naive_eval = evaluate_classifier(y_test, naive_prob, te_t["segment_name"], optimal_threshold=0.5)
    runs_to_store.append({
        "model_name": "Naive Base-Rate Classifier",
        "model_role": "naive_baseline",
        "train_period": "2024-01 to 2025-05",
        "val_period": "2025-06 to 2025-11",
        "test_period": "2025-12 to 2026-08",
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_test": len(X_test),
        "training_seconds": 0.01,
        "qini_auc": None,
        "feature_importance": [],
        "uplift_deciles": None,
        "limitations": limitations,
        **naive_eval,
    })

    # 2. Regularized Logistic Regression Baseline
    t1 = time.perf_counter()
    lr_pipe = Pipeline([
        ("pre", build_preprocessor(dense_output=False)),
        ("clf", LogisticRegression(C=0.4, max_iter=1000, random_state=42)),
    ])
    lr_pipe.fit(X_train, y_train)
    lr_sec = round(time.perf_counter() - t1, 2)

    # Tune F1 threshold on validation set ONLY
    val_prob_lr = lr_pipe.predict_proba(X_val)[:, 1]
    best_th_lr = max(
        np.linspace(0.06, 0.35, 30),
        key=lambda th: f1_score(y_val, (val_prob_lr >= th).astype(int), zero_division=0),
    )
    test_prob_lr = lr_pipe.predict_proba(X_test)[:, 1]
    lr_eval = evaluate_classifier(y_test, test_prob_lr, te_t["segment_name"], optimal_threshold=float(best_th_lr))

    # Permutation importance on raw input features (clean, interpretable, grouped by business feature)
    perm_lr = permutation_importance(lr_pipe, X_val.iloc[:8000], y_val[:8000], n_repeats=5, random_state=42, scoring="roc_auc")
    lr_fi = sorted(
        [{"feature": col, "importance": round(float(imp), 5)} for col, imp in zip(ALL_FEATURES, perm_lr.importances_mean)],
        key=lambda x: x["importance"],
        reverse=True,
    )

    runs_to_store.append({
        "model_name": "Regularized Logistic Regression (L2)",
        "model_role": "linear_baseline",
        "train_period": "2024-01 to 2025-05",
        "val_period": "2025-06 to 2025-11",
        "test_period": "2025-12 to 2026-08",
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_test": len(X_test),
        "training_seconds": lr_sec,
        "qini_auc": None,
        "feature_importance": lr_fi,
        "uplift_deciles": None,
        "limitations": limitations,
        **lr_eval,
    })

    # 3. Advanced Model: HistGradientBoostingClassifier (captures nonlinear segment x incentive interactions!)
    t2 = time.perf_counter()
    gbdt_pipe = Pipeline([
        ("pre", build_preprocessor(dense_output=True)),
        ("clf", HistGradientBoostingClassifier(
            max_iter=160,
            max_depth=5,
            learning_rate=0.055,
            min_samples_leaf=40,
            l2_regularization=2.0,
            random_state=42,
        )),
    ])
    gbdt_pipe.fit(X_train, y_train)
    gbdt_sec = round(time.perf_counter() - t2, 2)

    val_prob_gb = gbdt_pipe.predict_proba(X_val)[:, 1]
    best_th_gb = max(
        np.linspace(0.06, 0.35, 30),
        key=lambda th: f1_score(y_val, (val_prob_gb >= th).astype(int), zero_division=0),
    )
    test_prob_gb = gbdt_pipe.predict_proba(X_test)[:, 1]
    gb_eval = evaluate_classifier(y_test, test_prob_gb, te_t["segment_name"], optimal_threshold=float(best_th_gb))

    perm_gb = permutation_importance(gbdt_pipe, X_val.iloc[:8000], y_val[:8000], n_repeats=5, random_state=42, scoring="roc_auc")
    gb_fi = sorted(
        [{"feature": col, "importance": round(float(imp), 5)} for col, imp in zip(ALL_FEATURES, perm_gb.importances_mean)],
        key=lambda x: x["importance"],
        reverse=True,
    )

    runs_to_store.append({
        "model_name": "HistGradientBoosting Classifier",
        "model_role": "advanced_gbdt",
        "train_period": "2024-01 to 2025-05",
        "val_period": "2025-06 to 2025-11",
        "test_period": "2025-12 to 2026-08",
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_test": len(X_test),
        "training_seconds": gbdt_sec,
        "qini_auc": None,
        "feature_importance": gb_fi,
        "uplift_deciles": None,
        "limitations": limitations,
        **gb_eval,
    })

    # 4. Causal Uplift Model: T-Learner trained on Train+Val RCT Treatment vs. Control, evaluated on Test RCT!
    logger.info("Training Causal T-Learner Uplift Model on RCT Treatment vs. Control cohorts...")
    t3 = time.perf_counter()
    tv_df = pd.concat([train_df, val_df], ignore_index=True)
    tv_treat = tv_df[tv_df["t_flag"] == 1]
    tv_ctrl = tv_df[tv_df["t_flag"] == 0]

    mu1_pipe = Pipeline([
        ("pre", build_preprocessor(dense_output=True)),
        ("clf", HistGradientBoostingClassifier(max_iter=150, max_depth=5, learning_rate=0.05, min_samples_leaf=50, l2_regularization=2.5, random_state=42)),
    ])
    mu0_pipe = Pipeline([
        ("pre", build_preprocessor(dense_output=True)),
        ("clf", HistGradientBoostingClassifier(max_iter=130, max_depth=4, learning_rate=0.05, min_samples_leaf=50, l2_regularization=2.5, random_state=42)),
    ])
    mu1_pipe.fit(tv_treat[ALL_FEATURES], tv_treat["booked_in_window"].to_numpy())
    mu0_pipe.fit(tv_ctrl[ALL_FEATURES], tv_ctrl["booked_in_window"].to_numpy())
    uplift_sec = round(time.perf_counter() - t3, 2)

    test_mu1 = mu1_pipe.predict_proba(test_df[ALL_FEATURES])[:, 1]
    test_mu0 = mu0_pipe.predict_proba(test_df[ALL_FEATURES])[:, 1]
    test_uplift = test_mu1 - test_mu0
    uplift_deciles, qini_gain = compute_uplift_deciles(
        test_df["booked_in_window"].to_numpy(),
        test_df["t_flag"].to_numpy(),
        test_uplift,
    )

    # Also compute overall ROC-AUC of mu1 on treated test rows for reference
    t_test_mask = test_df["t_flag"].to_numpy() == 1
    up_eval = evaluate_classifier(
        test_df["booked_in_window"].to_numpy()[t_test_mask],
        test_mu1[t_test_mask],
        test_df["segment_name"][t_test_mask],
        optimal_threshold=float(best_th_gb),
    )
    runs_to_store.append({
        "model_name": "Causal T-Learner Uplift (GBDT)",
        "model_role": "causal_uplift_tlearner",
        "train_period": "2024-01 to 2025-11 (RCT T & C)",
        "val_period": "Internal early regularization",
        "test_period": "2025-12 to 2026-08 (Held-out RCT)",
        "n_train": len(tv_df),
        "n_val": len(val_df),
        "n_test": len(test_df),
        "training_seconds": uplift_sec,
        "qini_auc": qini_gain,
        "feature_importance": gb_fi,
        "uplift_deciles": uplift_deciles,
        "limitations": limitations,
        **up_eval,
    })

    # 5. Score all 52,000 customers for counterfactual scenarios (Baseline vs. 15% Fare Discount vs. 6,000 Bonus Miles)
    logger.info("Scoring all %d customers across counterfactual incentive scenarios...", len(df_customers))
    base_frame = df_customers.copy()
    base_frame["channel_name"] = "Email"
    base_frame["target_haul_type"] = "Network"
    base_frame["travel_season"] = "Spring Shoulder"

    # Scenario A: 15% Fare Discount offer
    disc_frame = base_frame.copy()
    disc_frame["campaign_type"] = "Discounted Ticket"
    disc_frame["discount_pct"] = 15.0
    disc_frame["bonus_miles_offer"] = 0

    # Scenario B: 6,000 Bonus Loyalty Miles offer
    miles_frame = base_frame.copy()
    miles_frame["campaign_type"] = "Bonus Loyalty Miles"
    miles_frame["discount_pct"] = 0.0
    miles_frame["bonus_miles_offer"] = 6000

    p0_base = mu0_pipe.predict_proba(disc_frame[ALL_FEATURES])[:, 1]
    p1_disc = mu1_pipe.predict_proba(disc_frame[ALL_FEATURES])[:, 1]
    p1_miles = mu1_pipe.predict_proba(miles_frame[ALL_FEATURES])[:, 1]

    u_disc = p1_disc - p0_base
    u_miles = p1_miles - p0_base
    u_best = np.maximum(u_disc, u_miles)
    p1_best = np.maximum(p1_disc, p1_miles)

    # Deciles (1 = top 10% highest uplift, 10 = lowest uplift)
    deciles_all = pd.qcut(pd.Series(u_best).rank(method="first"), 10, labels=list(range(10, 0, -1))).astype(int).to_numpy()

    # Classify each customer into clean, actionable commercial response archetypes
    q75_base = float(np.quantile(p0_base, 0.78))
    q65_spend = float(np.quantile(df_customers["historical_spend_12m"].to_numpy(), 0.72))
    q65_u_best = float(np.quantile(u_best, 0.65))
    q35_u_best = float(np.quantile(u_best, 0.35))

    score_rows: list[tuple[Any, ...]] = []
    for i in range(len(df_customers)):
        cid = int(df_customers["customer_id"].iloc[i])
        spend_i = float(df_customers["historical_spend_12m"].iloc[i])
        p0_i = float(p0_base[i])
        p1_i = float(p1_best[i])
        ud_i = float(u_disc[i])
        um_i = float(u_miles[i])
        ub_i = float(u_best[i])
        dec_i = int(deciles_all[i])

        if p0_i >= q75_base and ub_i < q65_u_best:
            archetype = "Sure Things (Baseline Bookers)"
            rec_inc = "Suppress Promo (Avoid Subsidy)"
        elif spend_i >= q65_spend and ub_i <= q35_u_best:
            archetype = "High-Value Non-Responders"
            rec_inc = "Service / Status Recognition"
        elif um_i >= ud_i + 0.008 and um_i > 0.018:
            archetype = "Loyalty-Incentive Responders"
            rec_inc = "Bonus Loyalty Miles"
        elif ud_i >= um_i + 0.008 and ud_i > 0.018:
            archetype = "Discount-Sensitive Responders"
            rec_inc = "Targeted Fare Discount"
        elif ub_i >= q65_u_best:
            archetype = "Highly Responsive Persuadables"
            rec_inc = "Bonus Loyalty Miles" if um_i >= ud_i else "Targeted Fare Discount"
        else:
            archetype = "Low-Propensity Dormant"
            rec_inc = "Low-Cost Reactivation Test"

        score_rows.append((
            cid,
            round(p0_i, 6),
            round(p1_i, 6),
            round(ub_i, 6),
            round(ud_i, 6),
            round(um_i, 6),
            dec_i,
            archetype,
            rec_inc,
        ))

    logger.info("Persisting %d ML runs and %d customer propensity scores to PostgreSQL...", len(runs_to_store), len(score_rows))
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE ml_model_runs RESTART IDENTITY;")
            cur.execute("TRUNCATE TABLE customer_propensity_scores;")

            for r in runs_to_store:
                cur.execute(
                    """
                    INSERT INTO ml_model_runs (
                        model_name, model_role, train_period, val_period, test_period,
                        n_train, n_val, n_test, roc_auc, roc_auc_ci_low, roc_auc_ci_high,
                        pr_auc, pr_auc_ci_low, pr_auc_ci_high, brier_score, log_loss_val,
                        f1_score_val, precision_top_20, lift_top_decile, qini_auc,
                        training_seconds, confusion_matrix_json, calibration_json,
                        feature_importance_json, slice_metrics_json, uplift_deciles_json, limitations_json
                    ) VALUES (
                        %(model_name)s, %(model_role)s, %(train_period)s, %(val_period)s, %(test_period)s,
                        %(n_train)s, %(n_val)s, %(n_test)s, %(roc_auc)s, %(roc_auc_ci_low)s, %(roc_auc_ci_high)s,
                        %(pr_auc)s, %(pr_auc_ci_low)s, %(pr_auc_ci_high)s, %(brier_score)s, %(log_loss_val)s,
                        %(f1_score_val)s, %(precision_top_20)s, %(lift_top_decile)s, %(qini_auc)s,
                        %(training_seconds)s, %(cm)s::jsonb, %(cal)s::jsonb,
                        %(fi)s::jsonb, %(sl)s::jsonb, %(ud)s::jsonb, %(lim)s::jsonb
                    );
                    """,
                    {
                        **r,
                        "cm": json.dumps(r["confusion_matrix"]),
                        "cal": json.dumps(r["calibration"]),
                        "fi": json.dumps(r["feature_importance"]),
                        "sl": json.dumps(r["slice_metrics"]),
                        "ud": json.dumps(r["uplift_deciles"]) if r["uplift_deciles"] is not None else None,
                        "lim": json.dumps(r["limitations"]),
                    },
                )

            # Fast COPY for customer_propensity_scores
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
            for row in score_rows:
                writer.writerow(row)
            buf.seek(0)
            with cur.copy(
                """
                COPY customer_propensity_scores (
                    customer_id, baseline_booking_prob, promo_booking_prob, predicted_uplift,
                    discount_uplift_score, miles_uplift_score, uplift_decile,
                    response_archetype, recommended_incentive
                ) FROM STDIN WITH (FORMAT text)
                """
            ) as copy:
                copy.write(buf.getvalue())

        conn.commit()
        with conn.cursor() as cur:
            cur.execute("ANALYZE customer_propensity_scores; ANALYZE ml_model_runs;")
        conn.commit()

    logger.info(
        "ML pipeline complete in %.1fs. Baseline LR AUC=%.4f (PR=%.4f) vs. GBDT AUC=%.4f (PR=%.4f), T-Learner Qini Gain=%.4f",
        time.perf_counter() - t0,
        lr_eval["roc_auc"],
        lr_eval["pr_auc"],
        gb_eval["roc_auc"],
        gb_eval["pr_auc"],
        qini_gain,
    )


if __name__ == "__main__":
    run_ml_pipeline()
