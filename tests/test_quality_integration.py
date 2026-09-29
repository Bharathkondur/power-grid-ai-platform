import uuid

import pandas as pd

from gridpulse.data.storage import Store
from gridpulse.models.registry import load
from gridpulse.monitoring.quality import monitor


def test_actual_join_and_duplicate_requests_do_not_inflate_sample_count(trained):
    settings, data, _ = trained
    store = Store(settings)
    store.save_data(data, "synthetic")
    bundle = load(settings)
    assert monitor(settings)["status"] == "insufficient_predictions"
    for cutoff in (len(data) - 48, len(data) - 24):
        history = data.iloc[cutoff - 168 : cutoff]
        features, values = bundle.forecast(history)
        origin = history.timestamp.iloc[-1]
        rows = [
            {
                "prediction": float(value),
                "forecast_timestamp": (origin + pd.Timedelta(hours=i + 1)).isoformat(),
            }
            for i, value in enumerate(values)
        ]
        for _ in range(2):
            store.save_forecast(
                uuid.uuid4().hex, "synthetic", bundle.version, origin.isoformat(), features, rows
            )
    report = monitor(settings)
    assert report["prediction_count"] == report["matched_count"] == 48
    assert report["performance"]["mae"] > 0
    assert report["psi"]
