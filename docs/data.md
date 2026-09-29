# Data contracts and lifecycle

`gridpulse.data.schema.validate` rejects the **entire** batch before storage or training. No implicit
sorting, deduplication, gap filling, interpolation or partial-weather fallback occurs. Extra columns
are also rejected, so schema changes cannot silently alter the contract. Optional generation/price
fields may be null. Required fields must be finite; demand must be positive.

| Canonical field | Unit / meaning |
| --- | --- |
| timestamp | timezone-aware hour, normalized to UTC, strictly increasing and contiguous |
| demand | national load, MW |
| temperature / apparent_temperature | Celsius, Berlin weather proxy |
| wind | km/h at 10 m |
| cloud_cover | percent, 0–100 |
| solar_radiation | shortwave radiation, W/m² |
| generation / price | optional future extension columns; not forecasting targets |

OPSD adapter selects `DE_load_actual_entsoe_transparency` from the immutable 2020-10-06 release.
Demand and weather join one-to-one on UTC, and the entire requested inclusive date range must exist.
ENTSO-E uses DE_LU for its modern bidding-zone API; it requires `ENTSOE_API_KEY`. If quarter-hour
load is returned, the adapter requires all four samples per hour before averaging power in MW.
DE_LU includes Luxembourg and is not an identical historical boundary to OPSD Germany. Treat the
adapters as distinct sources and retrain/version separately. ENTSO-E prices are a future extension.

Open-Meteo requests explicit coordinates (Berlin 52.52, 13.41), UTC, variable names and km/h units.
Observed weather at the forecast origin is used. Future observed weather is never a feature.
For a national production forecast, regionally weighted weather and archived weather forecasts
would be needed. OPSD is historical, not a live feed. `GRIDPULSE_ENV=demo` explicitly permits
retrospective forecasts. Real development-mode inference and retraining enforce the configured
freshness limit. Historical acquisition/training intentionally do not compare 2019 data with today.

## Storage

`src/gridpulse/data/storage.py` defines tables through SQLAlchemy. Timestamps are canonical UTC ISO
strings, consistently normalized, for matching behavior in PostgreSQL and the SQLite fallback.
This is a portability tradeoff; a larger deployment should migrate to TIMESTAMPTZ with Alembic.

| Table | Key / index | Responsibility |
| --- | --- | --- |
| observations | (source, market, timestamp) primary key | validated canonical demand/weather; idempotent upsert |
| forecasts | (request_id, timestamp), index (model_version, timestamp) | immutable served forecasts, origin and features |
| telemetry | event_id, received_at index | duplicate-safe smart-meter/plant/edge kW observations |
| monitoring_reports | UUID primary key, creation time | actual PSI/accuracy reports and quality decisions |

MLflow owns its own tracking/registry tables. The local demo uses the same PostgreSQL database
for convenience; separate database identities/schemas are recommended beyond the demo. Artifact
bytes are served through MLflow from a Docker volume; clients do not need shared filesystem paths.
Native development uses `runtime/mlflow.db` and MLflow's local artifact store.

Acquisition retains downloaded raw files in `runtime/raw/` and normalized source CSVs in `runtime/`.
Snapshots have SHA256 sidecars. `GRIDPULSE_S3_BUCKET` and optional `GRIDPULSE_S3_ENDPOINT` enable
upload of the normalized snapshot under its content hash, using standard AWS credential resolution.
The S3 adapter is optional and has not been integration-tested against a provisioned bucket.
Dataset hashes, exact feature names/version, data windows, parameters and Git identity are logged
with every model. IEEE floating point and CSV/database round trips can change sub-micro-MW digits;
hashes represent the exact normalized training snapshot, not a semantic dataset identity.

No automatic retention deletes data. Back up PostgreSQL plus artifact volumes together, retain
champion/previous versions and their artifacts, and define retention before long-running use.
MQTT has a durable local SQLite publisher outbox, QoS1 broker sessions, and database deduplication.
After 24 hours, buffered events are explicitly rejected as too old. A poison message is logged and
acknowledged; a storage failure is not acknowledged and triggers reconnection/redelivery.

Sources: [OPSD release and attribution](https://data.open-power-system-data.org/time_series/2020-10-06/),
[Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api),
[ENTSO-E client](https://github.com/EnergieID/entsoe-py).
Respect upstream licenses/attribution and API usage limits when redistributing data.
