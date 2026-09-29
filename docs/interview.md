# Technical interview preparation

## Why XGBoost instead of an LSTM or Transformer?

`models/training.py` fits 300-tree regressors at two depths on lag/calendar/weather features. It
requires no GPU, saves a native artifact via MLflow and logs feature importance. It is manageable
for a first operational system, not proof that sequence models are inferior. The synthetic test
slightly loses to weekly persistence; the public-data window improves on it. Both are disclosed.

## How did you prevent leakage?

`features.at_origin` sees only the previous 168 hours. The 24 target rows share those observations;
only calendar and horizon refer to the future. Future realized weather is excluded. `supervised`
creates disjoint daily target blocks and `split_points` divides them chronologically. Tests mutate
future demand/weather and verify earlier features remain unchanged. Validation selects depth;
test is an audit. Later origins can use labels that have actually arrived by that later time.

## How are data, features and models versioned?

The run manifest records a normalized dataset SHA256, data/split windows, exact feature columns,
`direct24-origin-v1`, parameters, source, Git identity, run ID and actual registered version. Snapshot
hash sidecars are retained. Images accept a `VCS_REF` build argument. Uncommitted code is explicitly
labeled rather than assigned a fabricated commit. Native and Compose registries are independent.

## What happens when the upstream feed stops?

HTTP failures propagate; incomplete requested windows are rejected, never silently replaced with
synthetic data. Real-source live inference/retraining enforces freshness. MQTT is a separate kW
stream: publisher SQLite outbox, QoS1 acknowledgements, retry, subscriber persist-before-ack and
event-ID deduplication. The API exposes time since last telemetry plus a stale status.

## How does the API know which version served a forecast?

`ModelManager` loads and smoke-tests an immutable Bundle before swapping its reference. A prediction
keeps that bundle locally and records its version in every response and persisted row. It does not
ask the registry again after prediction, so an alias change cannot mislabel an in-flight response.

## How is promotion decided?

`acceptance` checks finite metrics, configured validation MAE/MAPE and a permitted weekly-baseline
ratio. `load` validates feature version, reloads the actual artifact and checks 24 positive finite
outputs. A passing candidate receives staging/champion aliases; previous is retained. Optional HTTP
deployment checks verify adoption and serving. Failed checks restore the previous alias. Tests and
`scripts/failure_demo.py` exercise rejection and post-promotion failure against real MLflow stores.

## What is infrastructure monitoring versus ML monitoring?

Request counters, latency histograms, errors, Linux process CPU/RSS and Kubernetes ready/restart
metrics describe the runtime. Prediction distribution/count, loaded version, missing-field rejects,
PSI and delayed-label MAE/RMSE describe the model/data. Dashboard JSON uses those actual metrics.
No labels means no accuracy series, not a zero or fabricated result.

## How do drift and degradation differ?

`monitoring/quality.py` compares current and training feature distributions with quantile-bin PSI.
It separately joins predictions with actual observations to measure error. The replay showed high
seasonal PSI without crossing the degradation threshold. Either can request retraining, but the
candidate must still pass the gate. PSI is a review signal, not causal proof of lost accuracy.

## How does Kubernetes recover an unhealthy inference service?

The Helm deployment uses startup, readiness and liveness probes. `/ready` checks model and DB.
`scripts/k8s_recovery.py` creates a specific health-failure marker, watches restartCount increase,
and verifies Ready afterwards. Startup clears that test marker. This was demonstrated locally on
kind, and is not a claim of cloud-fleet high availability.

## How would you support multiple markets?

Storage/model metadata includes market/source, but config deliberately supports DE only. Expansion
requires explicit timezone/holiday rules, market boundaries, regional weather, independent registry
names, thresholds and backtests. I would introduce those contracts before pooling different targets.

## How would you secure MQTT and API traffic?

Current published ports are loopback-only, images non-root and Kubernetes uses Secrets with reduced
pod privileges. MQTT is anonymous/plaintext for this isolated demo. CA/username/password client
hooks exist, but a remote deployment also needs broker TLS and ACLs, authenticated API/MLflow ingress,
separate DB roles and secret rotation. Those external integrations have not been demonstrated.

## What changes for a real production energy operator?

Authoritative live feeds with revisions, archived forecast vintages, regional weather, multiple
seasons and rolling backtests come first. Add uncertainty and 23/25-hour market-day semantics rather
than this fixed rolling 24-hour horizon. Calibrate seasonal drift, coordinate per-replica rollout,
implement distributed promotion locks, migrations, retention, backups, authentication/TLS, audit and
recovery objectives. This portfolio demonstrates a lifecycle, not readiness to operate a real grid.

## CV positioning

Always call this a personal project and specify local Docker/kind for deployments. Do not claim
customers, employment impact, hosted CI success or remote production deployment. The verification
record identifies demonstrated functionality. Final CV claims should wait until the chosen external
CI/deployment definition of done is satisfied too.
