from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIDPULSE_", env_file=".env", extra="ignore")

    env: Literal["development", "demo", "test"] = "development"
    market: Literal["DE"] = "DE"
    data_source: Literal["synthetic", "opsd", "entsoe"] = "synthetic"
    runtime: Path = Path("runtime")
    database_url: str = "sqlite:///runtime/gridpulse.db"
    mlflow_uri: str = "sqlite:///runtime/mlflow.db"
    experiment: str = "gridpulse-demand"
    model_name: str = "gridpulse-de-demand"
    model_alias: str = "champion"
    max_mape: float = Field(20, gt=0)
    max_mae: float = Field(10000, gt=0)
    baseline_ratio: float = Field(1.05, gt=0)
    drift_threshold: float = Field(0.25, gt=0)
    performance_ratio: float = Field(1.5, gt=1)
    max_stale_hours: float = Field(3, gt=0)
    model_refresh_seconds: int = Field(30, ge=0)
    deployment_check_url: str | None = None
    mqtt_host: str = "localhost"
    mqtt_client_id: str = "gridpulse-ingestion"
    mqtt_port: int = 1883
    mqtt_topic: str = "gridpulse/telemetry/+/+"
    mqtt_ca: str | None = None
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    log_level: str = "INFO"
    unhealthy_file: Path = Path("/tmp/gridpulse-unhealthy")

    def prepare(self) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
