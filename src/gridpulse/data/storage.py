import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import (
    JSON,
    Column,
    Float,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from gridpulse.config import Settings
from gridpulse.data.schema import OPTIONAL, REQUIRED, validate

metadata = MetaData()
observations = Table(
    "observations",
    metadata,
    Column("source", String, primary_key=True),
    Column("market", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    *[Column(name, Float, nullable=name in OPTIONAL) for name in REQUIRED[1:] + OPTIONAL],
)
forecasts = Table(
    "forecasts",
    metadata,
    Column("request_id", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("origin", String, nullable=False),
    Column("source", String, nullable=False),
    Column("market", String, nullable=False),
    Column("model_version", String, nullable=False),
    Column("prediction", Float, nullable=False),
    Column("features", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)
Index("ix_forecasts_version_time", forecasts.c.model_version, forecasts.c.timestamp)
reports = Table(
    "monitoring_reports",
    metadata,
    Column("id", String, primary_key=True),
    Column("created_at", String, nullable=False),
    Column("model_version", String, nullable=False),
    Column("report", JSON, nullable=False),
)
telemetry = Table(
    "telemetry",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("timestamp", String, nullable=False),
    Column("received_at", String, nullable=False),
    Column("device_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("power_kw", Float, nullable=False),
)
Index("ix_telemetry_received_at", telemetry.c.received_at)


def utc_string(value: Any) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat()


class Store:
    def __init__(self, settings: Settings):
        settings.prepare()
        self.settings = settings
        self.engine = create_engine(settings.database_url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def insert(self, table: Table, rows: list[dict], *, immutable: bool = False) -> None:
        if not rows:
            return
        factory = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        with self.engine.begin() as connection:
            # Small bounded batches also stay below SQLite's parameter limit.
            for start in range(0, len(rows), 100):
                statement = factory(table).values(rows[start : start + 100])
                statement = (
                    statement.on_conflict_do_nothing()
                    if immutable
                    else (
                        statement.on_conflict_do_update(
                            index_elements=[c.name for c in table.primary_key],
                            set_={
                                c.name: statement.excluded[c.name]
                                for c in table.c
                                if not c.primary_key
                            },
                        )
                    )
                )
                connection.execute(statement)

    def save_data(self, frame: pd.DataFrame, source: str) -> None:
        normalized = validate(frame).reindex(columns=REQUIRED + OPTIONAL)
        normalized.timestamp = normalized.timestamp.map(utc_string)
        rows = normalized.astype(object).where(pd.notnull(normalized), None).to_dict("records")
        self.insert(observations, [dict(r, source=source, market="DE") for r in rows])

    def read_data(self, source: str) -> pd.DataFrame:
        query = (
            select(observations)
            .where(observations.c.source == source, observations.c.market == "DE")
            .order_by(observations.c.timestamp)
        )
        with self.engine.connect() as conn:
            result = pd.read_sql(query, conn).drop(columns=["source", "market"])
        result.timestamp = pd.to_datetime(result.timestamp, utc=True)
        return validate(result)

    def save_forecast(
        self,
        request_id: str,
        source: str,
        version: str,
        origin: str,
        features: pd.DataFrame,
        values: list[dict],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.insert(
            forecasts,
            [
                dict(
                    request_id=request_id,
                    source=source,
                    market="DE",
                    model_version=version,
                    origin=origin,
                    timestamp=v["forecast_timestamp"],
                    prediction=v["prediction"],
                    features=features.iloc[i].to_dict(),
                    created_at=now,
                )
                for i, v in enumerate(values)
            ],
            immutable=True,
        )

    def archive(self, path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.settings.s3_bucket:
            import boto3

            boto3.client("s3", endpoint_url=self.settings.s3_endpoint).upload_file(
                str(path), self.settings.s3_bucket, f"raw/{digest}/{path.name}"
            )
        manifest = path.with_suffix(path.suffix + ".sha256.json")
        manifest.write_text(json.dumps({"sha256": digest, "file": path.name}), encoding="utf-8")
        return digest
