"""Deterministically export dashboards containing only real Prometheus metric queries."""

import json
from pathlib import Path


def dashboard(uid: str, title: str, queries: list[tuple[str, str, str]]) -> dict:
    panels = []
    for i, (name, expression, unit) in enumerate(queries):
        panels.append(
            {
                "id": i + 1,
                "title": name,
                "type": "timeseries",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "gridPos": {"x": (i % 2) * 12, "y": (i // 2) * 8, "w": 12, "h": 8},
                "targets": [
                    {
                        "refId": "A",
                        "expr": expression,
                        "legendFormat": "{{version}}{{pod}}{{feature}}",
                    }
                ],
                "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
            }
        )
    return {
        "uid": uid,
        "title": title,
        "schemaVersion": 41,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-30m", "to": "now"},
        "tags": ["gridpulse", "personal-project"],
        "panels": panels,
    }


service = [
    ("API request rate", "sum(rate(gridpulse_requests_total[2m]))", "reqps"),
    (
        "API p95 latency",
        "histogram_quantile(0.95, sum by (le) (rate(gridpulse_request_seconds_bucket[2m])))",
        "s",
    ),
    (
        "5xx error ratio",
        'sum(rate(gridpulse_requests_total{status=~"5.."}[2m])) / '
        "clamp_min(sum(rate(gridpulse_requests_total[2m])), 0.001)",
        "percentunit",
    ),
    ("Scrape health", 'up{job="gridpulse-api"}', "short"),
    (
        "API process CPU cores (Linux)",
        'rate(process_cpu_seconds_total{job="gridpulse-api"}[2m])',
        "short",
    ),
    ("API resident memory (Linux)", 'process_resident_memory_bytes{job="gridpulse-api"}', "bytes"),
    (
        "Kubernetes pod ready — needs kube-state-metrics",
        'kube_pod_status_ready{namespace="gridpulse",condition="true"}',
        "short",
    ),
    (
        "Kubernetes container restarts",
        'kube_pod_container_status_restarts_total{namespace="gridpulse"}',
        "short",
    ),
]
model = [
    (
        "Prediction distribution: hourly observations by MW bucket",
        "sum by (le, version) (increase(gridpulse_prediction_mw_bucket[5m]))",
        "short",
    ),
    ("Prediction volume", "sum by (version) (rate(gridpulse_prediction_mw_count[2m]))", "ops"),
    ("Rolling MAE — requires matched actuals", "gridpulse_model_mae_mw", "short"),
    ("Rolling RMSE — requires matched actuals", "gridpulse_model_rmse_mw", "short"),
    (
        "Rejected requests with missing features",
        "increase(gridpulse_missing_features_total[5m])",
        "short",
    ),
    ("Feature drift PSI — requires >=48 unique predictions", "gridpulse_drift_psi", "short"),
    ("Loaded model version (legend)", "gridpulse_model_info", "short"),
    ("Quality retraining requested", "gridpulse_retrain_requested", "short"),
]
if __name__ == "__main__":
    output = Path("monitoring/grafana/dashboards")
    output.mkdir(parents=True, exist_ok=True)
    for uid, title, queries in [
        ("gridpulse-service", "GridPulse | Service and infrastructure", service),
        ("gridpulse-model", "GridPulse | Model quality", model),
    ]:
        (output / f"{uid}.json").write_text(json.dumps(dashboard(uid, title, queries), indent=2))
