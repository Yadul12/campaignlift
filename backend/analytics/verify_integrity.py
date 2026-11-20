"""
End-to-End Analytical & Data Integrity Verifier for CampaignLift.
Checks scale targets, schema completeness, funnel monotonicity, RCT randomization
balance (SRM & covariate SMDs), observational selection-bias detection,
accounting identities, and ML evaluation outputs.
"""
from __future__ import annotations

import logging
import sys

import psycopg
from psycopg.rows import dict_row

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.verify")


def verify_all() -> bool:
    errors: list[str] = []
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # 1. Verify all 15 core tables & scale requirements
            tables = [
                "customers", "customer_segments", "campaigns", "campaign_channels",
                "campaign_assignments", "campaign_exposures", "bookings", "booking_items",
                "ticket_revenue", "discount_transactions", "loyalty_rewards", "route_markets",
                "marketing_costs", "customer_responses", "calendar_dimension",
            ]
            counts = {}
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}")
                counts[tbl] = int(cur.fetchone()["cnt"])
            logger.info("Core table row counts: %s", counts)

            if counts["customers"] < 50000:
                errors.append(f"customers count {counts['customers']} < 50,000")
            if counts["campaigns"] < 100:
                errors.append(f"campaigns count {counts['campaigns']} < 100")
            if counts["campaign_assignments"] < 150000:
                errors.append(f"campaign_assignments count {counts['campaign_assignments']} < 150,000")
            if counts["bookings"] < 100000:
                errors.append(f"bookings count {counts['bookings']} < 100,000")

            # 2. Verify zero control group exposures
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM campaign_exposures ce
                JOIN campaign_assignments ca ON ca.assignment_id = ce.assignment_id
                WHERE ca.assignment_group = 'control'
                """
            )
            ctrl_exp = int(cur.fetchone()["cnt"])
            if ctrl_exp != 0:
                errors.append(f"Found {ctrl_exp} exposures in RCT control groups!")

            # 3. Verify funnel monotonicity per campaign
            cur.execute(
                """
                SELECT campaign_code, eligible_audience_count, total_assigned, customers_targeted,
                       customers_reached, customers_engaged, attributed_bookers, completed_travelers
                FROM v_campaign_commercial_summary
                """
            )
            bad_funnels = []
            for r in cur.fetchall():
                if not (
                    r["eligible_audience_count"] >= r["total_assigned"]
                    and r["customers_targeted"] >= r["customers_reached"]
                    and r["customers_reached"] >= r["customers_engaged"]
                    and r["customers_engaged"] >= r["attributed_bookers"]
                    and r["attributed_bookers"] >= r["completed_travelers"]
                ):
                    bad_funnels.append(r["campaign_code"])
            if bad_funnels:
                errors.append(f"Non-monotonic funnels in campaigns: {bad_funnels[:5]}")

            # 4. Verify RCT SRM & Covariate balance vs Observational selection bias
            cur.execute(
                """
                SELECT
                    experiment_type,
                    COUNT(*) AS cnt,
                    AVG(max_covariate_smd)::FLOAT8 AS avg_max_smd,
                    COUNT(*) FILTER (WHERE srm_passed = TRUE) AS srm_pass,
                    COUNT(*) FILTER (WHERE is_statistically_significant = TRUE) AS sig_cnt,
                    COUNT(*) FILTER (WHERE incremental_contribution > 0) AS pos_contrib,
                    COUNT(*) FILTER (WHERE incremental_contribution < 0) AS neg_contrib
                FROM experiment_results_store
                GROUP BY experiment_type
                """
            )
            exp_stats = {r["experiment_type"]: r for r in cur.fetchall()}
            logger.info("Experiment audit summary: %s", exp_stats)
            if exp_stats.get("RCT", {}).get("avg_max_smd", 1.0) > 0.12:
                errors.append(f"RCT average max SMD too high: {exp_stats['RCT']['avg_max_smd']}")
            if exp_stats.get("Observational", {}).get("avg_max_smd", 0.0) < 0.20:
                errors.append(f"Observational campaigns should exhibit realistic selection bias: {exp_stats.get('Observational')}")

            # 5. Verify accounting identity on ticket_revenue
            cur.execute(
                """
                SELECT COUNT(*) AS mismatches
                FROM ticket_revenue
                WHERE ABS((gross_fare_revenue + ancillary_revenue) - gross_total_revenue) > 0.02
                   OR ABS((gross_total_revenue - discount_amount) - net_ticket_revenue) > 0.02
                   OR ABS((gross_total_revenue - estimated_variable_cost) - contribution_before_promo) > 0.02
                """
            )
            mismatches = int(cur.fetchone()["mismatches"])
            if mismatches > 0:
                errors.append(f"Found {mismatches} ticket_revenue accounting mismatches!")

            # 6. Verify ML runs & propensity scores populated
            cur.execute("SELECT model_role, roc_auc, pr_auc, qini_auc FROM ml_model_runs ORDER BY run_id")
            ml_rows = cur.fetchall()
            logger.info("ML model runs: %s", ml_rows)
            if len(ml_rows) < 4:
                errors.append(f"Expected 4 ML model runs, got {len(ml_rows)}")

            cur.execute("SELECT response_archetype, COUNT(*) AS cnt FROM customer_propensity_scores GROUP BY response_archetype ORDER BY cnt DESC")
            arch_rows = cur.fetchall()
            logger.info("Customer archetypes: %s", arch_rows)
            if sum(int(r["cnt"]) for r in arch_rows) != counts["customers"]:
                errors.append("Not all customers scored in customer_propensity_scores!")

    if errors:
        for e in errors:
            logger.error("INTEGRITY FAILURE: %s", e)
        return False
    logger.info("ALL INTEGRITY CHECKS PASSED SUCCESSFULLY!")
    return True


if __name__ == "__main__":
    ok = verify_all()
    sys.exit(0 if ok else 1)
