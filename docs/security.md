# Security boundary

This is a local personal-project deployment. Docker ports bind to 127.0.0.1. API, MLflow and MQTT
use HTTP/plain TCP inside the local demo network. Grafana's random administrator password and
PostgreSQL password are generated into ignored `.env`; they are never baked into an image or Git.
The MQTT anonymous listener is intentional for the isolated loopback demo.

The application image runs as UID/GID 10001. Kubernetes API pods have a read-only root filesystem,
drop all Linux capabilities, use RuntimeDefault seccomp, cannot escalate privilege, and do not mount
a service-account token. Writable runtime/cache mounts are ephemeral. kube-state-metrics has only
namespace-scoped list/watch access to pods. Resources and probes are explicit.

`uv.lock` pins transitive dependencies and hashes; installs use `uv sync --frozen`. Docker's Python
and uv bases are pinned by digest. The known vulnerable Debian PCRE package is explicitly updated.
CI uses pip-audit and Trivy; see `docs/verification.md` for the actual observed results. Scans are
point-in-time checks, not a guarantee. Refresh dependencies and base digests deliberately.

For remote use, terminate API/MLflow TLS at an authenticated ingress or reverse proxy, restrict
registry writes to the promotion controller, use separate read/write database roles, network
policies, secret rotation and persistent backups. Configure MQTT server certificates, authenticated
users, topic ACLs and port 8883; the client already supports `GRIDPULSE_MQTT_CA`,
`GRIDPULSE_MQTT_USERNAME` and `GRIDPULSE_MQTT_PASSWORD` with certificate validation enabled.
These remote security integrations are documented requirements, not tested deployment claims.
Do not expose the unauthenticated local API or MLflow server to the Internet.

Kubernetes references an existing Secret named `gridpulse-secrets`; `scripts/deploy_local.py` creates
it from `.env` via stdin without logging its payload. Neither raw manifests nor Helm values embed
credentials. The demo shares a database owner role; it does not claim fine-grained DB least privilege.
