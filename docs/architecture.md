# Architecture decisions

The modular Python package owns validation, features, training, registry operations and monitoring.
FastAPI and the MQTT subscriber are separate processes using that package. PostgreSQL stores
observations, telemetry, forecasts and monitoring reports. MLflow stores experiment/registry metadata
and artifacts; optional S3 keeps immutable raw inputs. SQLite and local artifact files support a
credential-free native demo.

Germany is one market with one MW demand target. Timestamps are UTC; calendar features use
Europe/Berlin, including daylight saving and German national holidays. Future price/generation are
nullable schema fields, not implemented forecasting targets.

The model shares trees across 24 direct horizons. At each origin it sees only the preceding 168
hours, origin weather, target calendar and horizon. It never reads realized future weather or demand.
Daily origin blocks are split chronologically with disjoint target windows. This makes training and
serving share exactly the same feature builder. Weather persistence is deliberately conservative;
archived forecasts would be needed to evaluate future weather inputs honestly.

XGBoost is a strong tabular baseline, trains quickly, exports feature importance, and is simpler to
operate than a deep sequence model. It is not universally superior. LSTM/Transformer comparisons
are future experiments, not claims in this repository. Weekly persistence is the explicit baseline.

PostgreSQL provides transactions and timestamp joins for delayed-label monitoring. Object storage
separates immutable raw bytes/artifacts from relational operational state. MLflow links real runs,
data hashes, model artifacts and registry versions. Aliases represent staging/champion/previous.
FastAPI provides typed contracts and health endpoints. Kubernetes demonstrates process recovery and
resource management; Helm makes environment configuration repeatable. Neither is necessary for a
single developer's native demo. Prometheus/Grafana connect runtime counters to dashboards/alerts.
MQTT demonstrates separate edge telemetry ingestion; device kW is never mixed into national MW.

Distribution drift is not proof of accuracy loss. Drift compares features; performance joins
forecasts to later observed labels. Both can request retraining, but validation gates must still pass.
Rollback preserves an approved previous model. No Kafka, Spark, Airflow, feature store, service mesh,
multi-market system, price model or renewable model is introduced without a concrete need.
