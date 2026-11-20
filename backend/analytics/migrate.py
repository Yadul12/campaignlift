"""Idempotent SQL migration runner for CampaignLift PostgreSQL database."""
from pathlib import Path
import logging
import psycopg

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.migrate")


def run_migrations(database_url: str | None = None, migrations_dir: str | None = None) -> list[str]:
    db_url = database_url or settings.database_url
    mig_path = Path(migrations_dir or settings.migrations_dir)
    sql_files = sorted(mig_path.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL migrations found in {mig_path}")

    applied_now: list[str] = []
    with psycopg.connect(db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            conn.commit()
            cur.execute("SELECT version FROM schema_migrations")
            already_applied = {row[0] for row in cur.fetchall()}

            for sql_file in sql_files:
                version = sql_file.name
                if version in already_applied:
                    logger.info("Migration already applied: %s", version)
                    continue
                logger.info("Applying migration: %s", version)
                sql_text = sql_file.read_text(encoding="utf-8")
                cur.execute(sql_text)
                cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                conn.commit()
                applied_now.append(version)

    logger.info("Migrations complete. Newly applied: %s", applied_now or "none")
    return applied_now


if __name__ == "__main__":
    run_migrations()
