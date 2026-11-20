from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://campaignlift:campaignlift_dev_pw@localhost:5448/campaignlift"
    data_generation_seed: int = 20260401
    log_level: str = "INFO"
    migrations_dir: str = str(Path(__file__).resolve().parents[2] / "database" / "migrations")
    sql_analytics_dir: str = str(Path(__file__).resolve().parents[2] / "database" / "sql_analytics")
    app_version: str = "1.0.0"
    dataset_label: str = "SYNTHETIC DATASET · SIMULATED CAMPAIGN EXPERIMENTS (SEED 20260401)"


settings = Settings()
