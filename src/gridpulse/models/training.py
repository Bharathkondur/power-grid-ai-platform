import json
import os
import subprocess
from pathlib import Path

import mlflow
import mlflow.xgboost
import numpy as np
import pandas as pd
from mlflow.models import infer_signature
from xgboost import XGBRegressor

from gridpulse.config import Settings
from gridpulse.data.schema import fingerprint, validate
from gridpulse.features import FEATURE_VERSION, at_origin, split_points, supervised


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if not np.isfinite(predicted).all() or (actual <= 0).any():
        raise ValueError("Invalid predictions or non-positive demand labels")
    errors = np.asarray(actual) - np.asarray(predicted)
    return {
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt(np.square(errors).mean())),
        "mape": float((np.abs(errors) / actual).mean() * 100),
    }


def git_commit() -> str:
    if os.environ.get("GRIDPULSE_GIT_COMMIT"):
        return os.environ["GRIDPULSE_GIT_COMMIT"]
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    if result.returncode:
        return "uncommitted"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def train(data: pd.DataFrame, settings: Settings, source: str) -> dict:
    settings.prepare()
    data = validate(data)
    x, y, baseline, times = supervised(data)
    end_train, end_valid = split_points(len(x))
    candidates = []
    for depth in (3, 5):
        model = XGBRegressor(
            n_estimators=300,
            max_depth=depth,
            learning_rate=0.05,
            subsample=1.0,
            colsample_bytree=1.0,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=2,
            tree_method="hist",
        )
        model.fit(x.iloc[:end_train], y[:end_train])
        score = metrics(y[end_train:end_valid], model.predict(x.iloc[end_train:end_valid]))
        candidates.append((score["mae"], model, score))
    _, model, validation = min(candidates, key=lambda candidate: candidate[0])
    # Test is measured once after selection; never used to tune or choose a candidate.
    test = metrics(y[end_valid:], model.predict(x.iloc[end_valid:]))
    baseline_validation = metrics(y[end_train:end_valid], baseline[end_train:end_valid])
    baseline_test = metrics(y[end_valid:], baseline[end_valid:])
    manifest = {
        "feature_version": FEATURE_VERSION,
        "features": list(x.columns),
        "source": source,
        "market": "DE",
        "target": "demand_mw",
        "horizon": 24,
        "data_hash": fingerprint(data),
        "git_commit": git_commit(),
        "data_start": data.timestamp.iloc[0].isoformat(),
        "data_end": data.timestamp.iloc[-1].isoformat(),
        "train_target_end": times[end_train - 1].isoformat(),
        "validation_start": times[end_train].isoformat(),
        "validation_end": times[end_valid - 1].isoformat(),
        "test_start": times[end_valid].isoformat(),
        "test_end": times[-1].isoformat(),
        "validation": validation,
        "test": test,
        "baseline_validation": baseline_validation,
        "baseline_test": baseline_test,
        "baseline_features": x.iloc[:end_train]
        .sample(n=min(2000, end_train), random_state=42)
        .to_dict("list"),
        "smoke_history": json.loads(data.iloc[-168:].to_json(orient="records", date_format="iso")),
        "importance": dict(zip(x.columns, model.feature_importances_.astype(float), strict=True)),
    }
    mlflow.set_tracking_uri(settings.mlflow_uri)
    mlflow.set_experiment(settings.experiment)
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {
                "project_type": "personal_portfolio",
                "source": source,
                "feature_version": FEATURE_VERSION,
                "git_commit": manifest["git_commit"],
                "data_hash": manifest["data_hash"],
            }
        )
        mlflow.log_params(model.get_params())
        for prefix, values in [
            ("validation", validation),
            ("test", test),
            ("baseline_validation", baseline_validation),
            ("baseline_test", baseline_test),
        ]:
            mlflow.log_metrics({f"{prefix}_{key}": value for key, value in values.items()})
        mlflow.log_dict(manifest, "manifest.json")
        example = at_origin(data.iloc[-168:])
        info = mlflow.xgboost.log_model(
            model,
            name="model",
            input_example=example.iloc[:2],
            signature=infer_signature(example, model.predict(example)),
        )
        version = mlflow.register_model(info.model_uri, settings.model_name)
        mlflow.set_tag("model_version", version.version)
        client = mlflow.MlflowClient()
        client.set_model_version_tag(settings.model_name, version.version, "status", "candidate")
        manifest.update(run_id=run.info.run_id, model_version=str(version.version))
        mlflow.log_dict(manifest, "manifest.json")
    (settings.runtime / "last-training.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_manifest(settings: Settings, version: str) -> dict:
    mlflow.set_tracking_uri(settings.mlflow_uri)
    registered = mlflow.MlflowClient().get_model_version(settings.model_name, version)
    path = mlflow.artifacts.download_artifacts(
        run_id=registered.run_id, artifact_path="manifest.json"
    )
    return json.loads(Path(path).read_text())
