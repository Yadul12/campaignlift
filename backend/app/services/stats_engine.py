"""
Statistically valid experimentation engine for CampaignLift.
Implements Intention-to-Treat (ITT) inference, SRM diagnostics, covariate balance,
two-proportion z-test, Pearson chi-square test, Welch's t-test, confidence intervals,
statistical power, sample-size estimation, and observational IPW sensitivity analysis.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest


def _safe_float(val: Any, default: float | None = 0.0) -> float | None:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def two_proportion_test(
    success_t: int,
    n_t: int,
    success_c: int,
    n_c: int,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Two-proportion z-test, Pearson chi-square test, Wald 95% CI, and achieved power."""
    if n_t <= 0 or n_c <= 0:
        return {
            "control_rate": 0.0,
            "treatment_rate": 0.0,
            "lift_abs": 0.0,
            "lift_rel": None,
            "z_stat": 0.0,
            "p_value": 1.0,
            "chi2_stat": 0.0,
            "chi2_p_value": 1.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "power": 0.0,
            "significant": False,
        }

    p_t = success_t / n_t
    p_c = success_c / n_c
    diff = p_t - p_c
    rel = (diff / p_c) if p_c > 0 else None

    if (success_t + success_c == 0) or (success_t + success_c == n_t + n_c):
        z_stat, p_val = 0.0, 1.0
        chi2_stat, chi2_p = 0.0, 1.0
    else:
        z_raw, p_raw = proportions_ztest([success_t, success_c], [n_t, n_c], alternative="two-sided")
        z_stat = float(z_raw) if not math.isnan(float(z_raw)) else 0.0
        p_val = float(p_raw) if not math.isnan(float(p_raw)) else 1.0
        table = np.array([[success_t, n_t - success_t], [success_c, n_c - success_c]])
        chi2_raw, chi2_p_raw, _, _ = stats.chi2_contingency(table, correction=False)
        chi2_stat = float(chi2_raw)
        chi2_p = float(chi2_p_raw)

    z_crit = float(stats.norm.ppf(1.0 - alpha / 2.0))
    se_unpooled = math.sqrt(max(0.0, (p_t * (1.0 - p_t) / n_t) + (p_c * (1.0 - p_c) / n_c)))
    ci_low = diff - z_crit * se_unpooled
    ci_high = diff + z_crit * se_unpooled

    # Achieved power via Cohen's h
    h = abs(float(proportion_effectsize(max(1e-6, min(1 - 1e-6, p_t)), max(1e-6, min(1 - 1e-6, p_c)))))
    if h < 1e-6:
        power = alpha
    else:
        ratio = n_t / n_c
        power = float(NormalIndPower().power(effect_size=h, nobs1=n_c, alpha=alpha, ratio=ratio, alternative="two-sided"))
        power = max(0.0, min(1.0, power))

    return {
        "control_rate": p_c,
        "treatment_rate": p_t,
        "lift_abs": diff,
        "lift_rel": rel,
        "z_stat": z_stat,
        "p_value": p_val,
        "chi2_stat": chi2_stat,
        "chi2_p_value": chi2_p,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "power": power,
        "significant": p_val < alpha,
    }


def welch_t_test(
    arr_t: np.ndarray,
    arr_c: np.ndarray,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Welch's two-sample t-test with Welch-Satterthwaite CI and achieved statistical power."""
    a_t = np.asarray(arr_t, dtype=np.float64)
    a_c = np.asarray(arr_c, dtype=np.float64)
    n_t, n_c = len(a_t), len(a_c)

    if n_t < 2 or n_c < 2:
        m_t = float(a_t.mean()) if n_t > 0 else 0.0
        m_c = float(a_c.mean()) if n_c > 0 else 0.0
        return {
            "control_mean": m_c,
            "treatment_mean": m_t,
            "lift_abs": m_t - m_c,
            "lift_rel": ((m_t - m_c) / m_c) if abs(m_c) > 1e-9 else None,
            "t_stat": 0.0,
            "p_value": 1.0,
            "df": 0.0,
            "ci_low": m_t - m_c,
            "ci_high": m_t - m_c,
            "power": 0.0,
            "significant": False,
        }

    m_t, m_c = float(a_t.mean()), float(a_c.mean())
    v_t, v_c = float(a_t.var(ddof=1)), float(a_c.var(ddof=1))
    diff = m_t - m_c
    rel = (diff / abs(m_c)) if abs(m_c) > 1e-9 else None

    if v_t == 0.0 and v_c == 0.0:
        return {
            "control_mean": m_c,
            "treatment_mean": m_t,
            "lift_abs": diff,
            "lift_rel": rel,
            "t_stat": 0.0,
            "p_value": 1.0,
            "df": float(n_t + n_c - 2),
            "ci_low": diff,
            "ci_high": diff,
            "power": alpha,
            "significant": False,
        }

    t_res = stats.ttest_ind(a_t, a_c, equal_var=False)
    t_stat = _safe_float(t_res.statistic, 0.0) or 0.0
    p_val = _safe_float(t_res.pvalue, 1.0)
    if p_val is None:
        p_val = 1.0

    se2 = (v_t / n_t) + (v_c / n_c)
    se = math.sqrt(max(0.0, se2))
    denom = ((v_t / n_t) ** 2) / (n_t - 1) + ((v_c / n_c) ** 2) / (n_c - 1)
    df = (se2 ** 2 / denom) if denom > 0 else float(n_t + n_c - 2)
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df=max(1.0, df)))
    ci_low = diff - t_crit * se
    ci_high = diff + t_crit * se

    pooled_sd = math.sqrt(max(1e-12, ((n_t - 1) * v_t + (n_c - 1) * v_c) / (n_t + n_c - 2)))
    cohen_d = abs(diff) / pooled_sd
    if cohen_d < 1e-6:
        power = alpha
    else:
        try:
            power = float(
                TTestIndPower().power(
                    effect_size=min(cohen_d, 5.0),
                    nobs1=n_c,
                    alpha=alpha,
                    ratio=n_t / n_c,
                    alternative="two-sided",
                )
            )
            power = max(0.0, min(1.0, power))
        except Exception:
            power = 1.0 if p_val < 1e-6 else alpha

    return {
        "control_mean": m_c,
        "treatment_mean": m_t,
        "lift_abs": diff,
        "lift_rel": rel,
        "t_stat": t_stat,
        "p_value": p_val,
        "df": df,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "power": power,
        "significant": p_val < alpha,
    }


def sample_ratio_mismatch_test(n_t: int, n_c: int, expected_treatment_split: float) -> dict[str, Any]:
    """Chi-square goodness-of-fit test for Sample Ratio Mismatch (SRM)."""
    total = n_t + n_c
    if total <= 0 or expected_treatment_split <= 0 or expected_treatment_split >= 1:
        return {"chi2": 0.0, "p_value": 1.0, "passed": True, "observed_split": 0.0, "expected_split": expected_treatment_split}
    exp_t = total * expected_treatment_split
    exp_c = total * (1.0 - expected_treatment_split)
    chi2_raw, p_raw = stats.chisquare([n_t, n_c], f_exp=[exp_t, exp_c])
    p_val = float(p_raw)
    return {
        "chi2": float(chi2_raw),
        "p_value": p_val,
        "passed": p_val >= 0.001,
        "observed_split": n_t / total,
        "expected_split": expected_treatment_split,
    }


def standardized_mean_difference(arr_t: np.ndarray, arr_c: np.ndarray) -> float:
    """Compute pre-treatment covariate Standardized Mean Difference (SMD)."""
    a_t = np.asarray(arr_t, dtype=np.float64)
    a_c = np.asarray(arr_c, dtype=np.float64)
    if len(a_t) < 2 or len(a_c) < 2:
        return 0.0
    m_t, m_c = float(a_t.mean()), float(a_c.mean())
    v_t, v_c = float(a_t.var(ddof=1)), float(a_c.var(ddof=1))
    denom = math.sqrt((v_t + v_c) / 2.0)
    if denom < 1e-9:
        return 0.0
    return (m_t - m_c) / denom


def compute_covariate_balance(df: pd.DataFrame, group_col: str, treat_val: str, control_val: str) -> tuple[list[dict[str, Any]], float]:
    """Assess pre-campaign observable covariate balance between treatment and control groups."""
    t_df = df[df[group_col] == treat_val]
    c_df = df[df[group_col] == control_val]
    covariates = [
        ("historical_trips_12m", "Historical Trips (12m)"),
        ("historical_spend_12m", "Historical Spend (12m USD)"),
        ("tenure_months", "Loyalty Tenure (Months)"),
        ("miles_balance", "Miles Balance"),
        ("app_active_num", "Mobile App Active Share"),
    ]
    rows: list[dict[str, Any]] = []
    max_abs_smd = 0.0
    for col, label in covariates:
        if col not in df.columns:
            continue
        t_vals = t_df[col].to_numpy(dtype=np.float64)
        c_vals = c_df[col].to_numpy(dtype=np.float64)
        smd = standardized_mean_difference(t_vals, c_vals)
        abs_smd = abs(smd)
        max_abs_smd = max(max_abs_smd, abs_smd)
        status = "Balanced" if abs_smd < 0.10 else ("Mild Imbalance" if abs_smd < 0.20 else "Selection Bias Detected")
        rows.append({
            "covariate": label,
            "treatment_mean": round(float(t_vals.mean()) if len(t_vals) else 0.0, 3),
            "control_mean": round(float(c_vals.mean()) if len(c_vals) else 0.0, 3),
            "smd": round(smd, 4),
            "status": status,
        })
    return rows, round(max_abs_smd, 4)


def ipw_observational_sensitivity(df: pd.DataFrame) -> dict[str, Any]:
    """
    Inverse Probability Weighting (IPW) sensitivity estimate for observational campaigns.
    Uses ONLY observable pre-period covariates; results are explicitly caveated as
    non-causal sensitivity checks because unobserved confounding cannot be ruled out.
    """
    work = df.copy()
    work["t_flag"] = (work["assignment_group"] == "observational_targeted").astype(int)
    if work["t_flag"].nunique() < 2 or len(work) < 100:
        return {"ipw_conversion_lift_abs": None, "ipw_contrib_lift_per_cust": None, "overlap_pct": 0.0}

    num_cols = ["historical_trips_12m", "historical_spend_12m", "tenure_months", "miles_balance", "app_active_num"]
    cat_cols = ["segment_id", "loyalty_tier"]

    pre = ColumnTransformer([
        ("num", StandardScaler(), num_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
    ])
    pipe = Pipeline([
        ("pre", pre),
        ("clf", LogisticRegression(C=1.0, max_iter=500)),
    ])
    pipe.fit(work[num_cols + cat_cols], work["t_flag"])
    ps = pipe.predict_proba(work[num_cols + cat_cols])[:, 1]
    overlap_mask = (ps >= 0.05) & (ps <= 0.95)
    overlap_pct = float(overlap_mask.mean())
    ps_clip = np.clip(ps, 0.05, 0.95)

    t = work["t_flag"].to_numpy(dtype=np.float64)
    y_conv = work["converted"].to_numpy(dtype=np.float64)
    y_contrib = work["net_contribution"].to_numpy(dtype=np.float64)

    w1 = t / ps_clip
    w0 = (1.0 - t) / (1.0 - ps_clip)
    conv_1 = float(np.sum(w1 * y_conv) / np.sum(w1))
    conv_0 = float(np.sum(w0 * y_conv) / np.sum(w0))
    cont_1 = float(np.sum(w1 * y_contrib) / np.sum(w1))
    cont_0 = float(np.sum(w0 * y_contrib) / np.sum(w0))

    return {
        "ipw_conversion_lift_abs": round(conv_1 - conv_0, 6),
        "ipw_contrib_lift_per_cust": round(cont_1 - cont_0, 4),
        "overlap_pct": round(overlap_pct, 4),
    }


def estimate_sample_size(
    baseline_rate: float,
    mde_abs: float,
    alpha: float = 0.05,
    power: float = 0.80,
    treatment_split: float = 0.50,
) -> dict[str, Any]:
    """Calculate required per-group and total sample size for an airline promotion A/B test."""
    p0 = max(0.001, min(0.95, baseline_rate))
    p1 = max(0.0015, min(0.99, p0 + abs(mde_abs)))
    split = max(0.10, min(0.90, treatment_split))
    ratio = split / (1.0 - split)

    h = abs(float(proportion_effectsize(p1, p0)))
    solver = NormalIndPower()
    n_control = int(math.ceil(float(solver.solve_power(effect_size=h, power=power, alpha=alpha, ratio=ratio, alternative="two-sided"))))
    n_treatment = int(math.ceil(n_control * ratio))
    n_total = n_control + n_treatment

    # Power curve across multipliers of required sample size
    multipliers = [0.2, 0.35, 0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.8, 2.2]
    power_curve = []
    for mult in multipliers:
        nc = max(25, int(round(n_control * mult)))
        nt = max(25, int(round(n_treatment * mult)))
        pw = float(solver.power(effect_size=h, nobs1=nc, alpha=alpha, ratio=nt / nc, alternative="two-sided"))
        power_curve.append({
            "total_sample": nc + nt,
            "control_sample": nc,
            "treatment_sample": nt,
            "power": round(max(0.0, min(1.0, pw)), 4),
        })

    # MDE sensitivity grid (0.5x to 2.0x requested MDE)
    mde_grid = []
    for factor in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        m_abs = round(abs(mde_abs) * factor, 4)
        p_alt = min(0.99, p0 + m_abs)
        h_alt = abs(float(proportion_effectsize(p_alt, p0)))
        if h_alt > 1e-6:
            nc_alt = int(math.ceil(float(solver.solve_power(effect_size=h_alt, power=power, alpha=alpha, ratio=ratio, alternative="two-sided"))))
            nt_alt = int(math.ceil(nc_alt * ratio))
            mde_grid.append({
                "mde_abs_pp": round(m_abs * 100.0, 2),
                "mde_rel_pct": round((m_abs / p0) * 100.0, 1),
                "n_control": nc_alt,
                "n_treatment": nt_alt,
                "n_total": nc_alt + nt_alt,
            })

    return {
        "baseline_rate": p0,
        "target_treatment_rate": p1,
        "mde_abs": abs(mde_abs),
        "mde_rel": abs(mde_abs) / p0,
        "alpha": alpha,
        "target_power": power,
        "treatment_split": split,
        "cohen_h": round(h, 4),
        "required_n_control": n_control,
        "required_n_treatment": n_treatment,
        "required_n_total": n_total,
        "power_curve": power_curve,
        "mde_sensitivity": mde_grid,
    }
