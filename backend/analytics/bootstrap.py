"""Full reproducible pipeline bootstrap: migrations -> synthetic data -> experiments -> ML -> audit."""
import logging
import sys

from analytics.migrate import run_migrations
from analytics.generate_data import main as generate_data_main
from analytics.run_experiments import run_all_experiments
from analytics.train_models import run_ml_pipeline
from analytics.verify_integrity import verify_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.bootstrap")


def main() -> None:
    logger.info("=== Step 1/5: Applying SQL Migrations ===")
    run_migrations()
    logger.info("=== Step 2/5: Generating Reproducible Synthetic Airline Dataset ===")
    generate_data_main()
    logger.info("=== Step 3/5: Running ITT Experimentation & Observational Diagnostics ===")
    run_all_experiments()
    logger.info("=== Step 4/5: Training Leakage-Free Response & Causal Uplift Models ===")
    run_ml_pipeline()
    logger.info("=== Step 5/5: Running End-to-End Mathematical & Data Integrity Audit ===")
    ok = verify_all()
    if not ok:
        sys.exit(1)
    logger.info("=== CampaignLift Data & Analytics Bootstrap Complete ===")


if __name__ == "__main__":
    main()
