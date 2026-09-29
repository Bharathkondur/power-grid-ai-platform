import numpy as np
import pandas as pd
import pytest

from gridpulse.config import Settings
from gridpulse.data.schema import DataQualityError, fingerprint, validate
from gridpulse.data.sources import synthetic
from gridpulse.data.storage import Store


@pytest.mark.parametrize(
    "corruption", ["duplicate", "gap", "nan", "naive", "order", "column", "inf"]
)
def test_reject_corruption(corruption):
    frame = synthetic(10)
    if corruption == "duplicate":
        frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    elif corruption == "gap":
        frame = frame.drop(5)
    elif corruption == "nan":
        frame.loc[5, "temperature"] = np.nan
    elif corruption == "naive":
        frame.timestamp = frame.timestamp.dt.tz_localize(None)
    elif corruption == "order":
        frame = frame.iloc[::-1]
    elif corruption == "column":
        frame = frame.rename(columns={"demand": "new_schema"})
    else:
        frame.loc[3, "demand"] = np.inf
    with pytest.raises(DataQualityError):
        validate(frame)


def test_staleness_and_future():
    data = synthetic(10)
    for delta in (4, -1):
        with pytest.raises(DataQualityError):
            validate(data, now=data.timestamp.iloc[-1] + pd.Timedelta(hours=delta))


def test_storage_roundtrip_and_idempotency(tmp_path):
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/db.sqlite", runtime=tmp_path))
    data = synthetic(10)
    store.save_data(data, "synthetic")
    store.save_data(data, "synthetic")
    assert fingerprint(store.read_data("synthetic")) == fingerprint(data)


def test_synthetic_reproducible():
    assert fingerprint(synthetic(10)) == fingerprint(synthetic(10))
