# Demo and operations runbook

## Native Windows / Linux

```sh
uv python install 3.12
uv sync --frozen
uv run gridpulse demo
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, `uv run gridpulse smoke` exercises readiness and the complete 24-hour response.
The native demo needs no passwords, Docker or external API. It uses SQLite and explicitly synthetic
data. Run `uv run mlflow ui --backend-store-uri sqlite:///runtime/mlflow.db --port 5001` to inspect it.
Do not mix native and Compose MLflow stores: each has independent version numbering.

## Full local stack

```sh
uv run python scripts/init_env.py
docker compose up -d --build
docker compose ps
docker compose exec -T api gridpulse smoke --url http://localhost:8000
```

If `.env` exists, preserve it and supply missing `POSTGRES_PASSWORD` and `GRAFANA_PASSWORD` yourself.
Initial image pulls can take several minutes. `bootstrap` runs real training **only if there is no
champion**. It is a runtime demo job, never a Docker build step. API/ingestion/monitor wait for it.
`docker compose logs bootstrap` shows the real run and promotion outcome. Named volumes survive
`docker compose down`. Do not delete volumes unless you intend to erase local observations/models.

| Component | Local address |
| --- | --- |
| API / OpenAPI | http://localhost:8000/docs |
| MLflow | http://localhost:5000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 — admin, password from ignored `.env` |
| PostgreSQL | localhost:5432, database/user gridpulse |
| MQTT | localhost:1883 |

Grafana provisions **Service and infrastructure** and **Model quality** in the GridPulse AI folder.
The model dashboard stays empty for accuracy/drift until there are enough distinct forecasts and
matching observations. Populate honest retrospective measurements:

```sh
docker compose cp api:/app/runtime/synthetic.csv runtime/synthetic.csv
uv run python scripts/replay.py --days 14
docker compose exec -T api gridpulse monitor
```

The replay uses actual predictions on stored synthetic held-out labels; it does not fabricate
Prometheus values. KPI values appear after the next 10-second scrape. The current 24-hour forecast
has no labels yet, so it is excluded from accuracy calculations. Live MQTT counts can be checked
with `docker compose exec -T postgres psql -U gridpulse -d gridpulse -c "select kind,count(*) from telemetry group by kind"`.

## Public-data run

```sh
uv run gridpulse data --source opsd --start 2019-01-01 --end 2019-03-31
```

Set `GRIDPULSE_DATA_SOURCE=opsd`, `GRIDPULSE_MODEL_NAME=gridpulse-de-demand-opsd` and
`GRIDPULSE_ENV=demo` in a separate environment, then `uv run gridpulse train --promote`.
On PowerShell use `$env:GRIDPULSE_DATA_SOURCE='opsd'`; on Bash use `export GRIDPULSE_DATA_SOURCE=opsd`.
Use a separate model name to preserve the synthetic champion and keep provenance unambiguous.
For ENTSO-E, set `ENTSOE_API_KEY` and choose `--source entsoe` with explicit dates. No token is needed
for OPSD/Open-Meteo. API outages raise clear failures; there is no silent switch to synthetic data.

## Kubernetes and Helm

Install Docker, kubectl, Helm 3 and kind. Start Compose first; it supplies PostgreSQL, MLflow and MQTT.

```sh
uv run python scripts/deploy_local.py
uv run gridpulse smoke --url http://localhost:18000
uv run python scripts/k8s_recovery.py
```

The script creates only the dedicated `kind-gridpulse` context / `gridpulse` namespace, loads the
local image, creates a Secret through stdin and deploys the chart. Windows/macOS use Docker Desktop's
`host.docker.internal`; Linux should use `--ci`, which attaches the kind node to the Compose network
and supplies container IPs. For this Linux path set `MLFLOW_ALLOWED_HOSTS=*` in the local `.env`
before starting Compose; the server still has a loopback-only published port. It is a demo setting.

API is exposed on loopback port 18000; namespace-scoped kube-state-metrics uses 18080. Prometheus's
two optional Kubernetes scrape targets remain down when the cluster is not running. Their dashboard
panels show no data rather than invented pod metrics. Process CPU/memory panels come from the real
Linux API process. This is not a complete node-level cluster monitoring installation.

For an existing cluster, provision accessible PostgreSQL/MLflow/MQTT and `gridpulse-secrets` in the
target namespace, then run:

```sh
helm upgrade --install gridpulse deploy/helm/gridpulse -n gridpulse --create-namespace \
  -f deploy/helm/gridpulse/values-demo.yaml \
  --set image.repository=YOUR_REGISTRY/gridpulse-ai --set image.tag=YOUR_COMMIT_SHA \
  --set config.GRIDPULSE_MLFLOW_URI=https://YOUR_MLFLOW \
  --set config.GRIDPULSE_MQTT_HOST=YOUR_BROKER --wait --timeout 5m
```

Those uppercase values are deployment-specific inputs, not provisioned external services. Raw
`deploy/k8s/rendered-dev.yaml` is a checked-in rendering of the dev chart. Apply it with
`kubectl -n gridpulse apply -f deploy/k8s/rendered-dev.yaml` after creating the namespace/Secret.
Helm is the recommended owner; do not manage the same resources concurrently through both methods.

After rebuilding the same local image tag, run `kind load docker-image gridpulse-ai:0.1.0 --name gridpulse`
and `kubectl --context kind-gridpulse -n gridpulse rollout restart deployment/gridpulse-api deployment/gridpulse-ingestion`.
Released images use immutable commit tags rather than repeatedly replacing a tag.

## Drift, degradation and retraining

PSI uses training quantile bins with infinite outer boundaries. For reference fraction p_i and
current fraction q_i, `PSI = sum((q_i - p_i) * ln(q_i / p_i))`. Counts receive epsilon smoothing.
Constant reference features get a narrow central bin, so novel values are not hidden. A deterministic
sample from all training horizons represents the reference; it is not a random train/test split.

Monitoring considers up to 720 recent forecast rows for the current model and deduplicates repeated
requests for the same origin/target. At least 48 unique predictions are required. MAE/RMSE join
predictions with observations by source, market and target timestamp. Reported `matched_count`
distinguishes available labels from total predictions. Seasonal/calendar changes can cause high PSI
without accuracy loss; thresholds are demonstration policy, not calibrated energy-market alarms.

```sh
docker compose exec -T api gridpulse monitor
docker compose exec -T api gridpulse retrain --trigger quality
docker compose exec -T api gridpulse retrain --trigger scheduled
```

The quality trigger exits without training if neither PSI nor performance policy requests it.
Scheduled training always validates stored data and trains a candidate; it does not invent newly
arrived observations. Ingest a new complete window first for a meaningful updated model.

Compose's scheduler persists a seven-day cadence with a 24-hour quality-trigger cooldown.
The Helm chart offers a Monday 03:00 UTC training CronJob and a five-minute monitoring CronJob.
Enable **one** promotion controller only. The local values keep the Helm training CronJob disabled
because Compose owns it. `concurrencyPolicy: Forbid` prevents overlap within a CronJob, but is not a
distributed lock across independent CLIs or schedulers. Current limitation: no distributed registry
transaction; serialize manual and scheduled promotions operationally.

## Promotion and rollback

Candidates must have finite MAE/RMSE/MAPE, meet configurable validation MAE/MAPE limits and a weekly
baseline ratio, load from the registry, match the feature contract, and produce 24 positive finite
forecasts. Test metrics are recorded for honest auditing but never used to choose the candidate.
Successful candidates receive `staging`, then `champion`; old champion receives `previous`.

```sh
uv run python scripts/failure_demo.py
uv run gridpulse rollback
```

The failure script creates a real candidate, proves a strict gate rejects it without changing the
champion, injects a post-promotion failure, and asserts the old champion is restored. It uses the
native registry by default. `gridpulse rollback` loads/smoke-tests the actual previous artifact
before restoring its alias. API refreshes the alias periodically and swaps only a successfully loaded
bundle; every response reports the version actually used.

Set `GRIDPULSE_DEPLOYMENT_CHECK_URL` on an established training controller to execute an HTTP
forecast after promotion. Failed version adoption or forecast response restores the prior alias.
Do not enable this on first bootstrap before API starts (circular dependency). With multiple API
replicas a single load-balanced check does not prove every replica has switched; production rollout
coordination is a future hardening task.

Application-image rollback uses `helm rollback gridpulse REVISION -n NAMESPACE --wait`. The deployment
workflow deploys/smokes a test namespace before the demo namespace; it uses Helm atomic rollback
for rollout failures and explicitly restores the prior revision if smoke fails.

## Failure demonstrations

| Failure | Executable evidence / behavior |
| --- | --- |
| MQTT broker unavailable | stop this demo's mqtt service; publisher retains SQLite outbox, subscriber retries; restart mqtt to drain |
| No telemetry | `gridpulse_telemetry_stale` becomes 1 after the configured age; feed metrics remain separate from national demand |
| Upstream unavailable | `tests/test_sources.py` raises rather than returning partial data |
| Schema change / gap / duplicate | `tests/test_data.py` rejects whole batch |
| Missing inference field | `tests/test_api.py` verifies 422 plus missing-feature counter |
| Unhealthy API | `scripts/k8s_recovery.py` creates a liveness-failure marker, observes restart and Ready; startup clears only that marker |
| Bad candidate | real-registry rejection tests and failure_demo.py |
| Drift / degradation | replay, monitor, inspect separate drifted/degraded flags; Prometheus alert; quality retraining command |
| Unhealthy promoted model | failure_demo.py restores previous alias; optional real HTTP post-check |

## CI/CD boundaries

`ci.yml` runs lint, tests, pip-audit, image build/Trivy, Compose integration, Helm/kind deployment and
recovery. Tests use small real MLflow fixtures; release model training is separate. Only a passing
main-branch push publishes a SHA-tagged GHCR image. `deploy.yml` is manually dispatched against a
configured `demo` GitHub environment. It requires KUBE_CONFIG_BASE64, a pre-provisioned Secret in
both target namespaces, image-pull access, and MLFLOW_URI/MQTT_HOST variables. Restrict the deploy
environment and only select a passing CI image SHA. `retrain.yml` requires registry/DB/API access.

No remote repository or CI runner was supplied with this workspace. Local equivalents are tested;
an actual hosted GitHub Actions run and remote deployment must not be claimed until configured.
