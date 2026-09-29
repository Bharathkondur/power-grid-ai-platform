import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from gridpulse.config import Settings
from gridpulse.data.schema import DataQualityError, validate
from gridpulse.data.storage import Store, reports, telemetry
from gridpulse.models.registry import alias_version, load
from gridpulse.monitoring.metrics import Metrics
from gridpulse.utils.logging import configure

logger = logging.getLogger("gridpulse.api")


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    timestamp: AwareDatetime
    demand: float = Field(gt=0)
    temperature: float = Field(ge=-90, le=65)
    apparent_temperature: float
    wind: float = Field(ge=0)
    cloud_cover: float = Field(ge=0, le=100)
    solar_radiation: float = Field(ge=0)
    generation: float | None = None
    price: float | None = None


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history: list[Observation] = Field(min_length=168, max_length=168)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[ForecastRequest] = Field(min_length=1, max_length=16)


class Prediction(BaseModel):
    prediction: float
    target: str = "demand_mw"
    forecast_timestamp: AwareDatetime
    model_version: str
    data_timestamp: AwareDatetime


class ForecastResponse(BaseModel):
    request_id: str
    model_version: str
    source: str
    forecasts: list[Prediction]


class ModelManager:
    def __init__(self, settings: Settings, metrics: Metrics):
        self.settings, self.metrics = settings, metrics
        self.bundle = None
        self.last_attempt = float("-inf")
        self.lock = threading.Lock()

    def refresh(self):
        with self.lock:
            if time.monotonic() - self.last_attempt < self.settings.model_refresh_seconds:
                return self.bundle
            self.last_attempt = time.monotonic()
            try:
                version = alias_version(self.settings, self.settings.model_alias)
                if version and (self.bundle is None or version != self.bundle.version):
                    candidate = load(self.settings, version)
                    self.bundle = candidate  # Atomic swap only after artifact smoke test.
                    self.metrics.model.clear()
                    self.metrics.model.labels(version=version).set(1)
            except Exception:
                logger.exception("model_refresh_failed", extra={"error_category": "registry"})
            return self.bundle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    metrics = Metrics()
    manager = ModelManager(settings, metrics)

    @asynccontextmanager
    async def lifespan(app):
        configure(settings.log_level)
        settings.unhealthy_file.unlink(missing_ok=True)
        app.state.store = Store(settings)
        manager.refresh()
        yield
        app.state.store.engine.dispose()

    app = FastAPI(title="GridPulse AI", version="0.1.0", lifespan=lifespan)
    app.state.manager, app.state.metrics = manager, metrics

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        except Exception:
            logger.exception(
                "request_failed",
                extra={"request_id": request.state.request_id, "error_category": "internal"},
            )
            return JSONResponse(
                status_code=503,
                content={"error": "service_unavailable", "request_id": request.state.request_id},
            )
        finally:
            route = request.scope.get("route")
            route_name = route.path if route else "unmatched"
            metrics.requests.labels(route=route_name, status=str(status)).inc()
            metrics.latency.labels(route=route_name).observe(time.perf_counter() - start)
            logger.info(
                "http_request",
                extra={
                    "request_id": request.state.request_id,
                    "model_version": manager.bundle.version if manager.bundle else None,
                },
            )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        metrics.invalid.inc()
        if any(error["type"] == "missing" for error in exc.errors()):
            metrics.missing.inc()
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_request",
                "request_id": request.state.request_id,
                "details": str(exc),
            },
        )

    @app.exception_handler(DataQualityError)
    async def invalid_data(request, exc):
        metrics.invalid.inc()
        return JSONResponse(
            status_code=422,
            content={
                "error": "data_quality",
                "request_id": request.state.request_id,
                "details": str(exc),
            },
        )

    @app.get("/health")
    def health():
        if settings.unhealthy_file.exists():
            return JSONResponse(status_code=503, content={"status": "injected_unhealthy"})
        return {"status": "alive"}

    @app.get("/ready")
    def ready(request: Request):
        bundle = manager.refresh()
        try:
            with request.app.state.store.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "database_unavailable"})
        if bundle is None:
            return JSONResponse(status_code=503, content={"status": "model_unavailable"})
        return {"status": "ready", "model_version": bundle.version}

    @app.get("/v1/model")
    def model_info():
        bundle = manager.refresh()
        if bundle is None:
            return JSONResponse(status_code=503, content={"error": "model_unavailable"})
        return {
            "model_version": bundle.version,
            "target": "demand_mw",
            "source": bundle.manifest["source"],
            "feature_version": bundle.manifest["feature_version"],
            "data_hash": bundle.manifest["data_hash"],
        }

    def predict(payload: ForecastRequest, request: Request, request_id: str):
        bundle = manager.refresh()
        if bundle is None:
            return JSONResponse(
                status_code=503, content={"error": "model_unavailable", "request_id": request_id}
            )
        history = pd.DataFrame([row.model_dump() for row in payload.history])
        now = (
            datetime.now(UTC)
            if settings.env != "demo" and bundle.manifest["source"] != "synthetic"
            else None
        )
        history = validate(history, min_rows=168, now=now, max_stale_hours=settings.max_stale_hours)
        features, values = bundle.forecast(history)
        origin = history.timestamp.iloc[-1]
        predictions = [
            dict(
                prediction=float(value),
                target="demand_mw",
                model_version=bundle.version,
                data_timestamp=origin.isoformat(),
                forecast_timestamp=(origin + pd.Timedelta(hours=i + 1)).isoformat(),
            )
            for i, value in enumerate(values)
        ]
        request.app.state.store.save_forecast(
            request_id,
            bundle.manifest["source"],
            bundle.version,
            origin.isoformat(),
            features,
            predictions,
        )
        metrics.inferences.labels(version=bundle.version).inc()
        for value in values:
            metrics.predictions.labels(version=bundle.version).observe(value)
        return {
            "request_id": request_id,
            "model_version": bundle.version,
            "source": bundle.manifest["source"],
            "forecasts": predictions,
        }

    @app.post("/v1/forecast", response_model=ForecastResponse)
    def forecast(payload: ForecastRequest, request: Request):
        return predict(payload, request, request.state.request_id)

    @app.post("/v1/batch-forecast", response_model=list[ForecastResponse])
    def batch(payload: BatchRequest, request: Request):
        output = []
        for i, item in enumerate(payload.requests):
            result = predict(item, request, f"{request.state.request_id}-{i}")
            if isinstance(result, Response):
                return result
            output.append(result)
        return output

    @app.get("/metrics", include_in_schema=False)
    def exposition(request: Request):
        with request.app.state.store.engine.connect() as conn:
            latest = (
                conn.execute(select(reports).order_by(reports.c.created_at.desc()).limit(1))
                .mappings()
                .first()
            )
            last_event = conn.execute(
                select(telemetry.c.received_at).order_by(telemetry.c.received_at.desc()).limit(1)
            ).scalar()
        if latest:
            report = latest["report"]
            version = latest["model_version"]
            for feature, score in report["psi"].items():
                metrics.drift.labels(feature=feature, version=version).set(score)
            if report["performance"]:
                metrics.mae.labels(version=version).set(report["performance"]["mae"])
                metrics.rmse.labels(version=version).set(report["performance"]["rmse"])
            metrics.quality.set(int(report["retrain_requested"]))
        age = (
            (datetime.now(UTC) - datetime.fromisoformat(last_event)).total_seconds()
            if last_event
            else None
        )
        metrics.telemetry_stale.set(int(age is None or age > settings.max_stale_hours * 3600))
        if age is not None:
            metrics.telemetry_age.set(max(0, age))
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
