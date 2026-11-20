"""Unit tests for CampaignLift statistical experimentation engine."""
from __future__ import annotations

import math
import numpy as np
import pytest

from app.services.stats_engine import (
    estimate_sample_size,
    sample_ratio_mismatch_test,
    standardized_mean_difference,
    two_proportion_test,
    welch_t_test,
)


def test_two_proportion_significant_lift():
    # Treatment: 140/1000 (14%), Control: 100/1000 (10%) -> diff = +4pp
    res = two_proportion_test(140, 1000, 100, 1000)
    assert math.isclose(res["treatment_rate"], 0.14, abs_tol=1e-6)
    assert math.isclose(res["control_rate"], 0.10, abs_tol=1e-6)
    assert math.isclose(res["lift_abs"], 0.04, abs_tol=1e-6)
    assert math.isclose(res["lift_rel"], 0.40, abs_tol=1e-6)
    assert res["p_value"] < 0.01
    assert res["chi2_p_value"] < 0.01
    assert res["ci_low"] > 0.0
    assert res["ci_high"] > res["ci_low"]
    assert res["significant"] is True
    assert 0.70 < res["power"] <= 1.0


def test_two_proportion_null_effect():
    res = two_proportion_test(100, 1000, 100, 1000)
    assert res["lift_abs"] == 0.0
    assert res["p_value"] == 1.0
    assert res["significant"] is False
    assert res["ci_low"] < 0.0 < res["ci_high"]


def test_welch_t_test_unequal_variances():
    rng = np.random.default_rng(123)
    c = rng.normal(loc=50.0, scale=10.0, size=600)
    t = rng.normal(loc=56.0, scale=22.0, size=600)
    res = welch_t_test(t, c)
    assert res["lift_abs"] > 3.0
    assert res["p_value"] < 0.001
    assert res["ci_low"] > 0.0
    assert res["significant"] is True
    assert res["df"] < (len(c) + len(t) - 2)  # Welch df reduction under heteroscedasticity


def test_srm_pass_and_fail():
    ok = sample_ratio_mismatch_test(1012, 988, 0.50)
    assert ok["passed"] is True
    assert ok["p_value"] > 0.05

    bad = sample_ratio_mismatch_test(1200, 800, 0.50)
    assert bad["passed"] is False
    assert bad["p_value"] < 0.001


def test_smd_balance_detection():
    rng = np.random.default_rng(7)
    a = rng.normal(100, 15, 1000)
    b = rng.normal(100.3, 15, 1000)
    assert abs(standardized_mean_difference(a, b)) < 0.10

    biased = rng.normal(115, 15, 1000)
    assert abs(standardized_mean_difference(biased, b)) > 0.80


def test_sample_size_estimation_monotonicity():
    s_small_mde = estimate_sample_size(baseline_rate=0.08, mde_abs=0.01, alpha=0.05, power=0.80, treatment_split=0.50)
    s_large_mde = estimate_sample_size(baseline_rate=0.08, mde_abs=0.02, alpha=0.05, power=0.80, treatment_split=0.50)
    assert s_small_mde["required_n_total"] > s_large_mde["required_n_total"] * 3
    assert len(s_small_mde["power_curve"]) >= 8
    assert len(s_small_mde["mde_sensitivity"]) >= 5
