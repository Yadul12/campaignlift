"""Promotion Economics Service: P&L Waterfall, Margin Erosion, and Cannibalization Decomposition."""
from __future__ import annotations

from typing import Any

from app.db import fetch_all
from app.schemas.analytics import GlobalFilterParams
from app.services.filters import build_summary_where


METRIC_FORMULAS = [
    {
        "metric": "Gross Booking Revenue",
        "formula": "SUM(gross_fare_revenue + ancillary_revenue) across non-cancelled attributed bookings",
        "note": "Top-line undiscounted ticket + ancillary value; never a substitute for profit.",
    },
    {
        "metric": "Fare Discounts",
        "formula": "SUM(discount_amount) from ticket_revenue / discount_transactions",
        "note": "Direct fare reduction granted to both incremental and baseline (organic) bookers.",
    },
    {
        "metric": "Estimated Variable Costs",
        "formula": "SUM(estimated_variable_cost) covering marginal fuel share, passenger catering, GDS/distribution, airport fees & payment processing",
        "note": "Scales with haul length, cabin class, and passenger count.",
    },
    {
        "metric": "Contribution Before Promotion",
        "formula": "Gross Booking Revenue - Estimated Variable Costs",
        "note": "Baseline seat margin prior to promo fare discounts, bonus miles liability, and media spend.",
    },
    {
        "metric": "Bonus Loyalty Miles Cost",
        "formula": "SUM(miles_awarded * cost_per_mile) for promotional bonus miles (breakage-adjusted liability)",
        "note": "Booked at ~$0.0094/mile liability cost, typically much lower margin erosion than cash discounts.",
    },
    {
        "metric": "Other Promotional Cost",
        "formula": "SUM(marketing_costs.amount_usd) covering Media Spend, Creative, Delivery Fees, and Agency Ops",
        "note": "Fixed and variable channel execution costs incurred regardless of conversion.",
    },
    {
        "metric": "Contribution After Promotion",
        "formula": "Gross Revenue - Discounts - Variable Costs - Bonus Miles Cost - Other Promotional Cost",
        "note": "Attributed campaign P&L; still includes baseline organic bookings that clicked/used promo codes.",
    },
    {
        "metric": "Incremental Contribution (RCT Causal)",
        "formula": "(Mean Net Contribution per Treated Assigned - Mean Net Contribution per Control Assigned) * N_Treatment - Other Promotional Cost",
        "note": "True economic profit created by the campaign net of organic cannibalization and promo subsidies.",
    },
    {
        "metric": "Estimated Baseline Subsidy (Deadweight Loss)",
        "formula": "(Control Booking Rate * N_Treatment) * Avg Promo Cost per Treated Redeeming Booker",
        "note": "Discounts & bonus miles absorbed by customers who would have booked at full fare without the offer.",
    },
]


def get_promotion_economics(filters: GlobalFilterParams) -> dict[str, Any]:
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
            v.discount_pct::FLOAT8 AS discount_pct,
            v.bonus_miles_offer,
            v.customers_targeted,
            v.attributed_bookings,
            v.gross_booking_revenue::FLOAT8 AS gross_revenue,
            v.discount_cost::FLOAT8 AS discount_cost,
            v.net_ticket_revenue::FLOAT8 AS net_ticket_revenue,
            v.variable_cost::FLOAT8 AS variable_cost,
            v.contribution_before_promo::FLOAT8 AS contribution_before_promo,
            v.loyalty_reward_cost::FLOAT8 AS bonus_miles_cost,
            v.marketing_spend::FLOAT8 AS other_promo_cost,
            v.contribution_after_promo::FLOAT8 AS contribution_after_promo,
            v.incremental_bookings::FLOAT8 AS incremental_bookings,
            v.incremental_revenue::FLOAT8 AS incremental_revenue,
            v.incremental_contribution::FLOAT8 AS incremental_contribution,
            v.conversion_control::FLOAT8 AS conversion_control,
            v.conversion_treatment::FLOAT8 AS conversion_treatment,
            v.recommendation_status,
            ers.booking_freq_control::FLOAT8 AS booking_freq_control,
            ers.n_treatment
        FROM v_campaign_commercial_summary v
        LEFT JOIN experiment_results_store ers ON ers.campaign_id = v.campaign_id
        WHERE {where_sql}
        ORDER BY v.incremental_contribution DESC NULLS LAST, v.contribution_after_promo DESC
        """,
        params,
    )

    tot_gross = sum(float(r["gross_revenue"] or 0) for r in rows)
    tot_disc = sum(float(r["discount_cost"] or 0) for r in rows)
    tot_var = sum(float(r["variable_cost"] or 0) for r in rows)
    tot_cb = sum(float(r["contribution_before_promo"] or 0) for r in rows)
    tot_miles = sum(float(r["bonus_miles_cost"] or 0) for r in rows)
    tot_media = sum(float(r["other_promo_cost"] or 0) for r in rows)
    tot_ca = sum(float(r["contribution_after_promo"] or 0) for r in rows)

    rct_rows = [r for r in rows if r["experiment_type"] == "RCT"]
    tot_inc_contrib = sum(float(r["incremental_contribution"] or 0) for r in rct_rows)
    tot_inc_rev = sum(float(r["incremental_revenue"] or 0) for r in rct_rows)
    tot_inc_book = sum(float(r["incremental_bookings"] or 0) for r in rct_rows)

    campaign_economics = []
    tot_deadweight_subsidy = 0.0
    tot_rct_incentive_cost = 0.0

    for r in rows:
        gross = float(r["gross_revenue"] or 0)
        disc = float(r["discount_cost"] or 0)
        miles = float(r["bonus_miles_cost"] or 0)
        var_c = float(r["variable_cost"] or 0)
        cb = float(r["contribution_before_promo"] or 0)
        media = float(r["other_promo_cost"] or 0)
        ca = float(r["contribution_after_promo"] or 0)
        attr_b = int(r["attributed_bookings"] or 0)
        inc_b = float(r["incremental_bookings"]) if r["incremental_bookings"] is not None else None
        inc_c = float(r["incremental_contribution"]) if r["incremental_contribution"] is not None else None

        # Deadweight subsidy decomposition (for RCTs only!)
        deadweight = None
        incremental_share_of_attributed = None
        if r["experiment_type"] == "RCT" and attr_b > 0:
            promo_cost_per_book = (disc + miles) / attr_b
            inc_b_pos = max(0.0, inc_b or 0.0)
            baseline_redeemers = max(0.0, attr_b - inc_b_pos)
            deadweight = round(baseline_redeemers * promo_cost_per_book, 2)
            incremental_share_of_attributed = round(min(1.0, inc_b_pos / attr_b), 4)
            tot_deadweight_subsidy += deadweight
            tot_rct_incentive_cost += (disc + miles)

        erosion_pct = round((disc + miles) / cb, 4) if cb > 0 else 0.0

        campaign_economics.append({
            "campaign_id": int(r["campaign_id"]),
            "campaign_code": r["campaign_code"],
            "campaign_name": r["campaign_name"],
            "campaign_type": r["campaign_type"],
            "experiment_type": r["experiment_type"],
            "channel_name": r["channel_name"],
            "target_segment_name": r["target_segment_name"],
            "discount_pct": float(r["discount_pct"] or 0),
            "bonus_miles_offer": int(r["bonus_miles_offer"] or 0),
            "attributed_bookings": attr_b,
            "gross_revenue": round(gross, 2),
            "discount_cost": round(disc, 2),
            "variable_cost": round(var_c, 2),
            "contribution_before_promo": round(cb, 2),
            "bonus_miles_cost": round(miles, 2),
            "other_promo_cost": round(media, 2),
            "contribution_after_promo": round(ca, 2),
            "incremental_bookings": round(inc_b, 1) if inc_b is not None else None,
            "incremental_revenue": round(float(r["incremental_revenue"]), 2) if r["incremental_revenue"] is not None else None,
            "incremental_contribution": round(inc_c, 2) if inc_c is not None else None,
            "deadweight_subsidy": deadweight,
            "incremental_share_of_attributed": incremental_share_of_attributed,
            "margin_erosion_pct": erosion_pct,
            "recommendation_status": r["recommendation_status"],
        })

    # Portfolio P&L waterfall steps
    waterfall = [
        {"label": "Gross Booking Revenue", "value": round(tot_gross, 2), "measure": "absolute"},
        {"label": "Fare Discounts", "value": round(-tot_disc, 2), "measure": "relative"},
        {"label": "Estimated Variable Costs", "value": round(-tot_var, 2), "measure": "relative"},
        {"label": "Bonus Loyalty Miles Cost", "value": round(-tot_miles, 2), "measure": "relative"},
        {"label": "Media & Other Promo Cost", "value": round(-tot_media, 2), "measure": "relative"},
        {"label": "Contribution After Promo", "value": round(tot_ca, 2), "measure": "total"},
    ]

    # Aggregated economics by campaign type
    type_buckets: dict[str, dict[str, Any]] = {}
    for c in campaign_economics:
        ct = c["campaign_type"]
        b = type_buckets.setdefault(ct, {
            "campaign_type": ct,
            "campaigns": 0,
            "rct_campaigns": 0,
            "gross_revenue": 0.0,
            "discount_cost": 0.0,
            "bonus_miles_cost": 0.0,
            "other_promo_cost": 0.0,
            "contribution_before_promo": 0.0,
            "contribution_after_promo": 0.0,
            "incremental_contribution": 0.0,
            "deadweight_subsidy": 0.0,
        })
        b["campaigns"] += 1
        b["gross_revenue"] += c["gross_revenue"]
        b["discount_cost"] += c["discount_cost"]
        b["bonus_miles_cost"] += c["bonus_miles_cost"]
        b["other_promo_cost"] += c["other_promo_cost"]
        b["contribution_before_promo"] += c["contribution_before_promo"]
        b["contribution_after_promo"] += c["contribution_after_promo"]
        if c["experiment_type"] == "RCT":
            b["rct_campaigns"] += 1
            b["incremental_contribution"] += float(c["incremental_contribution"] or 0.0)
            b["deadweight_subsidy"] += float(c["deadweight_subsidy"] or 0.0)

    by_type = []
    for b in type_buckets.values():
        cb = b["contribution_before_promo"]
        b["margin_erosion_pct"] = round((b["discount_cost"] + b["bonus_miles_cost"]) / cb, 4) if cb > 0 else 0.0
        for k in ("gross_revenue", "discount_cost", "bonus_miles_cost", "other_promo_cost", "contribution_before_promo", "contribution_after_promo", "incremental_contribution", "deadweight_subsidy"):
            b[k] = round(b[k], 2)
        by_type.append(b)
    by_type.sort(key=lambda x: x["incremental_contribution"], reverse=True)

    return {
        "summary": {
            "campaign_count": len(rows),
            "rct_campaign_count": len(rct_rows),
            "gross_revenue": round(tot_gross, 2),
            "discount_cost": round(tot_disc, 2),
            "variable_cost": round(tot_var, 2),
            "contribution_before_promo": round(tot_cb, 2),
            "bonus_miles_cost": round(tot_miles, 2),
            "other_promo_cost": round(tot_media, 2),
            "contribution_after_promo": round(tot_ca, 2),
            "margin_erosion_pct": round((tot_disc + tot_miles) / tot_cb, 4) if tot_cb > 0 else 0.0,
            "rct_incremental_bookings": round(tot_inc_book, 1),
            "rct_incremental_revenue": round(tot_inc_rev, 2),
            "rct_incremental_contribution": round(tot_inc_contrib, 2),
            "rct_deadweight_subsidy": round(tot_deadweight_subsidy, 2),
            "rct_subsidy_waste_share": round(tot_deadweight_subsidy / tot_rct_incentive_cost, 4) if tot_rct_incentive_cost > 0 else 0.0,
        },
        "waterfall": waterfall,
        "by_campaign_type": by_type,
        "campaigns": campaign_economics,
        "formulas": METRIC_FORMULAS,
    }
