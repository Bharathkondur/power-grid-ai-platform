import time
from dataclasses import dataclass

import httpx
import mlflow
import mlflow.xgboost
import numpy as np
import pandas as pd
from mlflow.exceptions import MlflowException

from gridpulse.config import Settings
from gridpulse.features import FEATURE_VERSION, at_origin
from gridpulse.models.training import load_manifest


def client(settings: Settings) -> mlflow.MlflowClient:
    mlflow.set_tracking_uri(settings.mlflow_uri)
    return mlflow.MlflowClient()


def alias_version(settings: Settings, alias: str) -> str | None:
    try:
        aliases = client(settings).get_registered_model(settings.model_name).aliases
        value = aliases.get(alias)
        return str(value) if value is not None else None
    except MlflowException as exc:
        if exc.error_code == "RESOURCE_DOES_NOT_EXIST":
            return None
        raise


@dataclass(frozen=True)
class Bundle:
    version: str
    model: object
    manifest: dict

    def forecast(self, history: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        features = at_origin(history)
        if list(features.columns) != self.manifest["features"]:
            raise ValueError("Feature contract differs from registered model")
        predictions = np.asarray(self.model.predict(features), dtype=float)
        if (
            predictions.shape != (24,)
            or not np.isfinite(predictions).all()
            or (predictions <= 0).any()
        ):
            raise ValueError("Model produced invalid demand predictions")
        return features, predictions


def load(settings: Settings, version: str | None = None) -> Bundle:
    version = version or alias_version(settings, settings.model_alias)
    if version is None:
        raise ValueError(f"No approved model alias {settings.model_alias}")
    manifest = load_manifest(settings, version)
    if manifest["feature_version"] != FEATURE_VERSION:
        raise ValueError("Incompatible feature version")
    model = mlflow.xgboost.load_model(f"models:/{settings.model_name}/{version}")
    bundle = Bundle(version, model, manifest)
    history = pd.DataFrame(manifest["smoke_history"])
    history.timestamp = pd.to_datetime(history.timestamp, utc=True)
    bundle.forecast(history)
    return bundle


def acceptance(manifest: dict, settings: Settings) -> list[str]:
    reasons = []
    for group in ("validation", "test", "baseline_validation", "baseline_test"):
        for metric in ("mae", "rmse", "mape"):
            value = manifest.get(group, {}).get(metric)
            if value is None or not np.isfinite(value) or value < 0:
                reasons.append(f"Invalid {group}.{metric}")
    if reasons:
        return reasons
    # Only validation participates in acceptance; the test set remains an honest audit.
    validation = manifest["validation"]
    if validation["mae"] > settings.max_mae:
        reasons.append("Validation MAE exceeds configured limit")
    if validation["mape"] > settings.max_mape:
        reasons.append("Validation MAPE exceeds configured limit")
    if validation["mae"] > manifest["baseline_validation"]["mae"] * settings.baseline_ratio:
        reasons.append("Validation MAE is worse than the permitted weekly-baseline ratio")
    return reasons


def promote(settings: Settings, version: str, post_check=None) -> dict:
    registry = client(settings)
    manifest = load_manifest(settings, version)
    reasons = acceptance(manifest, settings)
    try:
        bundle = load(settings, version)
    except Exception as exc:
        reasons.append(f"Artifact smoke test failed: {type(exc).__name__}: {exc}")
    if reasons:
        registry.set_model_version_tag(settings.model_name, version, "status", "rejected")
        registry.set_model_version_tag(
            settings.model_name, version, "rejection", "; ".join(reasons)
        )
        return {"accepted": False, "version": version, "reasons": reasons}
    previous = alias_version(settings, settings.model_alias)
    registry.set_registered_model_alias(settings.model_name, "staging", version)
    # A single controller must serialize promotions; aliases are not a distributed transaction.
    if previous and previous != version:
        registry.set_registered_model_alias(settings.model_name, "previous", previous)
    registry.set_registered_model_alias(settings.model_name, settings.model_alias, version)
    try:
        load(settings)
        if post_check:
            post_check(bundle)
        if settings.deployment_check_url:
            verify_deployment(settings, bundle)
    except Exception:
        if previous:
            registry.set_registered_model_alias(settings.model_name, settings.model_alias, previous)
        else:
            registry.delete_registered_model_alias(settings.model_name, settings.model_alias)
        registry.set_model_version_tag(settings.model_name, version, "status", "rolled_back")
        raise
    registry.set_model_version_tag(settings.model_name, version, "status", "approved")
    return {"accepted": True, "version": version, "previous": previous}


def verify_deployment(settings: Settings, bundle: Bundle) -> None:
    """Wait for the serving process to load the alias, then execute a real HTTP forecast."""
    deadline = time.monotonic() + max(60, settings.model_refresh_seconds * 3)
    with httpx.Client(timeout=10) as connection:
        while time.monotonic() < deadline:
            try:
                response = connection.get(settings.deployment_check_url + "/v1/model")
                response.raise_for_status()
                if response.json()["model_version"] == bundle.version:
                    break
            except (httpx.HTTPError, KeyError):
                pass
            time.sleep(2)
        else:
            raise RuntimeError("Deployment did not load the promoted version")
        result = connection.post(
            settings.deployment_check_url + "/v1/forecast",
            json={
                "history": bundle.manifest["smoke_history"],
            },
        )
        result.raise_for_status()
        body = result.json()
        if body["model_version"] != bundle.version or len(body["forecasts"]) != 24:
            raise RuntimeError("Post-deployment forecast contract failed")


def rollback(settings: Settings) -> dict:
    previous = alias_version(settings, "previous")
    if previous is None:
        raise ValueError("There is no previous approved model")
    load(settings, previous)
    current = alias_version(settings, settings.model_alias)
    client(settings).set_registered_model_alias(settings.model_name, settings.model_alias, previous)
    return {"restored": previous, "replaced": current}
