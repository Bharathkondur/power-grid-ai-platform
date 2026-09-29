import json

from fastapi.testclient import TestClient

from apps.api.main import create_app
from gridpulse.data.sources import synthetic
from gridpulse.models.registry import promote


def payload(data):
    return {"history": json.loads(data.iloc[-168:].to_json(orient="records", date_format="iso"))}


def test_forecast_schema_metrics_and_invalid_requests(trained):
    settings, data, manifest = trained
    promote(settings, manifest["model_version"])
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        response = client.post("/v1/forecast", json=payload(data))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model_version"] == manifest["model_version"]
        assert len(body["forecasts"]) == 24
        assert body["forecasts"][0]["target"] == "demand_mw"
        assert response.headers["x-request-id"] == body["request_id"]
        batch = client.post("/v1/batch-forecast", json={"requests": [payload(data), payload(data)]})
        assert batch.status_code == 200 and len(batch.json()) == 2
        bad = payload(data)
        del bad["history"][0]["temperature"]
        assert client.post("/v1/forecast", json=bad).status_code == 422
        bad = payload(data)
        bad["history"][1]["timestamp"] = bad["history"][0]["timestamp"]
        assert client.post("/v1/forecast", json=bad).status_code == 422
        exposition = client.get("/metrics").text
        assert "gridpulse_prediction_mw_count" in exposition
        assert "gridpulse_missing_features_total 1.0" in exposition


def test_unavailable_model_is_not_ready(tmp_path):
    from gridpulse.config import Settings

    settings = Settings(
        runtime=tmp_path,
        database_url=f"sqlite:///{tmp_path}/d.db",
        mlflow_uri=f"sqlite:///{tmp_path}/m.db",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/v1/forecast", json=payload(synthetic(10))).status_code == 503
