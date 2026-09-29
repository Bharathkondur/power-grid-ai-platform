from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry(auto_describe=True)
        from prometheus_client import GCCollector, PlatformCollector, ProcessCollector

        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        GCCollector(registry=self.registry)
        self.requests = Counter(
            "gridpulse_requests_total", "HTTP requests", ["route", "status"], registry=self.registry
        )
        self.latency = Histogram(
            "gridpulse_request_seconds", "HTTP latency", ["route"], registry=self.registry
        )
        self.inferences = Counter(
            "gridpulse_inferences_total", "24-hour forecasts", ["version"], registry=self.registry
        )
        self.predictions = Histogram(
            "gridpulse_prediction_mw",
            "Predicted demand MW",
            ["version"],
            buckets=(10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 100000),
            registry=self.registry,
        )
        self.invalid = Counter(
            "gridpulse_invalid_requests_total", "Invalid inputs", registry=self.registry
        )
        self.missing = Counter(
            "gridpulse_missing_features_total",
            "Requests rejected for missing fields",
            registry=self.registry,
        )
        self.model = Gauge(
            "gridpulse_model_info", "Currently loaded version", ["version"], registry=self.registry
        )
        self.mae = Gauge(
            "gridpulse_model_mae_mw",
            "Delayed-label rolling MAE",
            ["version"],
            registry=self.registry,
        )
        self.rmse = Gauge(
            "gridpulse_model_rmse_mw",
            "Delayed-label rolling RMSE",
            ["version"],
            registry=self.registry,
        )
        self.drift = Gauge(
            "gridpulse_drift_psi",
            "Population stability index",
            ["feature", "version"],
            registry=self.registry,
        )
        self.quality = Gauge(
            "gridpulse_retrain_requested",
            "Monitoring policy requested retraining",
            registry=self.registry,
        )
        self.telemetry_age = Gauge(
            "gridpulse_telemetry_age_seconds",
            "Seconds since last received MQTT observation",
            registry=self.registry,
        )
        self.telemetry_stale = Gauge(
            "gridpulse_telemetry_stale", "MQTT feed absent or stale", registry=self.registry
        )
