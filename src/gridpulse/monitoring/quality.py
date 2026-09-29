import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import select

from gridpulse.config import Settings
from gridpulse.data.storage import Store, forecasts, observations, reports
from gridpulse.models.registry import load, promote
from gridpulse.models.training import metrics, train


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Quantile-bin PSI, epsilon-smoothed; explicit tails include out-of-range values."""
    reference, current = np.asarray(reference, dtype=float), np.asarray(current, dtype=float)
    if (
        not len(reference)
        or not len(current)
        or not np.isfinite(reference).all()
        or not np.isfinite(current).all()
    ):
        raise ValueError("PSI requires non-empty finite samples")
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) == 1:
        # Isolate a constant training value so novel values produce an actual signal.
        center = edges[0]
        tolerance = max(abs(center) * 1e-6, 1e-6)
        edges = np.array([-np.inf, center - tolerance, center + tolerance, np.inf])
    else:
        edges[0], edges[-1] = -np.inf, np.inf
    expected = np.histogram(reference, edges)[0].astype(float) + 1e-6
    actual = np.histogram(current, edges)[0].astype(float) + 1e-6
    expected, actual = expected / expected.sum(), actual / actual.sum()
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def monitor(settings: Settings, minimum_predictions: int = 48) -> dict:
    store, bundle = Store(settings), load(settings)
    query = (
        select(forecasts)
        .where(
            forecasts.c.model_version == bundle.version,
            forecasts.c.source == bundle.manifest["source"],
        )
        .order_by(forecasts.c.created_at.desc())
        .limit(24 * 30)
    )
    with store.engine.connect() as conn:
        rows = pd.read_sql(query, conn)
        actual = pd.read_sql(
            select(observations.c.timestamp, observations.c.demand).where(
                observations.c.source == bundle.manifest["source"], observations.c.market == "DE"
            ),
            conn,
        )
    # Repeated smoke/API calls for the same origin must not inflate sample size.
    if len(rows):
        rows = rows.drop_duplicates(["origin", "timestamp"])
    reference = bundle.manifest["baseline_features"]
    scores = {}
    performance = None
    matched_count = 0
    if len(rows) >= minimum_predictions:
        current = pd.DataFrame(rows.features.tolist())
        scores = {
            name: psi(np.array(reference[name]), current[name].to_numpy())
            for name in current.columns
        }
        joined = rows.merge(actual, on="timestamp", how="inner", validate="many_to_one")
        matched_count = len(joined)
        if matched_count >= minimum_predictions:
            performance = metrics(joined.demand.to_numpy(), joined.prediction.to_numpy())
    degraded = bool(
        performance
        and performance["mae"] > bundle.manifest["validation"]["mae"] * settings.performance_ratio
    )
    drifted = bool(scores and max(scores.values()) > settings.drift_threshold)
    report = {
        "psi": scores,
        "performance": performance,
        "prediction_count": len(rows),
        "matched_count": matched_count,
        "drifted": drifted,
        "degraded": degraded,
        "retrain_requested": drifted or degraded,
        "status": "measured" if scores else "insufficient_predictions",
    }
    store.insert(
        reports,
        [
            dict(
                id=uuid.uuid4().hex,
                created_at=datetime.now(UTC).isoformat(),
                model_version=bundle.version,
                report=report,
            )
        ],
    )
    return report


def retrain(settings: Settings, trigger: str) -> dict:
    if trigger == "quality":
        report = monitor(settings)
        if not report["retrain_requested"]:
            return {"trigger": trigger, "trained": False, "reason": report["status"]}
    data = Store(settings).read_data(settings.data_source)
    # Real online retraining must not accept a feed that has stopped updating.
    if settings.env != "demo" and settings.data_source != "synthetic":
        from gridpulse.data.schema import validate

        validate(data, now=datetime.now(UTC), max_stale_hours=settings.max_stale_hours)
    manifest = train(data, settings, settings.data_source)
    outcome = promote(settings, manifest["model_version"])
    return {
        "trigger": trigger,
        "trained": True,
        "model_version": manifest["model_version"],
        "promotion": outcome,
    }
